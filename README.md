# Running xv6-riscv

## Install dependencies

```bash
sudo pacman -Syu
sudo pacman -S --needed base-devel qemu-system-riscv riscv64-elf-gcc riscv64-elf-binutils gdb
```

## Build and run

From the xv6 directory inside this repo:

```bash
make
make qemu
```

To exit QEMU: `Ctrl-a` then `x`.
