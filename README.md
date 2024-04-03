# IPFS CID Dump

Extract CIDs from the IPFS daemon stdout/stderr and check for provider liveness

## Usage

With no specific parameters specified, the program runs with the following configuration:
```
LOG_LEVEL: INFO
NUM_IPFS_CYCLES: 2
IPFS_DAEMON_RUNTIME_SECONDS: 120
NUM_FINDPROV_THREADS: 4
FINDPROVS_TIMEOUT_SECONDS: 4
IPFS_DAEMON_OUTPUT_DIR: ./ipfsrawlog/
CID_OUTPUT_DIR: ./cids/
```

There are no external dependencies. A standard python3.x installation should include everything needed to run this. You can either run the program stand-alone or within a container with volume-mapped directories. 

### Standalone:
```
usage: IPFS CID-dump [-h] [--log-level {DEBUG,INFO}] [--ipfs-cycles NUM_IPFS_CYCLES] [--ipfs-daemon-runtime-seconds IPFS_DAEMON_RUNTIME_SECONDS]
                     [--num-findprov-threads NUM_FINDPROV_THREADS] [--findprovs-timeout-seconds FINDPROVS_TIMEOUT_SECONDS]
                     [--ipfs-daemon-output-dir IPFS_DAEMON_OUTPUT_DIR] [--cid-output-dir CID_OUTPUT_DIR]

Multi-threaded IPFS daemon log parser and CID extractor

options:
  -h, --help            show this help message and exit
  --log-level {DEBUG,INFO}
                        controls log verbosity to stdout
  --ipfs-cycles NUM_IPFS_CYCLES
                        controls the number of times the main thread starts and kills an IPFS daemon
  --ipfs-daemon-runtime-seconds IPFS_DAEMON_RUNTIME_SECONDS
                        specifies how many seconds each IPFS daemon cycle lasts
  --num-findprov-threads NUM_FINDPROV_THREADS
                        specifies the number of threads that will search for CID liveness (provider peers)
  --findprovs-timeout-seconds FINDPROVS_TIMEOUT_SECONDS
                        specifies how long each findprov thread will run to determine peer availability
  --ipfs-daemon-output-dir IPFS_DAEMON_OUTPUT_DIR
                        path to directory where the IPFS deamon will dump logs in debug mode
  --cid-output-dir CID_OUTPUT_DIR
                        path to directory where each findprov thread will write CIDs to individual files
```

### Docker:

Build with:
```
docker build -t ipfsciddump .
```

By default, the program writes to `./ipfsrawlog/` and `./cids/` for IPFS-daemon-logs and CIDs respectively. You can either volume map these directly onto the container, or specify paths explicitly and set the same with `--ipfs-daemon-output-dir` and ` --cid-output-dir`.

Run with:
```
docker run \
  -d --rm \
  -v /host/path/for/rawlogs:/container_ipfs_raw_logs \
  -v /host_path_for_cids:/container_path_for_cids \
  ipfsciddump \
  --log-level DEBUG \
  --ipfs-cycles 3 \
  --ipfs-daemon-runtime 180 \
  --num-findprov-threads 10 \
  --findprovs-timeout-seconds 5 \
  --ipfs-daemon-output-dir /container_ipfs_raw_logs \
  --cid-output-dir /container_path_for_cids
```

Heads up - debug logging can get very verbose. A high thread count, combined with the fact that does not run unbuffered IO (so that log output is readable instead of threads stepping all over each other) can lead to program slowdown. The default `INFO` logging should be sufficient, unless you want to look into each and every thread's functioning.  
