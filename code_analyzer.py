"""
Verilog 代码分析器
用于从目标未覆盖代码中提取触发条件，帮助 LLM 生成更精准的测试用例
"""

import re
from typing import List, Dict, Tuple, Optional


class VerilogAnalyzer:
    """分析 Verilog 代码，提取触发条件"""
    
    def __init__(self):
        # 常见的信号模式
        self.signal_patterns = {
            'csr': r'csr|CSR|mstatus|mtvec|mepc|mcause|mie|mip|satp|sstatus',
            'memory': r'mem|load|store|addr|data|cache|tlb|TLB',
            'branch': r'branch|jump|jal|jalr|beq|bne|blt|bge',
            'alu': r'alu|ALU|add|sub|mul|div|and|or|xor|sll|srl|sra',
            'exception': r'exception|trap|interrupt|fault|illegal',
            'float': r'float|fpu|FPU|fadd|fsub|fmul|fdiv',
        }
        
        # 条件运算符
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
        分析未覆盖的 Verilog 代码，提取关键信息
        
        返回:
            {
                'conditions': [...],  # 条件表达式列表
                'signals': [...],     # 涉及的信号
                'values': [...],      # 出现的常量值
                'code_type': '...',   # 代码类型推断
                'suggestions': [...], # 测试建议
            }
        """
        result = {
            'conditions': [],
            'signals': [],
            'values': [],
            'code_type': 'unknown',
            'suggestions': [],
        }
        
        # 提取条件表达式
        result['conditions'] = self._extract_conditions(verilog_code)
        
        # 提取信号名
        result['signals'] = self._extract_signals(verilog_code)
        
        # 提取常量值
        result['values'] = self._extract_values(verilog_code)
        
        # 推断代码类型
        result['code_type'] = self._infer_code_type(verilog_code)
        
        # 生成测试建议
        result['suggestions'] = self._generate_suggestions(result)
        
        return result
    
    def _extract_conditions(self, code: str) -> List[Dict]:
        """提取条件表达式"""
        conditions = []
        
        # 匹配 if 语句中的条件
        if_pattern = r'if\s*\(([^)]+)\)'
        for match in re.finditer(if_pattern, code):
            cond = match.group(1).strip()
            conditions.append({
                'expression': cond,
                'type': 'if',
                'parsed': self._parse_condition(cond)
            })
        
        # 匹配 case 语句
        case_pattern = r'(\d+\'[hHbBdD][\da-fA-F_]+)\s*:'
        for match in re.finditer(case_pattern, code):
            value = match.group(1)
            conditions.append({
                'expression': value,
                'type': 'case',
                'parsed': {'value': value}
            })
        
        # 匹配三元运算符
        ternary_pattern = r'\?\s*([^:]+)\s*:'
        for match in re.finditer(ternary_pattern, code):
            cond = match.group(1).strip()
            if '?' not in cond:  # 避免嵌套
                conditions.append({
                    'expression': cond,
                    'type': 'ternary',
                    'parsed': self._parse_condition(cond)
                })
        
        return conditions[:10]  # 限制数量
    
    def _parse_condition(self, cond: str) -> Dict:
        """解析单个条件表达式"""
        result = {'raw': cond, 'parts': []}
        
        # 检查比较运算符
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
        """提取信号名"""
        signals = set()
        
        # 匹配常见信号名模式
        # io.xxx, reg.xxx, wire_xxx 等
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
        
        # 匹配完整的信号路径
        full_signal_pattern = r'\b([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)\b'
        for match in re.finditer(full_signal_pattern, code):
            signals.add(match.group(1))
        
        return list(signals)[:20]
    
    def _extract_values(self, code: str) -> List[str]:
        """提取常量值"""
        values = set()
        
        # 匹配 Verilog 风格的数字
        patterns = [
            r"\d+'[hH]([\da-fA-F_]+)",  # 十六进制
            r"\d+'[bB]([01_]+)",         # 二进制
            r"\d+'[dD](\d+)",            # 十进制
            r'0x([\da-fA-F]+)',          # C 风格十六进制
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, code):
                value = match.group(0)
                values.add(value)
        
        return list(values)[:15]
    
    def _infer_code_type(self, code: str) -> str:
        """推断代码类型"""
        code_lower = code.lower()
        
        # 按优先级检查
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
        """根据分析结果生成测试建议"""
        suggestions = []
        code_type = analysis['code_type']
        
        # 基于代码类型的建议
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
        
        # 基于提取的值的建议
        for value in analysis['values'][:5]:
            suggestions.append(f'尝试使用值 {value} 作为操作数')
        
        # 基于条件的建议
        for cond in analysis['conditions'][:3]:
            if cond['type'] == 'if':
                suggestions.append(f'需要满足条件: {cond["expression"][:50]}')
        
        return suggestions[:10]


def analyze_target_code(verilog_code: str) -> str:
    """
    分析目标代码并返回格式化的分析结果
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


# 测试策略模板
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
    # 使用 t0 进行测试
    blt t0, t1, seq_loop
''',
    },
}
