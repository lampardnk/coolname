CC = gcc
CFLAGS = -fstack-protector-strong -pie -fPIE -Wl,-z,relro,-z,now -w

all: vm

vm: vm.c
	$(CC) $(CFLAGS) -o vm vm.c

clean:
	rm -f vm
