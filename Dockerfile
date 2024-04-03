FROM alpine:latest

RUN 	apk add python3 && \
	wget https://dist.ipfs.tech/kubo/v0.21.0/kubo_v0.21.0_linux-arm64.tar.gz && \
	tar -xzvf kubo_v0.21.0_linux-arm64.tar.gz && \
	./kubo/install.sh && \
	ipfs init 

WORKDIR /

COPY ./ipfs_cid_dump.py .

ENTRYPOINT ["python3", "ipfs_cid_dump.py"]
