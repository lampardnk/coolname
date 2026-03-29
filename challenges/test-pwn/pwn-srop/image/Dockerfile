FROM ubuntu:22.04 AS builder
RUN apt-get update -q && apt-get install -y --no-install-recommends nasm binutils make
WORKDIR /build
COPY srop.asm Makefile ./
RUN make

FROM ubuntu:22.04
RUN apt-get update -q && apt-get install -y --no-install-recommends socat && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/srop ./srop
RUN echo 'CTF{srop_sigreturn_execve_syscall}' > /flag.txt && \
    chmod 755 ./srop && chmod 644 /flag.txt
EXPOSE 31337
CMD ["socat", "-T", "60", "TCP-LISTEN:31337,reuseaddr,fork", "EXEC:./srop,stderr"]
