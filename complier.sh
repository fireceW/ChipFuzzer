#!/bin/bash

# 检查是否提供了输入文件
if [ $# -eq 0 ]; then
    echo "Usage: $0 <assembly_file.S> [output_bin_name]"
    exit 1
fi

# 获取输入文件名
input_file=$1

# 检查文件是否存在
if [ ! -f "$input_file" ]; then
    echo "Error: File '$input_file' not found!"
    exit 1
fi

# 设置输出 bin 文件名
if [ $# -ge 2 ]; then
    output_bin=$2
else
    # 如果没有提供输出文件名，则使用输入文件的基本名加上 .bin
    output_bin="${input_file%.*}.bin"
fi

# 设置工具链路径（根据你的实际路径可能需要调整）
TOOLCHAIN_PATH="/opt/riscv/bin"
AS="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-as"
LD="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-ld"
OBJCOPY="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-objcopy"

# 临时目标文件和临时 elf 文件
temp_obj="${input_file%.*}.o"
temp_elf="${input_file%.*}.elf"

# 汇编命令
echo "Assembling $input_file..."
$AS -march=rv64gc -o "$temp_obj" "$input_file"
if [ $? -ne 0 ]; then
    echo "Assembly failed!"
    exit 1
fi

# 链接命令（先生成临时 ELF）
echo "Linking $temp_obj to $temp_elf..."
$LD -o "$temp_elf" "$temp_obj"
if [ $? -ne 0 ]; then
    echo "Linking failed!"
    rm -f "$temp_obj"
    exit 1
fi

# 使用 objcopy 生成纯二进制 .bin 文件
echo "Converting $temp_elf to raw binary $output_bin..."
$OBJCOPY -O binary "$temp_elf" "$output_bin"
if [ $? -ne 0 ]; then
    echo "Objcopy failed!"
    rm -f "$temp_obj" "$temp_elf"
    exit 1
fi

# 清理临时文件
rm -f "$temp_obj" "$temp_elf"

echo "Successfully built $output_bin"
