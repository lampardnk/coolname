CC = gcc
# Full mitigations
CFLAGS = -fstack-protector-strong -pie -fPIE -Wl,-z,relro,-z,now -w

all: rop

rop: rop.c
	$(CC) $(CFLAGS) -o rop rop.c

clean:
	rm -f rop
