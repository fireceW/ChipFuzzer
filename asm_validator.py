"""
RISC-V assembly code verification and repair module
Detect and fix common assembly errors
"""

import re
from typing import List, Tuple, Dict

# Illegal registers map to legal registers
REGISTER_FIX_MAP = {
    # t7-t12 does not exist and is mapped to the s register
    't7': 's0', 't8': 's1', 't9': 's2', 
    't10': 's3', 't11': 's4', 't12': 's5',
    # ARM style registers
    'r0': 'zero', 'r1': 'ra', 'r2': 'sp', 'r3': 'gp', 'r4': 'tp',
    'r5': 't0', 'r6': 't1', 'r7': 't2', 'r8': 's0', 'r9': 's1',
    'r10': 'a0', 'r11': 'a1', 'r12': 'a2', 'r13': 'a3', 
    'r14': 'a4', 'r15': 'a5', 'r16': 'a6', 'r17': 'a7',
    # x86 style registers
    'eax': 'a0', 'ebx': 'a1', 'ecx': 'a2', 'edx': 'a3',
    'rax': 'a0', 'rbx': 'a1', 'rcx': 'a2', 'rdx': 'a3',
    'esi': 's0', 'edi': 's1', 'ebp': 's2', 'esp': 'sp',
    'rsi': 's0', 'rdi': 's1', 'rbp': 's2', 'rsp': 'sp',
}

# Jump instructions that require registers as parameters (labels cannot be used directly)
JUMP_REG_INSTRUCTIONS = {'jr', 'jalr'}


class AsmValidator:
    """RISC-V assembly code verifier - only checks for real errors"""
    
    def __init__(self):
        self.errors = []
        self.fixes_applied = []
    
    def validate(self, asm_code: str) -> Tuple[bool, List[str]]:
        """
        Verify assembly code, only check illegal registers
        
        return:
            (Are there any errors, error list)
        """
        self.errors = []
        lines = asm_code.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            self._check_line(line_num, line)
        
        return len(self.errors) == 0, self.errors
    
    def _check_line(self, line_num: int, line: str):
        """Check for errors in a single line of code"""
        # Remove comments
        code_part = line
        if '#' in line:
            code_part = line[:line.index('#')]
        if '//' in line:
            code_part = line[:line.index('//')]
        
        code_part = code_part.strip()
        if not code_part or code_part.startswith('.') or code_part.endswith(':'):
            return
        
        # 1. Check illegal registers
        for illegal_reg in REGISTER_FIX_MAP.keys():
            pattern = r'\b' + illegal_reg + r'\b'
            if re.search(pattern, code_part, re.IGNORECASE):
                self.errors.append(
                    f"行 {line_num}: 非法寄存器 '{illegal_reg}' "
                    f"(建议替换为 '{REGISTER_FIX_MAP[illegal_reg]}')"
                )
        
        # 2. Check for incorrect usage of the jr/jalr directive (jr label instead of jr reg)
        words = code_part.split()
        if words:
            instr = words[0].lower()
            if instr in JUMP_REG_INSTRUCTIONS and len(words) >= 2:
                operand = words[1].rstrip(',')
                # Check if the operand is a register
                valid_regs = {'zero', 'ra', 'sp', 'gp', 'tp', 
                             't0', 't1', 't2', 't3', 't4', 't5', 't6',
                             's0', 's1', 's2', 's3', 's4', 's5', 's6', 
                             's7', 's8', 's9', 's10', 's11',
                             'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7',
                             'fp'}
                # Also checks x0-x31 format
                if not (operand.lower() in valid_regs or 
                        re.match(r'^x\d{1,2}$', operand.lower())):
                    self.errors.append(
                        f"行 {line_num}: '{instr}' 指令需要寄存器作为参数，"
                        f"不能直接使用标签 '{operand}'"
                    )
    
    def fix(self, asm_code: str) -> Tuple[str, List[str]]:
        """
        Fix errors in assembly code
        
        return:
            (fixed code, list of fixes applied)
        """
        self.fixes_applied = []
        fixed_code = asm_code
        
        # 1. Fix illegal registers (case sensitive)
        for illegal_reg, legal_reg in REGISTER_FIX_MAP.items():
            # lower case version
            pattern = r'\b' + illegal_reg + r'\b'
            if re.search(pattern, fixed_code):
                fixed_code = re.sub(pattern, legal_reg, fixed_code)
                self.fixes_applied.append(f"'{illegal_reg}' → '{legal_reg}'")
            
            # upper case version
            pattern_upper = r'\b' + illegal_reg.upper() + r'\b'
            if re.search(pattern_upper, fixed_code):
                fixed_code = re.sub(pattern_upper, legal_reg, fixed_code)
                self.fixes_applied.append(f"'{illegal_reg.upper()}' → '{legal_reg}'")
        
        # 2. Fix the problem of jr/jalr using tags directly
        # Change "jr label" to "j label" (because j can use labels)
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
                    # If the operand is not a register, replace the instruction
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
    """Quickly verify assembly code"""
    validator = AsmValidator()
    return validator.validate(asm_code)


def fix_asm(asm_code: str) -> Tuple[str, List[str]]:
    """Quickly fix assembly code"""
    validator = AsmValidator()
    return validator.fix(asm_code)


def generate_error_feedback(compile_error: str) -> str:
    """
    Generate detailed feedback information based on compilation errors to help LLM better fix the code
    """
    feedback = []
    
    # Detect illegal register errors (the most common error)
    illegal_reg_matches = re.findall(r"illegal operands.*?`([^']+)'", compile_error, re.IGNORECASE)
    if illegal_reg_matches:
        feedback.append("【寄存器错误】")
        found_regs = set()
        for match in illegal_reg_matches[:5]:  # increase to 5
            # Extract possible illegal registers
            for reg in REGISTER_FIX_MAP.keys():
                if reg in match.lower() and reg not in found_regs:
                    feedback.append(f"  - '{reg}' 不是合法的 RISC-V 寄存器，请使用 '{REGISTER_FIX_MAP[reg]}'")
                    found_regs.add(reg)
                    break
        if found_regs:
            feedback.append("  提示: RISC-V 临时寄存器只有 t0-t6，没有 t7/t8/t9")
            feedback.append("  提示: 可以使用 s0-s11 作为额外的临时寄存器")
    
    # Detect undefined symbols
    if 'undefined' in compile_error.lower():
        undefined_matches = re.findall(r"undefined reference to `([^']+)'", compile_error)
        if undefined_matches:
            feedback.append("【未定义符号】")
            for match in undefined_matches[:5]:
                feedback.append(f"  - '{match}' 未定义，请移除或替换为已定义的符号")
    
    # Detect syntax errors
    syntax_errors = []
    if 'syntax error' in compile_error.lower():
        syntax_errors.append("语法错误：请检查指令格式和操作数")
    if 'expected' in compile_error.lower():
        # Extract desired content
        expected_matches = re.findall(r"expected\s+([^,]+)", compile_error, re.IGNORECASE)
        if expected_matches:
            syntax_errors.append(f"语法错误：期望 {expected_matches[0]}")
    
    if syntax_errors:
        feedback.append("【语法错误】")
        feedback.extend(syntax_errors)
        feedback.append("  提示: 检查指令格式，确保操作数顺序正确")
        feedback.append("  提示: 立即数指令（如 addi）的立即数范围是 -2048 到 2047")
    
    # Detect label errors
    if 'undefined symbol' in compile_error.lower() or 'undefined label' in compile_error.lower():
        label_matches = re.findall(r"undefined.*?`([^']+)'", compile_error)
        if label_matches:
            feedback.append("【标签错误】")
            for match in label_matches[:3]:
                feedback.append(f"  - 标签 '{match}' 未定义，请确保标签存在且拼写正确")
    
    # If no specific error is identified, display the key line of the original error
    if not feedback:
        error_lines = compile_error.strip().split('\n')
        # Show lines containing "Error" or "error" first
        important_lines = [line for line in error_lines if 'error' in line.lower() or 'Error' in line]
        if important_lines:
            feedback.append("【编译错误】")
            for line in important_lines[:5]:
                if line.strip():
                    feedback.append(f"  {line.strip()}")
        else:
            # If there are no important rows, show the first few rows
            feedback.append("【编译错误】")
            for line in error_lines[:5]:
                if line.strip():
                    feedback.append(f"  {line.strip()}")
    
    return '\n'.join(feedback)


# test
if __name__ == "__main__":
    test_code = """
.section .text
.global _start

_start:
    li t0, 100
    li t7, 200        # Illegal register
    li t8, 300        # Illegal register
    add t9, t7, t8    # Illegal register
    
    # Loops are allowed
    li t1, 10
loop:
    addi t1, t1, -1
    bnez t1, loop
    
    li gp, 1
    li a7, 93
    li a0, 0
    ecall
"""
    
    print("=== Verification result ===")
    is_valid, errors = validate_asm(test_code)
    print(f"valid: {is_valid}")
    for err in errors:
        print(f"  {err}")
    
    print("\n=== Repair result ===")
    fixed, fixes = fix_asm(test_code)
    if fixes:
        print("Applied fixes:")
        for fix in fixes:
            print(f"  - {fix}")
    print("\nRepaired code:")
    print(fixed)
