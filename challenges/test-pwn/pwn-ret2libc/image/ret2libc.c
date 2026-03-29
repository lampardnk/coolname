#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Classic ret2libc: no PIE, no canary, NX on.
 * Player must:
 *   1. Overflow buffer → call puts(puts@got) to leak libc address
 *   2. Return to vuln() again
 *   3. Overflow → call system("/bin/sh") with computed libc base
 *
 * Compile: gcc -fno-stack-protector -no-pie -o ret2libc ret2libc.c
 */

void vuln() {
    char buf[64];
    printf("Enter input: ");
    fflush(stdout);
    /* gets() overflow — no canary, no PIE */
    gets(buf);
    printf("You said: %s\n", buf);
    fflush(stdout);
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Ret2Libc ===");
    puts("NX is on. Shellcode won't work. Think ROP.");
    /* Call puts so it appears in PLT/GOT (needed for leak) */
    puts("Hint: puts@plt is available for your ROP chain.");
    vuln();
    return 0;
}
