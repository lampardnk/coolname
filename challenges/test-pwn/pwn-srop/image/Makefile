all: srop

srop: srop.asm
	nasm -f elf64 srop.asm -o srop.o
	ld -o srop srop.o

clean:
	rm -f srop srop.o
