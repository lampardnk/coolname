#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Heap notes challenge — Use-After-Free → tcache poisoning
 *
 * Each note has a function pointer (print_fn) and a data buffer.
 * After free(), the pointer is NOT cleared — classic UAF.
 *
 * Exploit path:
 *   1. Alloc note A (size 0x40)
 *   2. Free note A   → goes into tcache[0x40]
 *   3. View note A   → UAF: read tcache fd pointer → leak heap base
 *   4. Edit note A   → UAF: overwrite tcache fd with target address
 *   5. Alloc note B  → pops A from tcache (A is now reallocated)
 *   6. Alloc note C  → allocates at target address (poisoned tcache)
 *   7. Write system() into print_fn of note C
 *   8. View note C   → calls print_fn("/bin/sh") → shell
 *
 * Protections: NX, canary, PIE, Full RELRO
 */

#define MAX_NOTES 8
#define NOTE_DATA 56

typedef struct Note {
    void (*print_fn)(char *);
    char data[NOTE_DATA];
} Note;

static Note *notes[MAX_NOTES];

void default_print(char *s) {
    printf("[note] %s\n", s);
    fflush(stdout);
}

void win_print(char *s) {
    (void)s;
    FILE *f = fopen("/flag.txt", "r");
    if (!f) { puts("no flag.txt"); return; }
    char buf[64];
    fgets(buf, sizeof(buf), f);
    fclose(f);
    printf("Flag: %s\n", buf);
    fflush(stdout);
}

static int get_idx(const char *prompt) {
    printf("%s", prompt);
    fflush(stdout);
    int idx;
    if (scanf("%d", &idx) != 1) { puts("bad input"); exit(1); }
    getchar(); /* consume newline */
    return idx;
}

void alloc_note() {
    int idx = get_idx("Note index (0-7): ");
    if (idx < 0 || idx >= MAX_NOTES) { puts("invalid"); return; }
    if (notes[idx]) { puts("already exists"); return; }
    notes[idx] = malloc(sizeof(Note));
    if (!notes[idx]) { puts("oom"); return; }
    notes[idx]->print_fn = default_print;
    memset(notes[idx]->data, 0, NOTE_DATA);
    printf("Content: ");
    fflush(stdout);
    fgets(notes[idx]->data, NOTE_DATA - 1, stdin);
    notes[idx]->data[strcspn(notes[idx]->data, "\n")] = '\0';
    puts("Allocated.");
}

void free_note() {
    int idx = get_idx("Note index: ");
    if (idx < 0 || idx >= MAX_NOTES || !notes[idx]) { puts("invalid"); return; }
    free(notes[idx]);
    /* BUG: pointer not cleared → UAF */
    puts("Freed.");
}

void view_note() {
    int idx = get_idx("Note index: ");
    if (idx < 0 || idx >= MAX_NOTES || !notes[idx]) { puts("invalid"); return; }
    notes[idx]->print_fn(notes[idx]->data);
}

void edit_note() {
    int idx = get_idx("Note index: ");
    if (idx < 0 || idx >= MAX_NOTES || !notes[idx]) { puts("invalid"); return; }
    printf("New content (hex bytes, e.g. '41 42 43'): ");
    fflush(stdout);
    char line[256];
    fgets(line, sizeof(line), stdin);
    /* Write raw bytes — allows overwriting print_fn pointer */
    unsigned char *dst = (unsigned char *)notes[idx];
    char *tok = strtok(line, " \t\n");
    int off = 0;
    while (tok && off < (int)sizeof(Note)) {
        dst[off++] = (unsigned char)strtoul(tok, NULL, 16);
        tok = strtok(NULL, " \t\n");
    }
    printf("Written %d byte(s).\n", off);
    fflush(stdout);
}

void print_menu() {
    puts("\n--- Notes ---");
    puts("1. Alloc");
    puts("2. Free");
    puts("3. View");
    puts("4. Edit");
    puts("5. Exit");
    printf("> ");
    fflush(stdout);
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Heap Notes ===");
    printf("win_print is at: %p\n", (void *)win_print);

    int choice;
    while (1) {
        print_menu();
        if (scanf("%d", &choice) != 1) break;
        getchar();
        switch (choice) {
            case 1: alloc_note(); break;
            case 2: free_note();  break;
            case 3: view_note();  break;
            case 4: edit_note();  break;
            case 5: return 0;
            default: puts("unknown");
        }
    }
    return 0;
}
