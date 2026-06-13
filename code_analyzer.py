"""
Verilog code analyzer
Used to extract trigger conditions from target uncovered code to help LLM generate more accurate test cases
"""

import re
from typing import List, Dict, Tuple, Optional


class VerilogAnalyzer:
    """Analyze Verilog code and extract trigger conditions"""
    
    def __init__(self):
        # Common signaling patterns
        self.signal_patterns = {
            'csr': r'csr|CSR|mstatus|mtvec|mepc|mcause|mie|mip|satp|sstatus',
            'memory': r'mem|load|store|addr|data|cache|tlb|TLB',
            'branch': r'branch|jump|jal|jalr|beq|bne|blt|bge',
            'alu': r'alu|ALU|add|sub|mul|div|and|or|xor|sll|srl|sra',
            'exception': r'exception|trap|interrupt|fault|illegal',
            'float': r'float|fpu|FPU|fadd|fsub|fmul|fdiv',
        }
        
        # conditional operator
        self.condition_ops = {
            '===': 'equals',
            '==': 'equals',
            '!=': 'not_equals',
            '!==': 'not_equals',
            '<': 'less_than',
            '>': 'greater_than',
            '<=': 'less_equal',
            '>=': 'greater_equal',
            '&': 'and',
            '|': 'or',
            '^': 'xor',
        }
    
    def analyze_uncovered_code(self, verilog_code: str) -> Dict:
        """
        Analyze uncovered Verilog code and extract key information
        
        return:
            {
                'conditions': [...], # List of conditional expressions
                'signals': [...], # Involved signals
                'values': [...], # Constant values ​​that appear
                'code_type': '...', # Code type inference
                'suggestions': [...], # Test suggestions
            }
        """
        result = {
            'conditions': [],
            'signals': [],
            'values': [],
            'code_type': 'unknown',
            'suggestions': [],
        }
        
        # Extract conditional expression
        result['conditions'] = self._extract_conditions(verilog_code)
        
        # Extract signal name
        result['signals'] = self._extract_signals(verilog_code)
        
        # Extract constant value
        result['values'] = self._extract_values(verilog_code)
        
        # Infer code type
        result['code_type'] = self._infer_code_type(verilog_code)
        
        # Generate test recommendations
        result['suggestions'] = self._generate_suggestions(result)
        
        return result
    
    def _extract_conditions(self, code: str) -> List[Dict]:
        """Extract conditional expression"""
        conditions = []
        
        # Match the condition in the if statement
        if_pattern = r'if\s*\(([^)]+)\)'
        for match in re.finditer(if_pattern, code):
            cond = match.group(1).strip()
            conditions.append({
                'expression': cond,
                'type': 'if',
                'parsed': self._parse_condition(cond)
            })
        
        # Match case statement
        case_pattern = r'(\d+\'[hHbBdD][\da-fA-F_]+)\s*:'
        for match in re.finditer(case_pattern, code):
            value = match.group(1)
            conditions.append({
                'expression': value,
                'type': 'case',
                'parsed': {'value': value}
            })
        
        # match ternary operator
        ternary_pattern = r'\?\s*([^:]+)\s*:'
        for match in re.finditer(ternary_pattern, code):
            cond = match.group(1).strip()
            if '?' not in cond:  # avoid nesting
                conditions.append({
                    'expression': cond,
                    'type': 'ternary',
                    'parsed': self._parse_condition(cond)
                })
        
        return conditions[:10]  # limited quantity
    
    def _parse_condition(self, cond: str) -> Dict:
        """Parse a single conditional expression"""
        result = {'raw': cond, 'parts': []}
        
        # Check comparison operators
        for op, name in self.condition_ops.items():
            if op in cond:
                parts = cond.split(op)
                if len(parts) == 2:
                    result['parts'].append({
                        'left': parts[0].strip(),
                        'op': name,
                        'right': parts[1].strip()
                    })
        
        return result
    
    def _extract_signals(self, code: str) -> List[str]:
        """Extract signal name"""
        signals = set()
        
        # Match common signal name patterns
        # io.xxx, reg.xxx, wire_xxx, etc.
        patterns = [
            r'io\.(\w+)',
            r'reg_(\w+)',
            r'wire_(\w+)',
            r'(\w+)_reg',
            r'(\w+)_wire',
            r'(\w+)_i\b',
            r'(\w+)_o\b',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, code):
                signals.add(match.group(1))
        
        # Match the complete signal path
        full_signal_pattern = r'\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)\b'
        for match in re.finditer(full_signal_pattern, code):
            signals.add(match.group(1))
        
        return list(signals)[:20]
    
    def _extract_values(self, code: str) -> List[str]:
        """Extract constant value"""
        values = set()
        
        # Match Verilog-style numbers
        patterns = [
            r"\d+'[hH]([\da-fA-F_]+)",  # hexadecimal
            r"\d+'[bB]([01_]+)",         # binary
            r"\d+'[dD](\d+)",            # decimal
            r'0x([\da-fA-F]+)',          # C style hex
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, code):
                value = match.group(0)
                values.add(value)
        
        return list(values)[:15]
    
    def _infer_code_type(self, code: str) -> str:
        """Infer code type"""
        code_lower = code.lower()
        
        # Check by priority
        type_checks = [
            ('csr', self.signal_patterns['csr']),
            ('memory', self.signal_patterns['memory']),
            ('branch', self.signal_patterns['branch']),
            ('float', self.signal_patterns['float']),
            ('exception', self.signal_patterns['exception']),
            ('alu', self.signal_patterns['alu']),
        ]
        
        for code_type, pattern in type_checks:
            if re.search(pattern, code_lower):
                return code_type
        
        return 'general'
    
    def _generate_suggestions(self, analysis: Dict) -> List[str]:
        """Generate test recommendations based on analysis results"""
        suggestions = []
        code_type = analysis['code_type']
        
        # Recommendations based on code type
        type_suggestions = {
            'csr': [
                '使用 csrrw/csrrs/csrrc 指令读写 CSR 寄存器',
                '尝试不同的特权级别操作',
                '测试 CSR 寄存器的边界值',
            ],
            'memory': [
                '使用 lw/sw/ld/sd 等内存访问指令',
                '测试不同的地址对齐方式',
                '尝试访问不同的内存区域',
            ],
            'branch': [
                '使用 beq/bne/blt/bge 等分支指令',
                '测试分支条件的边界值',
                '尝试正向和反向跳转',
            ],
            'float': [
                '使用浮点运算指令 fadd/fsub/fmul/fdiv',
                '测试特殊浮点值（NaN, Inf, 0）',
                '测试浮点精度边界',
            ],
            'exception': [
                '触发非法指令异常',
                '触发地址对齐异常',
                '测试异常处理流程',
            ],
            'alu': [
                '测试各种算术运算',
                '使用边界值（MAX, MIN, 0, -1）',
                '测试运算结果的各种情况',
            ],
        }
        
        suggestions.extend(type_suggestions.get(code_type, []))
        
        # Recommendations based on extracted values
        for value in analysis['values'][:5]:
            suggestions.append(f'尝试使用值 {value} 作为操作数')
        
        # Condition-based recommendations
        for cond in analysis['conditions'][:3]:
            if cond['type'] == 'if':
                suggestions.append(f'需要满足条件: {cond["expression"][:50]}')
        
        return suggestions[:10]


def analyze_target_code(verilog_code: str) -> str:
    """
    Analyze target code and return formatted analysis results
    """
    analyzer = VerilogAnalyzer()
    result = analyzer.analyze_uncovered_code(verilog_code)
    
    output = []
    output.append(f"代码类型: {result['code_type']}")
    
    if result['conditions']:
        output.append("\n关键条件:")
        for cond in result['conditions'][:5]:
            output.append(f"  - [{cond['type']}] {cond['expression'][:60]}")
    
    if result['values']:
        output.append(f"\n关键常量值: {', '.join(result['values'][:8])}")
    
    if result['suggestions']:
        output.append("\n测试建议:")
        for i, sug in enumerate(result['suggestions'][:5], 1):
            output.append(f"  {i}. {sug}")
    
    return '\n'.join(output)


# Test strategy template
TEST_STRATEGIES = {
    'boundary': {
        'name': '边界值测试',
        'description': '使用边界值来触发边界条件',
        'values': [
            ('0', '零'),
            ('1', '最小正数'),
            ('-1 (0xFFFFFFFFFFFFFFFF)', '全1'),
            ('0x7FFFFFFFFFFFFFFF', '最大正数'),
            ('0x8000000000000000', '最小负数'),
        ],
    },
    'special': {
        'name': '特殊值测试',
        'description': '使用特殊值触发特殊路径',
        'values': [
            ('0xDEADBEEF', '调试魔数'),
            ('0xCAFEBABE', '调试魔数'),
            ('0x55555555', '交替位模式'),
            ('0xAAAAAAAA', '交替位模式'),
        ],
    },
    'sequence': {
        'name': '序列测试',
        'description': '使用递增/递减序列',
        'code': '''
    li t0, 0
    li t1, 100
seq_loop:
    addi t0, t0, 1
    # Test with t0
    blt t0, t1, seq_loop
''',
    },
}
