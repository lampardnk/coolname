FROM ubuntu:22.04 AS builder
RUN apt-get update -q && apt-get install -y --no-install-recommends gcc libc6-dev make
WORKDIR /build
COPY notes.c Makefile ./
RUN make

FROM ubuntu:22.04
RUN apt-get update -q && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/notes ./notes
RUN echo 'CTF{heap_uaf_tcache_poison_hijack}' > /flag.txt && \
    chmod 755 ./notes && chmod 644 /flag.txt
EXPOSE 31337
CMD ["socat", "-T", "120", "TCP-LISTEN:31337,reuseaddr,fork", "EXEC:./notes,stderr"]
