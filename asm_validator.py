"""
RISC-V 汇编代码验证和修复模块
检测和修复常见的汇编错误
"""

import re
from typing import List, Tuple, Dict

# 非法寄存器映射到合法寄存器
REGISTER_FIX_MAP = {
    # t7-t12 不存在，映射到 s 寄存器
    't7': 's0', 't8': 's1', 't9': 's2', 
    't10': 's3', 't11': 's4', 't12': 's5',
    # ARM 风格寄存器
    'r0': 'zero', 'r1': 'ra', 'r2': 'sp', 'r3': 'gp', 'r4': 'tp',
    'r5': 't0', 'r6': 't1', 'r7': 't2', 'r8': 's0', 'r9': 's1',
    'r10': 'a0', 'r11': 'a1', 'r12': 'a2', 'r13': 'a3', 
    'r14': 'a4', 'r15': 'a5', 'r16': 'a6', 'r17': 'a7',
    # x86 风格寄存器
    'eax': 'a0', 'ebx': 'a1', 'ecx': 'a2', 'edx': 'a3',
    'rax': 'a0', 'rbx': 'a1', 'rcx': 'a2', 'rdx': 'a3',
    'esi': 's0', 'edi': 's1', 'ebp': 's2', 'esp': 'sp',
    'rsi': 's0', 'rdi': 's1', 'rbp': 's2', 'rsp': 'sp',
}

# 需要寄存器作为参数的跳转指令（不能直接用标签）
JUMP_REG_INSTRUCTIONS = {'jr', 'jalr'}


class AsmValidator:
    """RISC-V 汇编代码验证器 - 只检查真正的错误"""
    
    def __init__(self):
        self.errors = []
        self.fixes_applied = []
    
    def validate(self, asm_code: str) -> Tuple[bool, List[str]]:
        """
        验证汇编代码，只检查非法寄存器
        
        返回:
            (是否有错误, 错误列表)
        """
        self.errors = []
        lines = asm_code.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            self._check_line(line_num, line)
        
        return len(self.errors) == 0, self.errors
    
    def _check_line(self, line_num: int, line: str):
        """检查单行代码中的错误"""
        # 去除注释
        code_part = line
        if '#' in line:
            code_part = line[:line.index('#')]
        if '//' in line:
            code_part = line[:line.index('//')]
        
        code_part = code_part.strip()
        if not code_part or code_part.startswith('.') or code_part.endswith(':'):
            return
        
        # 1. 检查非法寄存器
        for illegal_reg in REGISTER_FIX_MAP.keys():
            pattern = r'\b' + illegal_reg + r'\b'
            if re.search(pattern, code_part, re.IGNORECASE):
                self.errors.append(
                    f"行 {line_num}: 非法寄存器 '{illegal_reg}' "
                    f"(建议替换为 '{REGISTER_FIX_MAP[illegal_reg]}')"
                )
        
        # 2. 检查 jr/jalr 指令的错误用法（jr label 而不是 jr reg）
        words = code_part.split()
        if words:
            instr = words[0].lower()
            if instr in JUMP_REG_INSTRUCTIONS and len(words) >= 2:
                operand = words[1].rstrip(',')
                # 检查操作数是否是寄存器
                valid_regs = {'zero', 'ra', 'sp', 'gp', 'tp', 
                             't0', 't1', 't2', 't3', 't4', 't5', 't6',
                             's0', 's1', 's2', 's3', 's4', 's5', 's6', 
                             's7', 's8', 's9', 's10', 's11',
                             'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7',
                             'fp'}
                # 也检查 x0-x31 格式
                if not (operand.lower() in valid_regs or 
                        re.match(r'^x\d{1,2}$', operand.lower())):
                    self.errors.append(
                        f"行 {line_num}: '{instr}' 指令需要寄存器作为参数，"
                        f"不能直接使用标签 '{operand}'"
                    )
    
    def fix(self, asm_code: str) -> Tuple[str, List[str]]:
        """
        修复汇编代码中的错误
        
        返回:
            (修复后的代码, 应用的修复列表)
        """
        self.fixes_applied = []
        fixed_code = asm_code
        
        # 1. 修复非法寄存器（区分大小写）
        for illegal_reg, legal_reg in REGISTER_FIX_MAP.items():
            # 小写版本
            pattern = r'\b' + illegal_reg + r'\b'
            if re.search(pattern, fixed_code):
                fixed_code = re.sub(pattern, legal_reg, fixed_code)
                self.fixes_applied.append(f"'{illegal_reg}' → '{legal_reg}'")
            
            # 大写版本
            pattern_upper = r'\b' + illegal_reg.upper() + r'\b'
            if re.search(pattern_upper, fixed_code):
                fixed_code = re.sub(pattern_upper, legal_reg, fixed_code)
                self.fixes_applied.append(f"'{illegal_reg.upper()}' → '{legal_reg}'")
        
        # 2. 修复 jr/jalr 直接使用标签的问题
        # 将 "jr label" 改为 "j label" (因为 j 可以使用标签)
        lines = fixed_code.split('\n')
        new_lines = []
        valid_regs = {'zero', 'ra', 'sp', 'gp', 'tp', 
                     't0', 't1', 't2', 't3', 't4', 't5', 't6',
                     's0', 's1', 's2', 's3', 's4', 's5', 's6', 
                     's7', 's8', 's9', 's10', 's11',
                     'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'fp'}
        
        for line in lines:
            code_part = line
            if '#' in line:
                code_part = line[:line.index('#')]
            words = code_part.strip().split()
            
            if words and words[0].lower() in JUMP_REG_INSTRUCTIONS:
                if len(words) >= 2:
                    operand = words[1].rstrip(',')
                    # 如果操作数不是寄存器，替换指令
                    if not (operand.lower() in valid_regs or 
                            re.match(r'^x\d{1,2}$', operand.lower())):
                        # jr label -> j label
                        if words[0].lower() == 'jr':
                            new_line = line.replace('jr', 'j', 1).replace('JR', 'j', 1)
                            new_lines.append(new_line)
                            self.fixes_applied.append(f"'jr {operand}' → 'j {operand}'")
                            continue
                        # jalr label -> jal label
                        elif words[0].lower() == 'jalr':
                            new_line = line.replace('jalr', 'jal', 1).replace('JALR', 'jal', 1)
                            new_lines.append(new_line)
                            self.fixes_applied.append(f"'jalr {operand}' → 'jal {operand}'")
                            continue
            
            new_lines.append(line)
        
        fixed_code = '\n'.join(new_lines)
        return fixed_code, self.fixes_applied


def validate_asm(asm_code: str) -> Tuple[bool, List[str]]:
    """快速验证汇编代码"""
    validator = AsmValidator()
    return validator.validate(asm_code)


def fix_asm(asm_code: str) -> Tuple[str, List[str]]:
    """快速修复汇编代码"""
    validator = AsmValidator()
    return validator.fix(asm_code)


def generate_error_feedback(compile_error: str) -> str:
    """
    根据编译错误生成详细的反馈信息，帮助 LLM 更好地修复代码
    """
    feedback = []
    
    # 检测非法寄存器错误（最常见的错误）
    illegal_reg_matches = re.findall(r"illegal operands.*?`([^']+)'", compile_error, re.IGNORECASE)
    if illegal_reg_matches:
        feedback.append("【寄存器错误】")
        found_regs = set()
        for match in illegal_reg_matches[:5]:  # 增加到5个
            # 提取可能的非法寄存器
            for reg in REGISTER_FIX_MAP.keys():
                if reg in match.lower() and reg not in found_regs:
                    feedback.append(f"  - '{reg}' 不是合法的 RISC-V 寄存器，请使用 '{REGISTER_FIX_MAP[reg]}'")
                    found_regs.add(reg)
                    break
        if found_regs:
            feedback.append("  提示: RISC-V 临时寄存器只有 t0-t6，没有 t7/t8/t9")
            feedback.append("  提示: 可以使用 s0-s11 作为额外的临时寄存器")
    
    # 检测未定义符号
    if 'undefined' in compile_error.lower():
        undefined_matches = re.findall(r"undefined reference to `([^']+)'", compile_error)
        if undefined_matches:
            feedback.append("【未定义符号】")
            for match in undefined_matches[:5]:
                feedback.append(f"  - '{match}' 未定义，请移除或替换为已定义的符号")
    
    # 检测语法错误
    syntax_errors = []
    if 'syntax error' in compile_error.lower():
        syntax_errors.append("语法错误：请检查指令格式和操作数")
    if 'expected' in compile_error.lower():
        # 提取期望的内容
        expected_matches = re.findall(r"expected\s+([^,]+)", compile_error, re.IGNORECASE)
        if expected_matches:
            syntax_errors.append(f"语法错误：期望 {expected_matches[0]}")
    
    if syntax_errors:
        feedback.append("【语法错误】")
        feedback.extend(syntax_errors)
        feedback.append("  提示: 检查指令格式，确保操作数顺序正确")
        feedback.append("  提示: 立即数指令（如 addi）的立即数范围是 -2048 到 2047")
    
    # 检测标签错误
    if 'undefined symbol' in compile_error.lower() or 'undefined label' in compile_error.lower():
        label_matches = re.findall(r"undefined.*?`([^']+)'", compile_error)
        if label_matches:
            feedback.append("【标签错误】")
            for match in label_matches[:3]:
                feedback.append(f"  - 标签 '{match}' 未定义，请确保标签存在且拼写正确")
    
    # 如果没有识别出具体错误，显示原始错误的关键行
    if not feedback:
        error_lines = compile_error.strip().split('\n')
        # 优先显示包含 "Error" 或 "error" 的行
        important_lines = [line for line in error_lines if 'error' in line.lower() or 'Error' in line]
        if important_lines:
            feedback.append("【编译错误】")
            for line in important_lines[:5]:
                if line.strip():
                    feedback.append(f"  {line.strip()}")
        else:
            # 如果没有重要行，显示前几行
            feedback.append("【编译错误】")
            for line in error_lines[:5]:
                if line.strip():
                    feedback.append(f"  {line.strip()}")
    
    return '\n'.join(feedback)


# 测试
if __name__ == "__main__":
    test_code = """
.section .text
.global _start

_start:
    li t0, 100
    li t7, 200        # 非法寄存器
    li t8, 300        # 非法寄存器
    add t9, t7, t8    # 非法寄存器
    
    # 循环是允许的
    li t1, 10
loop:
    addi t1, t1, -1
    bnez t1, loop
    
    li gp, 1
    li a7, 93
    li a0, 0
    ecall
"""
    
    print("=== 验证结果 ===")
    is_valid, errors = validate_asm(test_code)
    print(f"有效: {is_valid}")
    for err in errors:
        print(f"  {err}")
    
    print("\n=== 修复结果 ===")
    fixed, fixes = fix_asm(test_code)
    if fixes:
        print("应用的修复:")
        for fix in fixes:
            print(f"  - {fix}")
    print("\n修复后的代码:")
    print(fixed)
