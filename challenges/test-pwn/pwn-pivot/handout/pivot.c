#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Stack Pivot — tight overflow, staged ROP
 *
 * The buffer overflow is only 16 bytes past saved RIP (not enough for a chain).
 * However, a global buffer `stage_buf` exists and is writable.
 *
 * Exploit flow:
 *   1. Call setup() — fills stage_buf with a full ROP chain via read()
 *   2. Call vuln()  — 8-byte overflow: [rbp = stage_buf - 8][rip = leave_ret]
 *      leave;ret pivots RSP to stage_buf and executes the planted chain
 *   3. Chain: pop rdi; ret → "/bin/sh\0" → system()
 *
 * Protections: NX, no canary, no PIE (so stage_buf address is known)
 */

/* Global staging area — address is known (no PIE) */
char stage_buf[256];

void setup() {
    printf("Stage your ROP chain in stage_buf (%p): ", (void *)stage_buf);
    fflush(stdout);
    /* Read directly into the global buffer */
    read(0, stage_buf, sizeof(stage_buf));
    puts("Staged.");
    fflush(stdout);
}

void vuln() {
    char buf[32];
    printf("Now overflow (read 64 bytes into 32-byte buf): ");
    fflush(stdout);
    read(0, buf, 64);  /* 32 bytes overflow: [buf][saved_rbp][saved_rip][16 extra] */
    puts("Overflow received.");
    fflush(stdout);
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Stack Pivot ===");
    puts("You have 64 bytes of overflow — not enough for a chain.");
    puts("Use a stack pivot to redirect RSP to your staged payload.");
    setup();
    vuln();
    return 0;
}
