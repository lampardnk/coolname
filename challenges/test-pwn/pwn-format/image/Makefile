CC = gcc
# Canary ON, PIE OFF, NX ON
CFLAGS = -fstack-protector-strong -no-pie -w

all: format

format: format.c
	$(CC) $(CFLAGS) -o format format.c

clean:
	rm -f format
