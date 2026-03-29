#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>

/*
 * NX is disabled (-z execstack). The stack is executable.
 * The program reads up to 256 bytes into a fixed-size buffer,
 * then calls a function pointer that points to that buffer.
 */
void vuln() {
    char buf[128];
    printf("Send me your shellcode (max 256 bytes): ");
    fflush(stdout);
    ssize_t n = read(0, buf, 256);
    if (n <= 0) return;

    /* Jump to the buffer — execute whatever was sent */
    void (*fp)(void) = (void (*)(void))buf;
    fp();
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Shellcraft Challenge ===");
    puts("The stack is executable. Send shellcode to get a shell.");
    puts("Flag is at /flag.txt");
    vuln();
    return 0;
}
