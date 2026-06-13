"""
Agent Memory Management System
Used to maintain context and historical experience when LLM generates test cases and improve generation accuracy

Function:
1. Conversation History Management: Record the complete context of each LLM interaction
2. Success/Failure Pattern Memorization: Learning which strategies work and which don’t
3. Code pattern learning: Identify effective code patterns and instruction sequences
4. Error pattern library: records common errors and solutions
5. Coverage improvement strategy memory: record which methods successfully improved coverage
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
    """single memory entry"""
    timestamp: float
    module_name: str
    uncovered_code_hash: str  # Hash of uncovered code, used to match similar code
    prompt_type: str  # "generate", "fix", "analysis"
    success: bool
    coverage_improved: bool
    compile_success: bool
    asm_code: str
    error_message: Optional[str] = None
    coverage_lines: List[str] = None  # Lines of code covered this time
    strategy: str = ""  # Description of the strategy used
    feedback: str = ""  # LLM feedback or analysis results


@dataclass
class PatternMemory:
    """code pattern memory"""
    pattern_hash: str
    pattern_type: str  # "instruction_sequence", "register_usage", "value_pattern"
    success_count: int
    failure_count: int
    examples: List[str]  # Successful code examples
    last_used: float


class AgentMemory:
    """
    Agent memory manager
    
    Maintains the following types of memory:
    1. Conversation History: A complete record of every LLM interaction
    2. Success Patterns: Effective Coding Patterns and Strategies
    3. Failure Modes: Ineffective Strategies and Common Mistakes
    4. Code similarity: similar code matching based on code hashing
    """
    
    def __init__(self, module_name: str, memory_dir: str = "/root/ChipFuzzer_cursor/agent_memory"):
        self.module_name = module_name
        self.memory_dir = memory_dir
        os.makedirs(memory_dir, exist_ok=True)
        
        # memory in memory
        self.history: List[MemoryEntry] = []
        self.patterns: Dict[str, PatternMemory] = {}
        self.error_patterns: Dict[str, int] = {}  # Error type -> number of occurrences
        
        # Load persistent memory
        self._load_memory()
    
    def _get_memory_file(self) -> str:
        """Get the memory file path of this module"""
        return os.path.join(self.memory_dir, f"{self.module_name}_memory.json")
    
    def _load_memory(self):
        """Load memory from file"""
        memory_file = self._get_memory_file()
        if not os.path.exists(memory_file):
            return
        
        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Load history
            self.history = [
                MemoryEntry(**entry) for entry in data.get('history', [])
            ]
            
            # load mode memory
            patterns_data = data.get('patterns', {})
            for key, pattern_data in patterns_data.items():
                self.patterns[key] = PatternMemory(**pattern_data)
            
            # Loading error mode
            self.error_patterns = data.get('error_patterns', {})
            
            print(f"📚 已加载 {len(self.history)} 条历史记录，{len(self.patterns)} 个代码模式")
        except Exception as e:
            print(f"⚠️ 加载记忆失败: {e}")
            self.history = []
            self.patterns = {}
            self.error_patterns = {}
    
    def _save_memory(self):
        """Save memory to file"""
        memory_file = self._get_memory_file()
        try:
            data = {
                'history': [asdict(entry) for entry in self.history[-100:]],  # Only save the latest 100 items
                'patterns': {k: asdict(v) for k, v in self.patterns.items()},
                'error_patterns': self.error_patterns,
                'last_updated': time.time()
            }
            
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存记忆失败: {e}")
    
    def _hash_code(self, code: str) -> str:
        """Generate a hash of the code for similarity matching"""
        # Remove whitespace and comments, leaving only key structures
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
        Record an LLM interaction
        
        parameter:
            uncovered_code: target uncovered code
            prompt_type: "generate", "fix", "analysis"
            asm_code: generated assembly code
            success: whether it is successful (compile + execution + coverage)
            compile_success: Whether the compilation was successful
            coverage_improved: Whether coverage has been improved
            error_message: error message (if any)
            coverage_lines: List of lines of code covered
            strategy: the strategy used
            feedback: LLM feedback
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
            asm_code=asm_code[:2000],  # Limit length
            error_message=error_message[:500] if error_message else None,
            coverage_lines=coverage_lines or [],
            strategy=strategy,
            feedback=feedback[:1000] if feedback else ""
        )
        
        self.history.append(entry)
        
        # Logging error patterns
        if error_message:
            error_type = self._classify_error(error_message)
            self.error_patterns[error_type] = self.error_patterns.get(error_type, 0) + 1
        
        # If successful, extract the code pattern
        if success and coverage_improved:
            self._extract_patterns(asm_code, uncovered_code)
        
        # Save regularly (save every 10 records)
        if len(self.history) % 10 == 0:
            self._save_memory()
    
    def _classify_error(self, error_message: str) -> str:
        """Classification error type"""
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
        """Extract patterns from successful code"""
        # Extract instruction sequence pattern
        lines = [line.strip() for line in asm_code.split('\n') 
                 if line.strip() and not line.strip().startswith('#')]
        
        # Extract common instruction sequences (combinations of 3-5 instructions)
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
        Retrieve relevant historical memory based on the currently uncovered code
        
        return:
            (related history, related code patterns)
        """
        code_hash = self._hash_code(uncovered_code)
        
        # 1. Find identical or similar code hashes
        similar_entries = [
            entry for entry in self.history
            if entry.uncovered_code_hash == code_hash
        ]
        
        # 2. Find successful cases (priority)
        successful_entries = [
            entry for entry in self.history
            if entry.success and entry.coverage_improved
        ]
        
        # 3. Find recent failure cases (avoid repeating mistakes)
        recent_failures = [
            entry for entry in self.history[-20:]  # Last 20 items
            if not entry.success
        ]
        
        # Merge and sort: similar code > success stories > failure stories
        relevant_entries = []
        seen_hashes = set()
        
        for entry in similar_entries + successful_entries[-10:] + recent_failures[-5:]:
            entry_hash = hash(entry.asm_code)
            if entry_hash not in seen_hashes:
                relevant_entries.append(entry)
                seen_hashes.add(entry_hash)
                if len(relevant_entries) >= max_memories:
                    break
        
        # 4. Obtain code patterns with high success rate
        successful_patterns = [
            pattern for pattern in self.patterns.values()
            if pattern.success_count > pattern.failure_count
        ]
        successful_patterns.sort(key=lambda p: p.success_count / (p.success_count + p.failure_count + 1), reverse=True)
        
        return relevant_entries[:max_memories], successful_patterns[:3]
    
    def get_error_summary(self) -> str:
        """Get error pattern summary"""
        if not self.error_patterns:
            return ""
        
        sorted_errors = sorted(
            self.error_patterns.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        summary = "# Common error patterns (avoid duplication):\n"
        for error_type, count in sorted_errors[:5]:
            summary += f"- {error_type}: 出现 {count} 次\n"
        
        return summary
    
    def get_success_strategies(self) -> str:
        """Summary of Strategies for Success"""
        successful_entries = [
            entry for entry in self.history
            if entry.success and entry.coverage_improved and entry.strategy
        ]
        
        if not successful_entries:
            return ""
        
        # Statistical strategy frequency
        strategy_counts = {}
        for entry in successful_entries:
            strategy_counts[entry.strategy] = strategy_counts.get(entry.strategy, 0) + 1
        
        sorted_strategies = sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True)
        
        summary = "# Successful strategies (preferred):\n"
        for strategy, count in sorted_strategies[:5]:
            summary += f"- {strategy}: 成功 {count} 次\n"
        
        return summary
    
    def get_context_summary(self, uncovered_code: str) -> str:
        """
        Generate contextual summaries to enhance prompts
        
        Returns a formatted string containing:
        1. Relevant historical cases
        2. Successful code patterns
        3. Common error reminders
        4. Suggestions for successful strategies
        """
        relevant_entries, successful_patterns = self.get_relevant_memories(uncovered_code)
        
        summary_parts = []
        
        # 1. Successful cases
        successful_entries = [e for e in relevant_entries if e.success and e.coverage_improved]
        if successful_entries:
            summary_parts.append("# 📚Related success stories:")
            for i, entry in enumerate(successful_entries[:3], 1):
                summary_parts.append(f"\n# # Case {i} ({entry.strategy or 'unknown strategy'}):")
                summary_parts.append(f"```assembly\n{entry.asm_code[:300]}\n```")
                if entry.coverage_lines:
                    summary_parts.append(f"覆盖了 {len(entry.coverage_lines)} 行代码")
        
        # 2. Failure cases (avoid duplication)
        failed_entries = [e for e in relevant_entries if not e.success]
        if failed_entries:
            summary_parts.append("\n# ⚠️ Related failure cases (to avoid duplication): ")
            for i, entry in enumerate(failed_entries[:2], 1):
                if entry.error_message:
                    error_type = self._classify_error(entry.error_message)
                    summary_parts.append(f"\n# # Failure case {i}:")
                    summary_parts.append(f"- 错误类型: {error_type}")
                    summary_parts.append(f"- 错误信息: {entry.error_message[:200]}")
        
        # 3. Successful coding patterns
        if successful_patterns:
            summary_parts.append("\n# ✅ Valid code patterns: ")
            for i, pattern in enumerate(successful_patterns[:2], 1):
                success_rate = pattern.success_count / (pattern.success_count + pattern.failure_count + 1)
                summary_parts.append(f"\n# # Mode {i} (success rate: {success_rate:.1%}):")
                if pattern.examples:
                    summary_parts.append(f"```assembly\n{pattern.examples[0][:200]}\n```")
        
        # 4. Summary of errors
        error_summary = self.get_error_summary()
        if error_summary:
            summary_parts.append(f"\n{error_summary}")
        
        # 5. Strategic suggestions
        strategy_summary = self.get_success_strategies()
        if strategy_summary:
            summary_parts.append(f"\n{strategy_summary}")
        
        return "\n".join(summary_parts)
    
    def finalize(self):
        """Save all memories when finished"""
        self._save_memory()
        print(f"💾 已保存 {len(self.history)} 条记忆到 {self._get_memory_file()}")


# Global memory manager (optional, for sharing across modules)
_global_memory_cache = {}


def get_agent_memory(module_name: str) -> AgentMemory:
    """Gets or creates the module's memory manager"""
    if module_name not in _global_memory_cache:
        _global_memory_cache[module_name] = AgentMemory(module_name)
    return _global_memory_cache[module_name]
