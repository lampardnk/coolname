CC = gcc
CFLAGS = -fno-stack-protector -no-pie -z execstack -w

all: shellcraft

shellcraft: shellcraft.c
	$(CC) $(CFLAGS) -o shellcraft shellcraft.c

clean:
	rm -f shellcraft
