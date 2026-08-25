# Running xv6-riscv

## Install dependencies

```bash
sudo pacman -Syu
sudo apt install -y build-essential gdb-multiarch \
    qemu-system-misc gcc-riscv64-linux-gnu binutils-riscv64-linux-gnu
```

## Build and run

From the xv6 directory inside this repo:

```bash
make
make qemu
```

To exit QEMU: `Ctrl-a` then `x`.
