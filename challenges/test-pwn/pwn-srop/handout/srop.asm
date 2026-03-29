; srop.asm — minimal SROP challenge
; Assemble: nasm -f elf64 srop.asm -o srop.o && ld -o srop srop.o
;
; Layout:
;   _start: write "Send payload: ", then read 0x200 bytes into bss_buf
;   A `syscall; ret` gadget follows immediately after read — reachable via ROP
;   The read target (bss_buf) is at a fixed address (no ASLR on stack for this)
;
; Exploit:
;   1. Overflow read (read returns to syscall gadget)
;   2. Place fake SigreturnFrame in bss_buf:
;      rax = 15 (rt_sigreturn), rip = syscall_gadget
;      rdi = ptr_to_binsh, rsi = 0, rdx = 0, rax (at call) = 59 (execve)
;   3. Place "/bin/sh\0" at known offset in bss_buf

global _start

section .text

_start:
    ; write(1, banner, banner_len)
    mov     rax, 1
    mov     rdi, 1
    mov     rsi, banner
    mov     rdx, banner_len
    syscall

    ; read(0, bss_buf, 0x200)
    mov     rax, 0
    mov     rdi, 0
    mov     rsi, bss_buf
    mov     rdx, 0x200
    syscall

    ; After read, control returns here (offset overflow overwrites ret addr)
    ; This is also where execution falls if payload is too short
    mov     rax, 60    ; exit
    xor     rdi, rdi
    syscall

; Gadget: syscall; ret  (also used as sigreturn trampoline)
syscall_gadget:
    syscall
    ret

section .data
banner:     db "=== SROP Challenge ===", 0xa
            db "Send payload (max 0x200 bytes): ", 0
banner_len: equ $ - banner

section .bss
bss_buf:    resb 0x200
