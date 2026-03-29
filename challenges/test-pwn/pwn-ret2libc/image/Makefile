CC = gcc
CFLAGS = -fno-stack-protector -no-pie -w

all: ret2libc

ret2libc: ret2libc.c
	$(CC) $(CFLAGS) -o ret2libc ret2libc.c

clean:
	rm -f ret2libc
