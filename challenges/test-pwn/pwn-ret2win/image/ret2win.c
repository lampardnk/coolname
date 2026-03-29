#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

void win() {
    FILE *f = fopen("/flag.txt", "r");
    if (!f) { puts("flag.txt not found"); exit(1); }
    char buf[64];
    fgets(buf, sizeof(buf), f);
    fclose(f);
    printf("You win! Flag: %s\n", buf);
    fflush(stdout);
}

void vuln() {
    char name[64];
    printf("What's your name? ");
    fflush(stdout);
    /* gets() is intentionally vulnerable */
    gets(name);
    printf("Hello, %s!\n", name);
    fflush(stdout);
}

int main() {
    /* Unbuffered I/O for socat compatibility */
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Ret2Win Challenge ===");
    puts("Can you call the win() function?");
    vuln();
    puts("Goodbye!");
    return 0;
}
