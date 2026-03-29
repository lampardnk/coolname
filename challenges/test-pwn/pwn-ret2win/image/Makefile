CC = gcc
CFLAGS = -fno-stack-protector -no-pie -z execstack -w

all: ret2win

ret2win: ret2win.c
	$(CC) $(CFLAGS) -o ret2win ret2win.c

clean:
	rm -f ret2win
