#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Format string vulnerability: printf(buf) where buf is user-controlled.
 * The flag is pushed onto the stack as a local char array before printf is called,
 * so it's directly leakable via %p or %s format specifiers.
 *
 * Protections: NX, stack canary (no PIE so addresses are fixed, but canary is random)
 */

#define FLAG_PATH "/flag.txt"

void run() {
    /* Flag lives on the stack right here */
    char flag[64];
    {
        FILE *f = fopen(FLAG_PATH, "r");
        if (!f) { perror("fopen"); exit(1); }
        fgets(flag, sizeof(flag), f);
        fclose(f);
        /* Strip newline */
        flag[strcspn(flag, "\n")] = '\0';
    }

    char buf[128];
    printf("Echo server — send me a message: ");
    fflush(stdout);

    if (!fgets(buf, sizeof(buf), stdin)) return;

    /* VULNERABLE: direct user input to printf */
    printf(buf);
    fflush(stdout);

    /* Scrub flag from stack (too late — already leaked) */
    memset(flag, 0, sizeof(flag));
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Format String Leak ===");
    puts("Find the flag hidden on the stack.");
    run();
    return 0;
}
