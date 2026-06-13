#!/bin/bash

# Check if input file is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <assembly_file.S> [output_bin_name]"
    exit 1
fi

# Get input file name
input_file=$1

# Check if the file exists
if [ ! -f "$input_file" ]; then
    echo "Error: File '$input_file' not found!"
    exit 1
fi

# Set the output bin file name
if [ $# -ge 2 ]; then
    output_bin=$2
else
    # If no output filename is provided, the basename of the input file plus .bin is used
    output_bin="${input_file%.*}.bin"
fi

# Set the tool chain path (may need to be adjusted according to your actual path)
TOOLCHAIN_PATH="/opt/riscv/bin"
AS="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-as"
LD="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-ld"
OBJCOPY="${TOOLCHAIN_PATH}/riscv64-unknown-linux-gnu-objcopy"

# Temporary object files and temporary elf files
temp_obj="${input_file%.*}.o"
temp_elf="${input_file%.*}.elf"

# Assembly command
echo "Assembling $input_file..."
$AS -march=rv64gc -o "$temp_obj" "$input_file"
if [ $? -ne 0 ]; then
    echo "Assembly failed!"
    exit 1
fi

# Link command (generate temporary ELF first)
echo "Linking $temp_obj to $temp_elf..."
$LD -o "$temp_elf" "$temp_obj"
if [ $? -ne 0 ]; then
    echo "Linking failed!"
    rm -f "$temp_obj"
    exit 1
fi

# Use objcopy to generate pure binary .bin files
echo "Converting $temp_elf to raw binary $output_bin..."
$OBJCOPY -O binary "$temp_elf" "$output_bin"
if [ $? -ne 0 ]; then
    echo "Objcopy failed!"
    rm -f "$temp_obj" "$temp_elf"
    exit 1
fi

# Clean temporary files
rm -f "$temp_obj" "$temp_elf"

echo "Successfully built $output_bin"
