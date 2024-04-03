'''
Extract CIDs from the IPFS daemon stdout/stderr and check for provider liveness
- Anish Sujanani, 2024.
'''

import argparse
import os
import sys
import subprocess
import time
import datetime
import threading
import queue
import json
import logging

thread_kill_signal = False

def thread_provider_check(sem, q, FINDPROVS_TIMEOUT_SECONDS, output_fpath):
    global thread_kill_signal
    
    while True:
        if thread_kill_signal:
            logging.debug(f'FINDPROV thread {threading.get_ident()} got KILL signal from main thread')
            return
        
        if q.qsize() == 0:
            logging.debug(f'FINDPROV thread {threading.get_ident()} discovered queue size: 0')
            time.sleep(10)
            continue
        
        item = q.get()
        if sem.acquire():
            logging.debug(f'Thread {threading.get_ident()} got sem (sem val: {sem._value}), processing item {item}')
            
            p_findprovs = subprocess.Popen(['ipfs', 'dht', 'findprovs', item], stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
            logging.debug(f'FINDPROV thread {threading.get_ident()} started IPFS FINDPROV process, pid: {p_findprovs.pid}')
            
            time.sleep(FINDPROVS_TIMEOUT_SECONDS)
            
            p_findprovs.terminate()
            p_findprovs.kill()
            logging.debug(f'FINDPROV thread {threading.get_ident()} killed IPFS FINDPROV process, pid: {p_findprovs.pid}')

            p_findprovs_stdout = p_findprovs.communicate()[0]
            
            # if we get some sort of ipfs error for locks on local fs
            with open(f'{os.path.join(output_fpath, str(threading.get_ident()))}', 'a') as f:
                if 'someone else has the lock' in str(p_findprovs_stdout):
                    logging.debug(f'FINDPROV thread {threading.get_ident()} on item {item} got "someone else has the lock" IPFS error')
                    f.write(f'someone else has the lock when trying getprovs for: {item}, placing back in q\n')
                    logging.debug(f'FINDPROV thread {threading.get_ident()} placing item {item} back onto queue')
                    q.put(item)
                # else check if we have any providers
                else:
                    if len(p_findprovs_stdout) > 0:
                        logging.debug(f'FINDPROV thread {threading.get_ident()} on item {item} found providers: {p_findprovs_stdout}')
                        f.write(f'{item} has providers\n')
                    else:
                        logging.debug(f'FINDPROV thread {threading.get_ident()} on item {item} did not find providers')
                        f.write(f'{item} does not have any peers discovered after {FINDPROVS_TIMEOUT_SECONDS} seconds\n')
            
            logging.debug(f'FINDPROV thread {threading.get_ident()} releasing semaphore. qsize: {q.qsize()}')
            sem.release()
            
            # without the following sleep, the loop immediately starts over
            # and this thread gets the semaphore, not allowign the main thread
            # to take it back. Tried running this many, many times, main thread
            # never got the semaphore back. Probably some optimization with
            # the while loop that immediately executes before the threads can
            # race for capturing the semaphore?
            time.sleep(1)

def thread_grep_func(fname, q):
    p = subprocess.Popen(['grep', '-nria', '"cid": "Qm', fname], stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    logging.debug(f'GREP thread {threading.get_ident()} started BASH GREP process, pid: {p.pid}')
    
    p_stdout = p.communicate()[0]
    logging.debug(f'GREP thread {threading.get_ident()} got completion signal from BASH GREP process, pid: {p.pid}')
    
    raw_jsons = []
    for line in p_stdout.split(b'\n'):
        try:
            raw_jsons.append(json.loads(line.split(b'\t')[-1]))
        except Exception as e:
            pass
    
    cid_set = set()
    for j in raw_jsons:
        try:
            cid_set.add(j['cid'])
        except Exception as e:
            logging.error(f'Exception in GREP thread: {e} when trying to parse CIDs out of {j}')

    for c in cid_set:
        q.put(c)

    logging.debug(f'GREP thread {threading.get_ident()} discovered {len(raw_jsons)} CIDs, unique: {len(cid_set)}')

def parse_args():
    ap = argparse.ArgumentParser(
            prog="IPFS CID-dump",
            description="Multi-threaded IPFS daemon log parser and CID extractor"
        )
    ap.add_argument(
            '--log-level', 
            choices=['DEBUG', 'INFO'], 
            default='INFO', 
            dest='LOGLEVEL',
            help='controls log verbosity to stdout'
            )
    ap.add_argument(
            '--ipfs-cycles',
            type=int,
            default=2,
            dest='NUM_IPFS_CYCLES',
            help='controls the number of times the main thread starts and kills an IPFS daemon'
        )
    ap.add_argument(
            '--ipfs-daemon-runtime-seconds', 
            type=int, 
            default=120,
            dest='IPFS_DAEMON_RUNTIME_SECONDS',
            help='specifies how many seconds each IPFS daemon cycle lasts'
            )
    ap.add_argument(
            '--num-findprov-threads',
            type=int,
            default=4,
            dest='NUM_FINDPROV_THREADS',
            help='specifies the number of threads that will search for CID liveness (provider peers)'
            )
    ap.add_argument(
            '--findprovs-timeout-seconds',
            type=int,
            default=6,
            dest='FINDPROVS_TIMEOUT_SECONDS',
            help='specifies how long each findprov thread will run to determine peer availability'
            )
    ap.add_argument(
            '--ipfs-daemon-output-dir',
            type=str,
            default='./ipfsrawlog',
            dest='IPFS_DAEMON_OUTPUT_DIR',
            help='path to directory where the IPFS deamon will dump logs in debug mode'
            )
    ap.add_argument(
            '--cid-output-dir',
            type=str,
            default='./cids/',
            dest='CID_OUTPUT_DIR',
            help='path to directory where each findprov thread will write CIDs to individual files'
            )
    return ap.parse_args()

def check_or_create_dirs(*dirs):
	logging.debug(f'Main thread checking or creating directories {dirs}')
	[os.makedirs(d) for d in dirs if not os.path.exists(d)]

def main():    
    args = parse_args()
    
    logging.basicConfig(level=args.LOGLEVEL, format='%(levelname)s: %(message)s')
    check_or_create_dirs(args.IPFS_DAEMON_OUTPUT_DIR, args.CID_OUTPUT_DIR)

    ipfs_daemon_proc = -1
    sem = threading.BoundedSemaphore(value=args.NUM_FINDPROV_THREADS)
    q = queue.Queue() 
    global thread_kill_signal

    # start main thread functionality off while holding all locks
    for i in range(args.NUM_FINDPROV_THREADS):
        sem.acquire()
    logging.debug(f'Main thread now has all semaphores, sem val: {sem._value}')

    threads = []
    for i in range(args.NUM_FINDPROV_THREADS):
        t = threading.Thread(target=thread_provider_check, args=(sem, q, args.FINDPROVS_TIMEOUT_SECONDS, args.CID_OUTPUT_DIR))
        threads.append(t)
        t.start()

    loops = 0
    while loops != args.NUM_IPFS_CYCLES:
        is_last_cycle = loops == args.NUM_IPFS_CYCLES - 1

        logging.info(f'On IPFS cycle: {loops+1}')
        date_str = str(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S'))
        fname = os.path.join(args.IPFS_DAEMON_OUTPUT_DIR, date_str)
        fi = open(fname, 'wb')
        
        # start ipfs daemon
        ipfs_daemon_proc = subprocess.Popen(['ipfs', 'daemon', '-D'], stderr=subprocess.STDOUT, stdout=fi) 
        logging.info(f'Main thread started IPFS daemon, PID: {ipfs_daemon_proc.pid}, runtime: {args.IPFS_DAEMON_RUNTIME_SECONDS} seconds')
       
        # release sempaphores for cat/download threads to interact with ipfs from previous loop output
        sem.release(args.NUM_FINDPROV_THREADS)
        logging.debug(f'Main thread has now released all semaphores, sem val: {sem._value}')
        
        logging.debug(f'Main thread sleeping for {args.IPFS_DAEMON_RUNTIME_SECONDS}, threads may interact with IPFS until then')
        time.sleep(args.IPFS_DAEMON_RUNTIME_SECONDS)
 
        logging.debug(f'Main thread is now trying to get all semaphores to safely kill IPFS daemon')
        # as long as this is not the last cycle, get semaphores and kill IPFS
        # if it is the last cycle, then do not kill the process
        # this loop will exist, then we'll wait for threads to complete
        if is_last_cycle == False:
            # restart ipfs daemon on the next iteration of this loop
            # but if any of the provider threads are midway or about to execute a 'cat' or 'download' operation
            # and the daemon is dead, it will fail
            # capture # semaphores = # threads so that they will all wait till this thread releases them
            for i in range(args.NUM_FINDPROV_THREADS):
                sem.acquire()
        
            logging.debug('Main thread got all sempahores. Killing IPFS daemon now.')

            # we have all semaphores at this point, safe to kill process
            ipfs_daemon_proc.terminate()
            ipfs_daemon_proc.kill()
            logging.info(f'Main thread killed IPFS daemon, PID: {ipfs_daemon_proc.pid}')

        # start the thread here that greps the file we just wrote, pushes hashes to q, then deletes file
        # no need to join() on this thread, it will finish when done
        # after this, start using semaphores to control cat threads
        logging.debug(f'Main thread starting a thread to load PID {ipfs_daemon_proc.pid} stdout/stderr into queue')
        (threading.Thread(target=thread_grep_func, args=(fname, q,))).start() 
        time.sleep(1)

        # adding a generic 'calculating' message in the case where grep takes >1s for large IPFS daemon stdout
        logging.info(f'Queue size: {"Calculating" if q.qsize() == 0 else q.qsize()}')

        # restart loop, restart ipfs process and release semaphores
        loops += 1

    logging.info(f'{args.NUM_IPFS_CYCLES} IPFS cycles complete, waiting for {threading.active_count()} threads to empty queue ({q.qsize()})')
    while q.qsize() != 0:
        time.sleep(60)
    # add another few seconds as max processing time if any threads are still running
    time.sleep(args.FINDPROVS_TIMEOUT_SECONDS) 
    # q is empty, we can safely kill threads and processes
    logging.debug(f'Queue size: {q.qsize()}. Setting kill signal to true which will end all findprov threads')
    thread_kill_signal = True
    ipfs_daemon_proc.terminate()
    ipfs_daemon_proc.kill()
    time.sleep(10)
    logging.debug(f'Killed threads. Thread count is now: {threading.active_count()}')
    logging.info(f'Threads have emptied queue and ended. Output: {args.CID_OUTPUT_DIR}. Main thread quitting.')

if __name__ == '__main__':
    main()
