#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Heap Art — off-by-one heap overflow
 *
 * The "gallery" stores frames: a size field + data buffer allocated together.
 * resize() calls realloc() but the bounds check is `size <= MAX` (should be `<`),
 * allowing one extra byte to be written past the allocation — into the next chunk
 * header's size field.
 *
 * The "secret" struct sits right after in the same tcache bin, so corrupting
 * its chunk size tricks the allocator into treating it as a different bin.
 *
 * For simplicity, a win() function exists. The secret struct has a fn pointer.
 * Corrupt chunk metadata → get overlapping allocation → overwrite fn pointer.
 *
 * Protections: NX, canary, PIE, Full RELRO, ASLR
 */

#define MAX_FRAMES 4
#define FRAME_MAX  120

typedef struct {
    size_t  size;
    char   *data;
} Frame;

typedef struct {
    void (*action)(void);
    char  secret[56];
} Secret;

static Frame  *frames[MAX_FRAMES];
static Secret *s_obj;

void win() {
    FILE *f = fopen("/flag.txt", "r");
    if (!f) { puts("no flag.txt"); return; }
    char buf[64];
    fgets(buf, sizeof(buf), f);
    fclose(f);
    printf("Flag: %s\n", buf);
    fflush(stdout);
}

void init_secret() {
    s_obj = malloc(sizeof(Secret));
    s_obj->action = NULL;
    memset(s_obj->secret, 0, sizeof(s_obj->secret));
}

void create_frame(int idx, size_t sz) {
    if (frames[idx]) { puts("exists"); return; }
    if (sz == 0 || sz > FRAME_MAX) { puts("bad size"); return; }
    frames[idx] = malloc(sizeof(Frame));
    frames[idx]->size = sz;
    frames[idx]->data = malloc(sz);
    memset(frames[idx]->data, 0, sz);
    printf("Created frame[%d] size=%zu\n", idx, sz);
    fflush(stdout);
}

void write_frame(int idx) {
    if (!frames[idx]) { puts("null"); return; }
    size_t sz = frames[idx]->size;
    printf("Write (max %zu): ", sz);
    fflush(stdout);
    /* OFF-BY-ONE: reads sz+1 bytes into a sz-byte buffer */
    ssize_t n = read(0, frames[idx]->data, sz + 1);
    printf("Wrote %zd bytes.\n", n);
    fflush(stdout);
}

void show_frame(int idx) {
    if (!frames[idx]) { puts("null"); return; }
    printf("Frame[%d]: ", idx);
    fwrite(frames[idx]->data, 1, frames[idx]->size, stdout);
    putchar('\n');
    fflush(stdout);
}

void free_frame(int idx) {
    if (!frames[idx]) return;
    free(frames[idx]->data);
    free(frames[idx]);
    frames[idx] = NULL;
    puts("Freed.");
}

void trigger_secret() {
    if (!s_obj->action) { puts("no action set"); return; }
    s_obj->action();
}

void menu() {
    puts("\n1. Create  2. Write  3. Show  4. Free  5. Trigger  6. Exit");
    printf("> ");
    fflush(stdout);
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== Heap Art Gallery ===");
    printf("win()   @ %p\n", (void *)win);
    printf("s_obj   @ %p\n", (void *)&s_obj);

    init_secret();

    int choice, idx;
    size_t sz;
    while (1) {
        menu();
        if (scanf("%d", &choice) != 1) break;
        getchar();
        switch (choice) {
        case 1:
            printf("Index (0-3): "); fflush(stdout);
            scanf("%d", &idx); getchar();
            printf("Size: "); fflush(stdout);
            scanf("%zu", &sz); getchar();
            create_frame(idx, sz);
            break;
        case 2:
            printf("Index: "); fflush(stdout);
            scanf("%d", &idx); getchar();
            write_frame(idx);
            break;
        case 3:
            printf("Index: "); fflush(stdout);
            scanf("%d", &idx); getchar();
            show_frame(idx);
            break;
        case 4:
            printf("Index: "); fflush(stdout);
            scanf("%d", &idx); getchar();
            free_frame(idx);
            break;
        case 5:
            trigger_secret();
            break;
        case 6:
            return 0;
        default:
            puts("?");
        }
    }
    return 0;
}
