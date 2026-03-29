CC = gcc
CFLAGS = -fno-stack-protector -no-pie -w

all: pivot

pivot: pivot.c
	$(CC) $(CFLAGS) -o pivot pivot.c

clean:
	rm -f pivot
