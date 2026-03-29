FROM ubuntu:22.04 AS builder
RUN apt-get update -q && apt-get install -y --no-install-recommends gcc libc6-dev make
WORKDIR /build
COPY shellcraft.c Makefile ./
RUN make

FROM ubuntu:22.04
RUN apt-get update -q && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/shellcraft ./shellcraft
RUN echo 'CTF{shellcode_execve_stack_nop_sled}' > /flag.txt && \
    chmod 755 ./shellcraft && chmod 644 /flag.txt
EXPOSE 31337
CMD ["socat", "-T", "60", "TCP-LISTEN:31337,reuseaddr,fork", "EXEC:./shellcraft,stderr"]
