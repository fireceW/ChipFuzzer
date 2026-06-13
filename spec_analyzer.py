"""
SPEC file analyzer
Used to parse the spec file of the Xiangshan processor and extract key information to guide test generation

Function:
1. Parse the interface definition of the spec file
2. Extract signal and port information
3. Identify function modules and state machines
4. Generate targeted testing recommendations
"""

import os
import re
from typing import Dict, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SignalInfo:
    """signal information"""
    name: str
    width: str  # Such as "8:0", "4:0"
    direction: str  # "input", "output", "inout"
    description: str = ""


@dataclass
class ModuleSpec:
    """Module specification information"""
    name: str
    signals: List[SignalInfo]
    submodules: List[str]
    description: str = ""
    spec_file: str = ""


class SpecAnalyzer:
    """Analyze the spec file and extract module specification information"""
    
    def __init__(self, spec_dir: str = "/root/XiangShan/build/rtl"):
        self.spec_dir = Path(spec_dir)
        self.spec_cache: Dict[str, ModuleSpec] = {}
        self._load_specs()
    
    def _load_specs(self):
        """Load all spec files"""
        if not self.spec_dir.exists():
            return
        
        # Find all spec related files
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
        """Parse a single spec file"""
        try:
            with open(spec_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Extract module name
            module_match = re.search(r'module\s+(\w+)', content)
            if not module_match:
                return None
            
            module_name = module_match.group(1)
            
            # Extract signal definition
            signals = self._extract_signals(content)
            
            # Extract submodule instance
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
        """Extract signal definition"""
        signals = []
        
        # Matching port definition: input/output/inout [width] signal_name
        # For example: input [4:0] io_q_j,
        port_pattern = r'(input|output|inout)\s+(?:\[([^\]]+)\])?\s*(\w+)'
        
        for match in re.finditer(port_pattern, content):
            direction = match.group(1)
            width = match.group(2) or ""
            name = match.group(3)
            
            # Skip keywords and common internal signals
            if name in ['module', 'endmodule', 'wire', 'reg', 'assign']:
                continue
            
            signals.append(SignalInfo(
                name=name,
                width=width,
                direction=direction
            ))
        
        return signals
    
    def _extract_submodules(self, content: str) -> List[str]:
        """Extract submodule instance"""
        submodules = []
        
        # Match module instantiation: ModuleName instance_name (...)
        instance_pattern = r'(\w+)\s+\w+\s*\('
        
        for match in re.finditer(instance_pattern, content):
            module_name = match.group(1)
            # Skip common keywords
            if module_name not in ['module', 'endmodule', 'if', 'else', 'case', 'always']:
                submodules.append(module_name)
        
        return list(set(submodules))[:10]  # Remove duplicates and limit quantity
    
    def get_module_spec(self, module_name: str) -> Optional[ModuleSpec]:
        """Get module specification information"""
        # exact match
        if module_name in self.spec_cache:
            return self.spec_cache[module_name]
        
        # Fuzzy matching (handling cases with suffixes)
        for cached_name, spec in self.spec_cache.items():
            if module_name in cached_name or cached_name in module_name:
                return spec
        
        return None
    
    def get_signal_info(self, module_name: str, signal_name: str) -> Optional[SignalInfo]:
        """Get information about a specific signal"""
        spec = self.get_module_spec(module_name)
        if not spec:
            return None
        
        for signal in spec.signals:
            if signal.name == signal_name or signal_name in signal.name:
                return signal
        
        return None
    
    def generate_test_hints(self, module_name: str, uncovered_code: str) -> str:
        """
        Generate test prompts based on spec information
        
        Returns a formatted string containing:
        1. Module interface information
        2. Description of key signals
        3. Testing suggestions
        """
        spec = self.get_module_spec(module_name)
        if not spec:
            return ""
        
        hints = []
        hints.append(f"# 📋 Module specification information ({module_name})")
        hints.append(f"")
        
        # input signal
        input_signals = [s for s in spec.signals if s.direction == 'input']
        if input_signals:
            hints.append(f"**输入信号 ({len(input_signals)} 个):**")
            for sig in input_signals[:10]:  # Limit display quantity
                width_info = f"[{sig.width}]" if sig.width else ""
                hints.append(f"  - `{sig.name}` {width_info} ({sig.direction})")
        
        # Output signal
        output_signals = [s for s in spec.signals if s.direction == 'output']
        if output_signals:
            hints.append(f"\n**输出信号 ({len(output_signals)} 个):**")
            for sig in output_signals[:10]:
                width_info = f"[{sig.width}]" if sig.width else ""
                hints.append(f"  - `{sig.name}` {width_info} ({sig.direction})")
        
        # Submodule information
        if spec.submodules:
            hints.append(f"\n**子模块:** {', '.join(spec.submodules[:5])}")
        
        # Signals extracted from uncovered code
        uncovered_signals = self._extract_signals_from_code(uncovered_code)
        if uncovered_signals:
            hints.append(f"\n**未覆盖代码中的关键信号:**")
            for sig_name in uncovered_signals[:5]:
                sig_info = self.get_signal_info(module_name, sig_name)
                if sig_info:
                    hints.append(f"  - `{sig_name}`: {sig_info.direction}, 宽度 {sig_info.width}")
                else:
                    hints.append(f"  - `{sig_name}`")
        
        # Testing recommendations
        hints.append(f"\n**测试建议:**")
        if input_signals:
            hints.append(f"  1. 通过 RISC-V 指令设置输入信号的值")
            hints.append(f"  2. 测试不同输入组合以触发所有分支")
        
        # Give specific recommendations based on signal width
        for sig in input_signals[:3]:
            if sig.width:
                try:
                    # Parse width, such as "4:0" -> 5 bits, "8:0" -> 9 bits
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
        """Extract signal names from code"""
        signals = set()
        
        # Matches io.xxx format
        io_pattern = r'io\.(\w+)'
        for match in re.finditer(io_pattern, code):
            signals.add(match.group(1))
        
        # Match common signal name patterns
        signal_pattern = r'\b([a-z_][a-z0-9_]*)\b'
        for match in re.finditer(signal_pattern, code):
            name = match.group(1)
            # filter out keywords
            if name not in ['if', 'else', 'begin', 'end', 'wire', 'reg', 'assign']:
                if len(name) > 2 and '_' in name:  # possibly a signal name
                    signals.add(name)
        
        return list(signals)[:10]


# global instance
_spec_analyzer_instance = None


def get_spec_analyzer() -> SpecAnalyzer:
    """Get the global spec analyzer instance"""
    global _spec_analyzer_instance
    if _spec_analyzer_instance is None:
        _spec_analyzer_instance = SpecAnalyzer()
    return _spec_analyzer_instance


def get_module_spec_hints(module_name: str, uncovered_code: str) -> str:
    """
    Get the spec prompt information of the module
    
    parameter:
        module_name: module name
        uncovered_code: uncovered code
    
    return:
        Formatted prompt string
    """
    analyzer = get_spec_analyzer()
    return analyzer.generate_test_hints(module_name, uncovered_code)
