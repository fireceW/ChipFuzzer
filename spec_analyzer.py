"""
SPEC 文件分析器
用于解析香山处理器的 spec 文件，提取关键信息用于指导测试生成

功能：
1. 解析 spec 文件的接口定义
2. 提取信号和端口信息
3. 识别功能模块和状态机
4. 生成针对性的测试建议
"""

import os
import re
from typing import Dict, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SignalInfo:
    """信号信息"""
    name: str
    width: str  # 如 "8:0", "4:0"
    direction: str  # "input", "output", "inout"
    description: str = ""


@dataclass
class ModuleSpec:
    """模块规格信息"""
    name: str
    signals: List[SignalInfo]
    submodules: List[str]
    description: str = ""
    spec_file: str = ""


class SpecAnalyzer:
    """分析 spec 文件，提取模块规格信息"""
    
    def __init__(self, spec_dir: str = "/root/XiangShan/build/rtl"):
        self.spec_dir = Path(spec_dir)
        self.spec_cache: Dict[str, ModuleSpec] = {}
        self._load_specs()
    
    def _load_specs(self):
        """加载所有 spec 文件"""
        if not self.spec_dir.exists():
            return
        
        # 查找所有 spec 相关文件
        spec_files = list(self.spec_dir.glob("*spec*.sv"))
        spec_files.extend(self.spec_dir.glob("*Spec*.sv"))
        
        for spec_file in spec_files:
            try:
                module_spec = self._parse_spec_file(spec_file)
                if module_spec:
                    self.spec_cache[module_spec.name] = module_spec
            except Exception as e:
                print(f"⚠️ 解析 spec 文件失败 {spec_file}: {e}")
    
    def _parse_spec_file(self, spec_file: Path) -> Optional[ModuleSpec]:
        """解析单个 spec 文件"""
        try:
            with open(spec_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 提取模块名
            module_match = re.search(r'module\s+(\w+)', content)
            if not module_match:
                return None
            
            module_name = module_match.group(1)
            
            # 提取信号定义
            signals = self._extract_signals(content)
            
            # 提取子模块实例
            submodules = self._extract_submodules(content)
            
            return ModuleSpec(
                name=module_name,
                signals=signals,
                submodules=submodules,
                spec_file=str(spec_file)
            )
        except Exception as e:
            print(f"⚠️ 解析失败 {spec_file}: {e}")
            return None
    
    def _extract_signals(self, content: str) -> List[SignalInfo]:
        """提取信号定义"""
        signals = []
        
        # 匹配端口定义：input/output/inout [width] signal_name
        # 例如：input  [4:0] io_q_j,
        port_pattern = r'(input|output|inout)\s+(?:\[([^\]]+)\])?\s*(\w+)'
        
        for match in re.finditer(port_pattern, content):
            direction = match.group(1)
            width = match.group(2) or ""
            name = match.group(3)
            
            # 跳过关键字和常见内部信号
            if name in ['module', 'endmodule', 'wire', 'reg', 'assign']:
                continue
            
            signals.append(SignalInfo(
                name=name,
                width=width,
                direction=direction
            ))
        
        return signals
    
    def _extract_submodules(self, content: str) -> List[str]:
        """提取子模块实例"""
        submodules = []
        
        # 匹配模块实例化：ModuleName instance_name (...)
        instance_pattern = r'(\w+)\s+\w+\s*\('
        
        for match in re.finditer(instance_pattern, content):
            module_name = match.group(1)
            # 跳过常见的关键字
            if module_name not in ['module', 'endmodule', 'if', 'else', 'case', 'always']:
                submodules.append(module_name)
        
        return list(set(submodules))[:10]  # 去重并限制数量
    
    def get_module_spec(self, module_name: str) -> Optional[ModuleSpec]:
        """获取模块的规格信息"""
        # 精确匹配
        if module_name in self.spec_cache:
            return self.spec_cache[module_name]
        
        # 模糊匹配（处理带后缀的情况）
        for cached_name, spec in self.spec_cache.items():
            if module_name in cached_name or cached_name in module_name:
                return spec
        
        return None
    
    def get_signal_info(self, module_name: str, signal_name: str) -> Optional[SignalInfo]:
        """获取特定信号的信息"""
        spec = self.get_module_spec(module_name)
        if not spec:
            return None
        
        for signal in spec.signals:
            if signal.name == signal_name or signal_name in signal.name:
                return signal
        
        return None
    
    def generate_test_hints(self, module_name: str, uncovered_code: str) -> str:
        """
        根据 spec 信息生成测试提示
        
        返回格式化的字符串，包含：
        1. 模块接口信息
        2. 关键信号说明
        3. 测试建议
        """
        spec = self.get_module_spec(module_name)
        if not spec:
            return ""
        
        hints = []
        hints.append(f"## 📋 模块规格信息 ({module_name})")
        hints.append(f"")
        
        # 输入信号
        input_signals = [s for s in spec.signals if s.direction == 'input']
        if input_signals:
            hints.append(f"**输入信号 ({len(input_signals)} 个):**")
            for sig in input_signals[:10]:  # 限制显示数量
                width_info = f"[{sig.width}]" if sig.width else ""
                hints.append(f"  - `{sig.name}` {width_info} ({sig.direction})")
        
        # 输出信号
        output_signals = [s for s in spec.signals if s.direction == 'output']
        if output_signals:
            hints.append(f"\n**输出信号 ({len(output_signals)} 个):**")
            for sig in output_signals[:10]:
                width_info = f"[{sig.width}]" if sig.width else ""
                hints.append(f"  - `{sig.name}` {width_info} ({sig.direction})")
        
        # 子模块信息
        if spec.submodules:
            hints.append(f"\n**子模块:** {', '.join(spec.submodules[:5])}")
        
        # 从未覆盖代码中提取的信号
        uncovered_signals = self._extract_signals_from_code(uncovered_code)
        if uncovered_signals:
            hints.append(f"\n**未覆盖代码中的关键信号:**")
            for sig_name in uncovered_signals[:5]:
                sig_info = self.get_signal_info(module_name, sig_name)
                if sig_info:
                    hints.append(f"  - `{sig_name}`: {sig_info.direction}, 宽度 {sig_info.width}")
                else:
                    hints.append(f"  - `{sig_name}`")
        
        # 测试建议
        hints.append(f"\n**测试建议:**")
        if input_signals:
            hints.append(f"  1. 通过 RISC-V 指令设置输入信号的值")
            hints.append(f"  2. 测试不同输入组合以触发所有分支")
        
        # 根据信号宽度给出具体建议
        for sig in input_signals[:3]:
            if sig.width:
                try:
                    # 解析宽度，如 "4:0" -> 5位, "8:0" -> 9位
                    if ':' in sig.width:
                        parts = sig.width.split(':')
                        if len(parts) == 2:
                            high = int(parts[0])
                            low = int(parts[1])
                            width = high - low + 1
                            max_val = (1 << width) - 1
                            hints.append(f"  3. `{sig.name}` 是 {width} 位信号，测试值范围: 0 到 {max_val}")
                except:
                    pass
        
        return '\n'.join(hints)
    
    def _extract_signals_from_code(self, code: str) -> List[str]:
        """从代码中提取信号名"""
        signals = set()
        
        # 匹配 io.xxx 格式
        io_pattern = r'io\.(\w+)'
        for match in re.finditer(io_pattern, code):
            signals.add(match.group(1))
        
        # 匹配常见的信号名模式
        signal_pattern = r'\b([a-z_][a-z0-9_]*)\b'
        for match in re.finditer(signal_pattern, code):
            name = match.group(1)
            # 过滤掉关键字
            if name not in ['if', 'else', 'begin', 'end', 'wire', 'reg', 'assign']:
                if len(name) > 2 and '_' in name:  # 可能是信号名
                    signals.add(name)
        
        return list(signals)[:10]


# 全局实例
_spec_analyzer_instance = None


def get_spec_analyzer() -> SpecAnalyzer:
    """获取全局 spec 分析器实例"""
    global _spec_analyzer_instance
    if _spec_analyzer_instance is None:
        _spec_analyzer_instance = SpecAnalyzer()
    return _spec_analyzer_instance


def get_module_spec_hints(module_name: str, uncovered_code: str) -> str:
    """
    获取模块的 spec 提示信息
    
    参数:
        module_name: 模块名
        uncovered_code: 未覆盖的代码
    
    返回:
        格式化的提示字符串
    """
    analyzer = get_spec_analyzer()
    return analyzer.generate_test_hints(module_name, uncovered_code)
