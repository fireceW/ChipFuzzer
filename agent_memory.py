"""
Agent Memory 管理系统
用于维护 LLM 生成测试用例时的上下文和历史经验，提高生成准确性

功能：
1. 对话历史管理：记录每次 LLM 交互的完整上下文
2. 成功/失败模式记忆：学习哪些策略有效，哪些无效
3. 代码模式学习：识别有效的代码模式和指令序列
4. 错误模式库：记录常见错误及解决方案
5. 覆盖率提升策略记忆：记录哪些方法成功提升了覆盖率
"""

import os
import json
import time
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class MemoryEntry:
    """单个记忆条目"""
    timestamp: float
    module_name: str
    uncovered_code_hash: str  # 未覆盖代码的哈希，用于匹配相似代码
    prompt_type: str  # "generate", "fix", "analysis"
    success: bool
    coverage_improved: bool
    compile_success: bool
    asm_code: str
    error_message: Optional[str] = None
    coverage_lines: List[str] = None  # 本次覆盖的代码行
    strategy: str = ""  # 使用的策略描述
    feedback: str = ""  # LLM 反馈或分析结果


@dataclass
class PatternMemory:
    """代码模式记忆"""
    pattern_hash: str
    pattern_type: str  # "instruction_sequence", "register_usage", "value_pattern"
    success_count: int
    failure_count: int
    examples: List[str]  # 成功的代码示例
    last_used: float


class AgentMemory:
    """
    Agent 记忆管理器
    
    维护以下类型的记忆：
    1. 对话历史：每次 LLM 交互的完整记录
    2. 成功模式：有效的代码模式和策略
    3. 失败模式：无效的策略和常见错误
    4. 代码相似性：基于代码哈希的相似代码匹配
    """
    
    def __init__(self, module_name: str, memory_dir: str = "/root/ChipFuzzer_cursor/agent_memory"):
        self.module_name = module_name
        self.memory_dir = memory_dir
        os.makedirs(memory_dir, exist_ok=True)
        
        # 内存中的记忆
        self.history: List[MemoryEntry] = []
        self.patterns: Dict[str, PatternMemory] = {}
        self.error_patterns: Dict[str, int] = {}  # 错误类型 -> 出现次数
        
        # 加载持久化的记忆
        self._load_memory()
    
    def _get_memory_file(self) -> str:
        """获取该模块的记忆文件路径"""
        return os.path.join(self.memory_dir, f"{self.module_name}_memory.json")
    
    def _load_memory(self):
        """从文件加载记忆"""
        memory_file = self._get_memory_file()
        if not os.path.exists(memory_file):
            return
        
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # 加载历史记录
            self.history = [
                MemoryEntry(**entry) for entry in data.get('history', [])
            ]
            
            # 加载模式记忆
            patterns_data = data.get('patterns', {})
            for key, pattern_data in patterns_data.items():
                self.patterns[key] = PatternMemory(**pattern_data)
            
            # 加载错误模式
            self.error_patterns = data.get('error_patterns', {})
            
            print(f"📚 已加载 {len(self.history)} 条历史记录，{len(self.patterns)} 个代码模式")
        except Exception as e:
            print(f"⚠️ 加载记忆失败: {e}")
            self.history = []
            self.patterns = {}
            self.error_patterns = {}
    
    def _save_memory(self):
        """保存记忆到文件"""
        memory_file = self._get_memory_file()
        try:
            data = {
                'history': [asdict(entry) for entry in self.history[-100:]],  # 只保存最近100条
                'patterns': {k: asdict(v) for k, v in self.patterns.items()},
                'error_patterns': self.error_patterns,
                'last_updated': time.time()
            }
            
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存记忆失败: {e}")
    
    def _hash_code(self, code: str) -> str:
        """生成代码的哈希值，用于相似性匹配"""
        # 移除空白和注释，只保留关键结构
        lines = [line.strip() for line in code.split('\n') 
                 if line.strip() and not line.strip().startswith('#')]
        normalized = '\n'.join(lines)
        return hashlib.md5(normalized.encode()).hexdigest()[:16]
    
    def record_interaction(
        self,
        uncovered_code: str,
        prompt_type: str,
        asm_code: str,
        success: bool,
        compile_success: bool,
        coverage_improved: bool,
        error_message: Optional[str] = None,
        coverage_lines: List[str] = None,
        strategy: str = "",
        feedback: str = ""
    ):
        """
        记录一次 LLM 交互
        
        参数:
            uncovered_code: 目标未覆盖代码
            prompt_type: "generate", "fix", "analysis"
            asm_code: 生成的汇编代码
            success: 是否成功（编译+执行+覆盖）
            compile_success: 是否编译成功
            coverage_improved: 是否提升了覆盖率
            error_message: 错误信息（如果有）
            coverage_lines: 覆盖的代码行列表
            strategy: 使用的策略
            feedback: LLM 反馈
        """
        code_hash = self._hash_code(uncovered_code)
        
        entry = MemoryEntry(
            timestamp=time.time(),
            module_name=self.module_name,
            uncovered_code_hash=code_hash,
            prompt_type=prompt_type,
            success=success,
            coverage_improved=coverage_improved,
            compile_success=compile_success,
            asm_code=asm_code[:2000],  # 限制长度
            error_message=error_message[:500] if error_message else None,
            coverage_lines=coverage_lines or [],
            strategy=strategy,
            feedback=feedback[:1000] if feedback else ""
        )
        
        self.history.append(entry)
        
        # 记录错误模式
        if error_message:
            error_type = self._classify_error(error_message)
            self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
        
        # 如果成功，提取代码模式
        if success and coverage_improved:
            self._extract_patterns(asm_code, uncovered_code)
        
        # 定期保存（每10条记录保存一次）
        if len(self.history) % 10 == 0:
            self._save_memory()
    
    def _classify_error(self, error_message: str) -> str:
        """分类错误类型"""
        error_lower = error_message.lower()
        
        if 'illegal operands' in error_lower or 'register' in error_lower:
            return "register_error"
        elif 'undefined' in error_lower or 'symbol' in error_lower:
            return "symbol_error"
        elif 'syntax' in error_lower or 'expected' in error_lower:
            return "syntax_error"
        elif 'timeout' in error_lower:
            return "timeout_error"
        else:
            return "other_error"
    
    def _extract_patterns(self, asm_code: str, uncovered_code: str):
        """从成功的代码中提取模式"""
        # 提取指令序列模式
        lines = [line.strip() for line in asm_code.split('\n') 
                 if line.strip() and not line.strip().startswith('#')]
        
        # 提取常见的指令序列（3-5条指令的组合）
        for i in range(len(lines) - 2):
            sequence = '\n'.join(lines[i:i+3])
            pattern_hash = hashlib.md5(sequence.encode()).hexdigest()[:12]
            
            if pattern_hash not in self.patterns:
                self.patterns[pattern_hash] = PatternMemory(
                    pattern_hash=pattern_hash,
                    pattern_type="instruction_sequence",
                    success_count=0,
                    failure_count=0,
                    examples=[],
                    last_used=time.time()
                )
            
            pattern = self.patterns[pattern_hash]
            pattern.success_count += 1
            pattern.last_used = time.time()
            
            if len(pattern.examples) < 5:
                pattern.examples.append(sequence)
    
    def get_relevant_memories(
        self,
        uncovered_code: str,
        max_memories: int = 5
    ) -> Tuple[List[MemoryEntry], List[PatternMemory]]:
        """
        根据当前未覆盖代码，检索相关的历史记忆
        
        返回:
            (相关历史记录, 相关代码模式)
        """
        code_hash = self._hash_code(uncovered_code)
        
        # 1. 查找相同或相似的代码哈希
        similar_entries = [
            entry for entry in self.history
            if entry.uncovered_code_hash == code_hash
        ]
        
        # 2. 查找成功的案例（优先）
        successful_entries = [
            entry for entry in self.history
            if entry.success and entry.coverage_improved
        ]
        
        # 3. 查找最近的失败案例（避免重复错误）
        recent_failures = [
            entry for entry in self.history[-20:]  # 最近20条
            if not entry.success
        ]
        
        # 合并并排序：相似代码 > 成功案例 > 失败案例
        relevant_entries = []
        seen_hashes = set()
        
        for entry in similar_entries + successful_entries[-10:] + recent_failures[-5:]:
            entry_hash = hash(entry.asm_code)
            if entry_hash not in seen_hashes:
                relevant_entries.append(entry)
                seen_hashes.add(entry_hash)
                if len(relevant_entries) >= max_memories:
                    break
        
        # 4. 获取成功率高的代码模式
        successful_patterns = [
            pattern for pattern in self.patterns.values()
            if pattern.success_count > pattern.failure_count
        ]
        successful_patterns.sort(key=lambda p: p.success_count / (p.success_count + p.failure_count + 1), reverse=True)
        
        return relevant_entries[:max_memories], successful_patterns[:3]
    
    def get_error_summary(self) -> str:
        """获取错误模式总结"""
        if not self.error_patterns:
            return ""
        
        sorted_errors = sorted(
            self.error_patterns.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        summary = "## 常见错误模式（避免重复）：\n"
        for error_type, count in sorted_errors[:5]:
            summary += f"- {error_type}: 出现 {count} 次\n"
        
        return summary
    
    def get_success_strategies(self) -> str:
        """获取成功的策略总结"""
        successful_entries = [
            entry for entry in self.history
            if entry.success and entry.coverage_improved and entry.strategy
        ]
        
        if not successful_entries:
            return ""
        
        # 统计策略频率
        strategy_counts = {}
        for entry in successful_entries:
            strategy_counts[entry.strategy] = strategy_counts.get(entry.strategy, 0) + 1
        
        sorted_strategies = sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True)
        
        summary = "## 成功的策略（优先使用）：\n"
        for strategy, count in sorted_strategies[:5]:
            summary += f"- {strategy}: 成功 {count} 次\n"
        
        return summary
    
    def get_context_summary(self, uncovered_code: str) -> str:
        """
        生成上下文总结，用于增强 prompt
        
        返回格式化的字符串，包含：
        1. 相关历史案例
        2. 成功的代码模式
        3. 常见错误提醒
        4. 成功策略建议
        """
        relevant_entries, successful_patterns = self.get_relevant_memories(uncovered_code)
        
        summary_parts = []
        
        # 1. 成功案例
        successful_entries = [e for e in relevant_entries if e.success and e.coverage_improved]
        if successful_entries:
            summary_parts.append("## 📚 相关成功案例：")
            for i, entry in enumerate(successful_entries[:3], 1):
                summary_parts.append(f"\n### 案例 {i}（{entry.strategy or '未知策略'}）:")
                summary_parts.append(f"```assembly\n{entry.asm_code[:300]}\n```")
                if entry.coverage_lines:
                    summary_parts.append(f"覆盖了 {len(entry.coverage_lines)} 行代码")
        
        # 2. 失败案例（避免重复）
        failed_entries = [e for e in relevant_entries if not e.success]
        if failed_entries:
            summary_parts.append("\n## ⚠️ 相关失败案例（避免重复）：")
            for i, entry in enumerate(failed_entries[:2], 1):
                if entry.error_message:
                    error_type = self._classify_error(entry.error_message)
                    summary_parts.append(f"\n### 失败案例 {i}:")
                    summary_parts.append(f"- 错误类型: {error_type}")
                    summary_parts.append(f"- 错误信息: {entry.error_message[:200]}")
        
        # 3. 成功的代码模式
        if successful_patterns:
            summary_parts.append("\n## ✅ 有效的代码模式：")
            for i, pattern in enumerate(successful_patterns[:2], 1):
                success_rate = pattern.success_count / (pattern.success_count + pattern.failure_count + 1)
                summary_parts.append(f"\n### 模式 {i}（成功率: {success_rate:.1%}）:")
                if pattern.examples:
                    summary_parts.append(f"```assembly\n{pattern.examples[0][:200]}\n```")
        
        # 4. 错误总结
        error_summary = self.get_error_summary()
        if error_summary:
            summary_parts.append(f"\n{error_summary}")
        
        # 5. 策略建议
        strategy_summary = self.get_success_strategies()
        if strategy_summary:
            summary_parts.append(f"\n{strategy_summary}")
        
        return "\n".join(summary_parts)
    
    def finalize(self):
        """完成时保存所有记忆"""
        self._save_memory()
        print(f"💾 已保存 {len(self.history)} 条记忆到 {self._get_memory_file()}")


# 全局记忆管理器（可选，用于跨模块共享）
_global_memory_cache = {}


def get_agent_memory(module_name: str) -> AgentMemory:
    """获取或创建模块的记忆管理器"""
    if module_name not in _global_memory_cache:
        _global_memory_cache[module_name] = AgentMemory(module_name)
    return _global_memory_cache[module_name]
