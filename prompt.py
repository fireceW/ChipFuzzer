# RISC-V 汇编代码生成的 prompt 模板

# RISC-V 寄存器和指令说明（简洁版）
RISCV_INSTRUCTION_GUIDE = """
## RISC-V 64-bit 寄存器（必须使用以下名称）

通用寄存器：
- zero (x0): 恒为0
- ra (x1): 返回地址
- sp (x2): 栈指针  
- gp (x3): 全局指针
- tp (x4): 线程指针
- t0-t6 (x5-x7, x28-x31): 临时寄存器 【注意：只有 t0~t6，没有 t7/t8/t9】
- s0-s11 (x8-x9, x18-x27): 保存寄存器
- a0-a7 (x10-x17): 参数/返回值寄存器

浮点寄存器（如果需要）：
- f0-f31 或 ft0-ft11, fs0-fs11, fa0-fa7

## 常见错误（请避免）
- ❌ t7, t8, t9 等寄存器不存在
- ❌ r0, r1, r2 等 ARM 风格寄存器名
- ❌ eax, ebx 等 x86 风格寄存器名
"""

# 基础汇编模板
asm_template = """
'''assembly
.section .text
.global _start

_start:
    # 在这里编写测试代码
    # 【推荐】使用循环、跳转、分支等控制流指令来增加测试覆盖
    # 【推荐】生成足够长的指令序列（50-200 条指令）以充分触发硬件逻辑
    # 【重要】寄存器只能用: t0-t6, s0-s11, a0-a7, zero, ra, sp, gp, tp
    
    # 你的测试指令...
    
    # === 程序退出（必须保留）===
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
'''
"""

# 带循环的测试示例
asm_template_with_loop = """
.section .text
.global _start

_start:
    # 初始化测试数据
    li t0, 0x12345678
    li t1, 0x87654321
    li t2, 100          # 循环计数
    
loop_start:
    # 执行各种运算来触发不同的硬件路径
    add t3, t0, t1
    sub t4, t0, t1
    xor t5, t0, t1
    and t6, t0, t1
    or s0, t0, t1
    sll s1, t0, t1
    srl s2, t0, t1
    sra s3, t0, t1
    
    # 更新值
    addi t0, t0, 1
    xori t1, t1, 0xFF
    
    # 循环控制
    addi t2, t2, -1
    bnez t2, loop_start
    
    # 更多测试...
    mul a0, t3, t4
    div a1, t5, t6
    rem a2, s0, s1
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
"""

# 边界测试示例
asm_template_boundary = """
.section .text
.global _start

_start:
    # 边界值测试
    li t0, 0x7FFFFFFFFFFFFFFF   # 最大正数
    li t1, 0x8000000000000000   # 最小负数
    li t2, 0xFFFFFFFFFFFFFFFF   # -1
    li t3, 0                     # 零
    li t4, 1                     # 最小正数
    
    # 边界运算
    add t5, t0, t4      # 溢出测试
    sub t6, t1, t4      # 下溢测试
    mul s0, t0, t2      # 大数乘法
    div s1, t1, t2      # 特殊除法
    
    # 移位边界
    slli s2, t4, 63     # 左移到最高位
    srli s3, t1, 63     # 右移取符号位
    srai s4, t1, 63     # 算术右移
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
"""

# CSR 操作测试模板
asm_template_csr = """
.section .text
.global _start

_start:
    # CSR 寄存器测试
    # 读取各种 CSR 寄存器
    csrr t0, 0x300       # mstatus
    csrr t1, 0x305       # mtvec
    csrr t2, 0x341       # mepc
    csrr t3, 0x342       # mcause
    
    # 写入 CSR 寄存器
    li t4, 0x1800
    csrw 0x300, t4       # 设置 mstatus
    
    # 读-修改-写
    csrrs t5, 0x300, t4  # 设置特定位
    csrrc t6, 0x300, t4  # 清除特定位
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
"""

# 内存访问测试模板
asm_template_memory = """
.section .text
.global _start

_start:
    # 内存访问测试
    la t0, test_data     # 加载数据地址
    
    # 各种宽度的加载
    lb t1, 0(t0)         # 字节加载
    lh t2, 0(t0)         # 半字加载
    lw t3, 0(t0)         # 字加载
    ld t4, 0(t0)         # 双字加载
    
    # 无符号加载
    lbu t5, 0(t0)
    lhu t6, 0(t0)
    lwu s0, 0(t0)
    
    # 存储测试
    sb t1, 8(t0)
    sh t2, 16(t0)
    sw t3, 24(t0)
    sd t4, 32(t0)
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp

.section .data
test_data:
    .dword 0x123456789ABCDEF0
    .dword 0xFEDCBA9876543210
    .space 64
"""

# 分支跳转测试模板
asm_template_branch = """
.section .text
.global _start

_start:
    # 分支测试
    li t0, 10
    li t1, 10
    li t2, 5
    li t3, 20
    
    # 相等/不等分支
    beq t0, t1, equal_label
    j skip1
equal_label:
    addi t4, zero, 1
skip1:
    
    bne t0, t2, not_equal_label
    j skip2
not_equal_label:
    addi t4, zero, 2
skip2:
    
    # 比较分支
    blt t2, t0, less_than_label
less_than_label:
    
    bge t3, t0, greater_equal_label
greater_equal_label:
    
    # 无符号比较
    li t5, 0xFFFFFFFFFFFFFFFF
    bltu t0, t5, unsigned_less
unsigned_less:
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
"""

# 乘除法测试模板
asm_template_muldiv = """
.section .text
.global _start

_start:
    # 乘除法测试
    li t0, 12345
    li t1, 67890
    li t2, -12345
    li t3, 0
    
    # 乘法
    mul a0, t0, t1       # 有符号乘法（低64位）
    mulh a1, t0, t1      # 有符号乘法（高64位）
    mulhu a2, t0, t1     # 无符号乘法（高64位）
    mulhsu a3, t2, t1    # 有符号*无符号
    
    # 除法
    li t4, 1000
    li t5, 7
    div a4, t4, t5       # 有符号除法
    divu a5, t4, t5      # 无符号除法
    rem a6, t4, t5       # 有符号余数
    remu a7, t4, t5      # 无符号余数
    
    # 边界情况：除以零（可能触发异常）
    # div s0, t0, t3     # 除以零 - 谨慎使用
    
    # 程序退出
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
"""

# 非法寄存器映射（用于自动修复）
ILLEGAL_REGISTER_MAP = {
    't7': 's0', 't8': 's1', 't9': 's2', 't10': 's3', 't11': 's4', 't12': 's5',
    'r0': 'zero', 'r1': 'ra', 'r2': 'sp', 'r3': 'gp', 'r4': 'tp',
    'r5': 't0', 'r6': 't1', 'r7': 't2', 'r8': 's0', 'r9': 's1',
    'r10': 'a0', 'r11': 'a1', 'r12': 'a2', 'r13': 'a3', 'r14': 'a4', 'r15': 'a5',
    # x86 风格
    'eax': 'a0', 'ebx': 'a1', 'ecx': 'a2', 'edx': 'a3',
    'rax': 'a0', 'rbx': 'a1', 'rcx': 'a2', 'rdx': 'a3',
}

# 合法的 RISC-V 寄存器
LEGAL_REGISTERS = {
    'zero', 'ra', 'sp', 'gp', 'tp',
    't0', 't1', 't2', 't3', 't4', 't5', 't6',
    's0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11',
    'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7',
    'fp',  # s0 的别名
    # x 风格也合法
    'x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7',
    'x8', 'x9', 'x10', 'x11', 'x12', 'x13', 'x14', 'x15',
    'x16', 'x17', 'x18', 'x19', 'x20', 'x21', 'x22', 'x23',
    'x24', 'x25', 'x26', 'x27', 'x28', 'x29', 'x30', 'x31',
    # 浮点寄存器
    'f0', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7',
    'f8', 'f9', 'f10', 'f11', 'f12', 'f13', 'f14', 'f15',
    'f16', 'f17', 'f18', 'f19', 'f20', 'f21', 'f22', 'f23',
    'f24', 'f25', 'f26', 'f27', 'f28', 'f29', 'f30', 'f31',
    'ft0', 'ft1', 'ft2', 'ft3', 'ft4', 'ft5', 'ft6', 'ft7',
    'ft8', 'ft9', 'ft10', 'ft11',
    'fs0', 'fs1', 'fs2', 'fs3', 'fs4', 'fs5', 'fs6', 'fs7',
    'fs8', 'fs9', 'fs10', 'fs11',
    'fa0', 'fa1', 'fa2', 'fa3', 'fa4', 'fa5', 'fa6', 'fa7',
}
