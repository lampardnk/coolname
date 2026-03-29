#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Full-mitigation ROP challenge.
 *
 * Stage 1 — format string:
 *   printf(buf) leaks: canary (looks like 0x????00), PIE base, libc ptr
 *
 * Stage 2 — buffer overflow:
 *   Bypass canary with leaked value, build ROP chain:
 *   pop rdi; ret → "/bin/sh" in libc → system()
 *
 * Protections: NX, stack canary, PIE, Full RELRO, ASLR
 */

void run() {
    char buf[64];

    /* Stage 1: format string leak */
    printf("Format: ");
    fflush(stdout);
    fgets(buf, sizeof(buf) - 1, stdin);
    buf[63] = '\0';
    printf(buf);   /* VULNERABLE */
    fflush(stdout);

    /* Stage 2: stack overflow */
    printf("Input:  ");
    fflush(stdout);
    read(0, buf, 256);  /* overflow: reads 256 into a 64-byte buffer */
    puts("Done.");
    fflush(stdout);
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== ROP Emperor ===");
    puts("Leak. Pivot. Win.");
    /* puts() → appears in GOT/PLT for leak chains */
    run();
    return 0;
}
