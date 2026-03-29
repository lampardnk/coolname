FROM ubuntu:22.04 AS builder
RUN apt-get update -q && apt-get install -y --no-install-recommends gcc libc6-dev make
WORKDIR /build
COPY rop.c Makefile ./
RUN make

FROM ubuntu:22.04
RUN apt-get update -q && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/rop ./rop
COPY --from=builder /lib/x86_64-linux-gnu/libc.so.6 ./libc.so.6
RUN echo 'CTF{rop_chain_full_mitigation_bypass}' > /flag.txt && \
    chmod 755 ./rop && chmod 644 /flag.txt libc.so.6
EXPOSE 31337
CMD ["socat", "-T", "60", "TCP-LISTEN:31337,reuseaddr,fork", "EXEC:./rop,stderr"]
