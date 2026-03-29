CC = gcc
# Full mitigations: canary, PIE, Full RELRO, NX
CFLAGS = -fstack-protector-strong -pie -fPIE -Wl,-z,relro,-z,now -w

all: notes

notes: notes.c
	$(CC) $(CFLAGS) -o notes notes.c

clean:
	rm -f notes
