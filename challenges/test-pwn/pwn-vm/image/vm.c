#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * ByteVM — custom 8-register bytecode interpreter
 *
 * Instruction set:
 *   0x01 rD rA rB  MOV  rD = rA + rB
 *   0x02 rD imm8   LDI  rD = imm8
 *   0x03 rD rA     LOAD rD = mem[rA]       (rA = byte offset into mem[])
 *   0x04 rA rB     STORE mem[rA] = rB      (VULNERABLE: signed comparison)
 *   0x05 rD rA rB  SUB  rD = rA - rB
 *   0x06 addr8     JMP  pc = addr8
 *   0x07           HALT
 *   0x08           PRINT prints mem[] as string
 *
 * Vulnerability: STORE checks `if ((int8_t)reg[rA] >= 0 && reg[rA] < 512)`
 * but reg[] is uint16_t. The cast to int8_t truncates large addresses.
 * If rA holds 0x100 (256), (int8_t)256 = 0 → passes the check and stores
 * to mem[256] which is IN bounds. But with rA = 0xFF80 (sign-extends to
 * negative int8_t) the check fails — that is intentional.
 *
 * The actual bug: the bounds check uses `reg[rA] < 512` as unsigned but
 * reads the register as int16_t for the address calculation, so negative
 * register values result in mem[negative offset] which underflows into host
 * stack frame. Distance from mem[] to saved RIP is leaked at startup.
 *
 * For simplicity: the binary prints the address of win() and the distance
 * from mem to the saved return address so players can focus on VM mechanics.
 *
 * Protections: NX, canary, PIE, Full RELRO
 */

#define MEM_SIZE   512
#define NUM_REGS   8
#define MAX_OPS    256

typedef struct {
    uint16_t regs[NUM_REGS];
    uint8_t  mem[MEM_SIZE];
    uint16_t pc;
} VM;

void win() {
    FILE *f = fopen("/flag.txt", "r");
    if (!f) { puts("no flag.txt"); return; }
    char buf[64];
    fgets(buf, sizeof(buf), f);
    fclose(f);
    printf("Flag: %s\n", buf);
    fflush(stdout);
}

static void vm_run(VM *vm, uint8_t *prog, uint16_t prog_len) {
    int steps = 0;
    while (steps++ < MAX_OPS) {
        if (vm->pc >= prog_len) break;
        uint8_t op = prog[vm->pc++];
        switch (op) {
        case 0x01: { /* MOV rD = rA + rB */
            uint8_t rD = prog[vm->pc++] & 7;
            uint8_t rA = prog[vm->pc++] & 7;
            uint8_t rB = prog[vm->pc++] & 7;
            vm->regs[rD] = vm->regs[rA] + vm->regs[rB];
            break;
        }
        case 0x02: { /* LDI rD = imm16 */
            uint8_t rD = prog[vm->pc++] & 7;
            uint16_t imm = prog[vm->pc] | ((uint16_t)prog[vm->pc+1] << 8);
            vm->pc += 2;
            vm->regs[rD] = imm;
            break;
        }
        case 0x03: { /* LOAD rD = mem[rA] */
            uint8_t rD = prog[vm->pc++] & 7;
            uint8_t rA = prog[vm->pc++] & 7;
            uint16_t addr = vm->regs[rA];
            if (addr < MEM_SIZE) vm->regs[rD] = vm->mem[addr];
            break;
        }
        case 0x04: { /* STORE mem[rA] = rB  ← VULNERABLE */
            uint8_t rA = prog[vm->pc++] & 7;
            uint8_t rB = prog[vm->pc++] & 7;
            /* BUG: addr is uint16_t but cast to int16_t for the write offset,
             * allowing addresses > 32767 (which wrap negative) to escape mem[] */
            int16_t addr = (int16_t)vm->regs[rA];
            /* Bounds check uses unsigned comparison — negative addr is huge */
            if ((uint16_t)addr < MEM_SIZE) {
                vm->mem[(uint16_t)addr] = (uint8_t)vm->regs[rB];
            } else {
                /* VULNERABLE PATH: negative addr bypasses check via OOB ptr */
                /* addr is negative → points before mem[] into the stack frame */
                ((uint8_t *)vm->mem)[addr] = (uint8_t)vm->regs[rB];
            }
            break;
        }
        case 0x05: { /* SUB rD = rA - rB */
            uint8_t rD = prog[vm->pc++] & 7;
            uint8_t rA = prog[vm->pc++] & 7;
            uint8_t rB = prog[vm->pc++] & 7;
            vm->regs[rD] = vm->regs[rA] - vm->regs[rB];
            break;
        }
        case 0x06: { /* JMP addr8 */
            vm->pc = prog[vm->pc];
            break;
        }
        case 0x07: /* HALT */
            return;
        case 0x08: /* PRINT */
            printf("[vm] %.*s\n", MEM_SIZE, (char *)vm->mem);
            fflush(stdout);
            break;
        default:
            return;
        }
    }
}

int main() {
    setvbuf(stdin,  NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);

    puts("=== ByteVM ===");
    puts("Submit bytecode (up to 256 bytes). STORE has a signed addr bug.");

    VM vm;
    memset(&vm, 0, sizeof(vm));

    /* Leak helpers so players can focus on VM mechanics, not offsets */
    printf("win()  @ 0x%lx\n", (unsigned long)win);
    /* Distance from mem[0] to the saved return address on the stack.
     * Negative value → mem[offset] is the return address byte. */
    void *retaddr_ptr = __builtin_return_address(0);
    long dist = (int8_t *)retaddr_ptr - (int8_t *)vm.mem;
    printf("mem[]  @ %p  |  ret offset from mem[0] = %ld\n",
           (void *)vm.mem, dist);

    printf("Bytecode length (1-256): ");
    fflush(stdout);
    int len;
    if (scanf("%d", &len) != 1 || len < 1 || len > 256) {
        puts("bad length");
        return 1;
    }
    getchar();

    uint8_t prog[256];
    printf("Bytecode (hex bytes, space-separated): ");
    fflush(stdout);
    char line[1024];
    fgets(line, sizeof(line), stdin);
    char *tok = strtok(line, " \t\n");
    int i = 0;
    while (tok && i < len) {
        prog[i++] = (uint8_t)strtoul(tok, NULL, 16);
        tok = strtok(NULL, " \t\n");
    }

    vm_run(&vm, prog, (uint16_t)i);
    puts("VM halted.");
    return 0;
}
