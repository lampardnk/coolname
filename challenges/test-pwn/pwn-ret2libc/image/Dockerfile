FROM ubuntu:22.04 AS builder
RUN apt-get update -q && apt-get install -y --no-install-recommends gcc libc6-dev make
WORKDIR /build
COPY ret2libc.c Makefile ./
RUN make

FROM ubuntu:22.04
RUN apt-get update -q && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/ret2libc ./ret2libc
# Also expose libc for players to download
COPY --from=builder /lib/x86_64-linux-gnu/libc.so.6 ./libc.so.6
RUN echo 'CTF{ret2libc_rop_leak_system_binsh}' > /flag.txt && \
    chmod 755 ./ret2libc && chmod 644 /flag.txt libc.so.6
EXPOSE 31337
CMD ["socat", "-T", "60", "TCP-LISTEN:31337,reuseaddr,fork", "EXEC:./ret2libc,stderr"]
