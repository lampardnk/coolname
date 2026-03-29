CC = gcc
CFLAGS = -fstack-protector-strong -pie -fPIE -Wl,-z,relro,-z,now -w

all: heap

heap: heap.c
	$(CC) $(CFLAGS) -o heap heap.c

clean:
	rm -f heap
