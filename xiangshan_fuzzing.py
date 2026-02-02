from getmodulecoverstate import getTheMostUncoveredModule, getTopUncoveredModules
from getuncoveredcodeline import extract_lines_with_prefix_origin, extract_lines_with_prefix_stage
from getalluncoveredcode import get_uncovered_code
from prompt import (
    asm_template, asm_template_with_loop, asm_template_boundary,
    asm_template_csr, asm_template_memory, asm_template_branch, asm_template_muldiv,
    RISCV_INSTRUCTION_GUIDE
)
from LLM_API import callOpenAI
from LLM_API_KJY import callOpenAI_KJY
from global_coverage import GlobalCoverageManager
from asm_validator import validate_asm, fix_asm, generate_error_feedback
from code_analyzer import analyze_target_code, VerilogAnalyzer, TEST_STRATEGIES
from agent_memory import AgentMemory, get_agent_memory
from spec_analyzer import get_module_spec_hints

import argparse
import glob
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime


# =========================
# 基础工具 / 配置
# =========================

@dataclass
class PathConfig:
    """路径配置，后面用这个对象统一管理路径。"""
    project_root: str = "/root/XiangShan/"
    testcase_dir: str = "/root/XiangShan/testcase"
    success_root: str = "/root/XiangShan/successed"
    all_seed_dir: str = "/root/XiangShan/all_seed"
    uncovered_code_file: str = "uncovered_code.json"
    annotated_logs_dir: str = "/root/XiangShan/logs/annotated"
    # 全局覆盖率统计使用的 annotated 目录
    global_annotated_dir: str = "/root/XiangShan/logs_global/annotated"
    # 累积覆盖率文件
    sum_dat_file: str = "/root/XiangShan/sum_gj.dat"

    @property
    def emulator_exec_dir(self) -> str:
        return self.project_root

    @property
    def emulator_cmd_prefix(self) -> str:

        #return "./build/emu -b 0 -e 0 --diff ./ready-to-run/riscv64-nemu-interpreter-so --dump-coverage -i "
        os.environ['NEMU_HOME'] = '/root/XiangShan/xs-env/NEMU/' 
        #return "./build/emu -b 0 -e 0  --dump-coverage -i "
        return "./build/emu -b 0 -e 0 --diff ./ready-to-run/riscv64-nemu-interpreter-so --dump-coverage -i "

    @property
    def coverage_cmd_prefix(self) -> str:
        # 原来是: verilator_coverage -annotate logs/annotated/ <dat_file>
        return "verilator_coverage -annotate logs2/annotated/ "


class EmulatorRunner:
    """负责调用模拟器，返回 coverage.dat 的路径。"""

    def __init__(self, config: PathConfig):
        self.config = config

    def run_elf(self, elf_relative_path: str):
        """
        elf_relative_path 例子：
          - 'successed/<module>/<xxx>.elf'
          - 'testcase/<xxx>.elf'
        """
        exec_cmd = self.config.emulator_cmd_prefix + elf_relative_path
        return self._execute_emulator_fast(self.config.emulator_exec_dir, exec_cmd)
    
    @staticmethod
    def _execute_emulator_fast(directory, exec_cmd):
        """
        在指定目录执行模拟器命令，返回 coverage 文件名和执行是否成功。
        
        所有命令和输出都会被完整记录。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n{'='*60}")
        print(f"🚀 [{timestamp}] 启动香山模拟器")
        print(f"{'='*60}")
        print(f"📂 工作目录: {directory}")
        print(f"💻 完整命令: {exec_cmd}")
        print(f"💻 命令类型: shell=True")
        print(f"-" * 60)
        print(f"📌 [阶段] 仿真运行中（可能需数秒至数分钟，请勿中断）...")
        
        # 缩短超时时间到 30 分钟（1800 秒），避免长时间卡死
        # 如果测试用例需要更长时间，可以考虑增加，但通常 30 分钟足够
        timeout_seconds = 1800  # 30 分钟
        
        try:
            start_time = time.time()
            process = subprocess.Popen(
                exec_cmd,
                shell=True,
                cwd=directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # 使用更可靠的超时机制：定期检查进程状态
            import threading
            import queue
            output_queue = queue.Queue()
            process_finished = threading.Event()
            timeout_occurred = threading.Event()
            
            def read_output():
                """在后台线程中读取输出"""
                try:
                    total_lines = []
                    while True:
                        line = process.stdout.readline()
                        if not line:
                            break
                        total_lines.append(line)
                    output_queue.put(''.join(total_lines))
                except Exception as e:
                    output_queue.put(f"读取输出时出错: {e}")
                finally:
                    process_finished.set()
            
            def timeout_killer():
                """超时后强制终止进程"""
                time.sleep(timeout_seconds)
                if not process_finished.is_set():
                    timeout_occurred.set()
                    print(f"\n⏰ 模拟器执行超时 (超过 {timeout_seconds // 60} 分钟)，强制终止进程...")
                    try:
                        # 先尝试优雅终止
                        process.terminate()
                        time.sleep(5)  # 等待 5 秒
                        if process.poll() is None:
                            # 如果还在运行，强制杀死
                            print(f"   进程未响应，强制杀死...")
                            process.kill()
                    except Exception as e:
                        print(f"   终止进程时出错: {e}")
            
            # 启动输出读取线程
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()
            
            # 启动超时监控线程
            timeout_thread = threading.Thread(target=timeout_killer, daemon=True)
            timeout_thread.start()
            
            # 添加进度监控：每 5 分钟输出一次等待信息
            def progress_monitor():
                elapsed = 0
                while not process_finished.is_set() and not timeout_occurred.is_set():
                    time.sleep(60)  # 每 60 秒检查一次
                    if process_finished.is_set() or timeout_occurred.is_set():
                        break
                    elapsed += 60
                    if elapsed % 300 == 0:  # 每 5 分钟输出一次
                        print(f"⏳ 模拟器仍在运行中... (已运行 {elapsed // 60} 分钟)")
            
            monitor_thread = threading.Thread(target=progress_monitor, daemon=True)
            monitor_thread.start()
            
            # 等待进程完成或超时
            # 使用轮询方式等待，这样可以及时响应超时
            while process.poll() is None:
                if timeout_occurred.is_set():
                    # 超时已发生，等待进程被终止
                    time.sleep(1)
                    continue
                time.sleep(0.5)  # 每 0.5 秒检查一次进程状态
            
            # 等待输出读取完成（最多等待 10 秒）
            process_finished.wait(timeout=10)
            
            # 获取输出
            try:
                total_output = output_queue.get(timeout=1)
            except queue.Empty:
                total_output = ""
            
            elapsed = time.time() - start_time
            
            # 检查是否超时
            if timeout_occurred.is_set():
                print(f"⏰ 模拟器执行超时 (超过 {timeout_seconds // 60} 分钟)，已强制终止")
                print(f"   提示：如果测试用例确实需要更长时间，可以考虑增加超时时间")
                print(f"{'='*60}\n")
                return None, False
            
            # 输出模拟器日志（限制长度）
            output_lines = total_output.strip().split('\n') if total_output else []
            if len(output_lines) > 30:
                print(f"📤 模拟器输出 (前15行):")
                for line in output_lines[:15]:
                    print(f"   {line}")
                print(f"   ... (省略 {len(output_lines) - 30} 行) ...")
                print(f"📤 模拟器输出 (后15行):")
                for line in output_lines[-15:]:
                    print(f"   {line}")
            else:
                print(f"📤 模拟器输出:")
                for line in output_lines:
                    print(f"   {line}")

            # 默认值
            coverage_filename = "logs/coverage.dat"

            # 优先匹配新的输出格式:
            # 例如：dump coverage data to /root/XiangShan/build/2025-11-25-21-45-06.coverage.dat...
            match = re.search(
                r'dump coverage data to\s*(.+?\.coverage\.dat)\.\.\.',
                total_output
            )
            if match:
                coverage_filename = match.group(1).strip()
                print(f"📁 找到 coverage 文件: {coverage_filename}")
            else:
                # 兼容旧格式：Generated coverage filename: xxx
                match_old = re.search(
                    r'Generated coverage filename:\s*([^\s]+)',
                    total_output
                )
                if match_old:
                    coverage_filename = match_old.group(1).strip()
                    print(f"📁 找到 coverage 文件(旧格式): {coverage_filename}")
                else:
                    print("⚠️ 未在输出中找到 coverage 文件名，使用默认值 logs/coverage.dat")

            returncode = process.returncode
            status_icon = "✅" if returncode == 0 else "❌"
            print(f"-" * 60)
            print(f"{status_icon} 模拟器执行完成")
            print(f"   返回值: {returncode}")
            print(f"   耗时: {elapsed:.2f} 秒")
            print(f"{'='*60}\n")
            return coverage_filename, returncode == 0

        except Exception as e:
            print(f"❌ 执行错误: {e}")
            import traceback
            traceback.print_exc()
            # 确保进程被终止
            try:
                if 'process' in locals():
                    process.terminate()
                    time.sleep(2)
                    if process.poll() is None:
                        process.kill()
            except:
                pass
            print(f"{'='*60}\n")
            return None, False



class SubprocessRunner:
    """统一封装在某个目录下执行通用命令。"""

    @staticmethod
    def run(directory, command, shell=True, log_prefix="🔧"):
        """
        使用 subprocess 在指定目录执行命令。
        
        所有命令都会被完整记录到日志中，包括：
        - 工作目录
        - 完整命令
        - 执行结果
        - 输出内容
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n{'='*60}")
        print(f"{log_prefix} [{timestamp}] 执行命令")
        print(f"{'='*60}")
        print(f"📂 工作目录: {directory}")
        print(f"💻 完整命令: {command}")
        print(f"💻 命令类型: {'shell' if shell else 'executable'}")
        print(f"-" * 60)
        
        try:
            start_time = time.time()
            result = subprocess.run(
                command,
                shell=shell,
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=6000
            )
            elapsed = time.time() - start_time

            status_icon = "✅" if result.returncode == 0 else "❌"
            print(f"{status_icon} 返回值: {result.returncode}")
            print(f"⏱️ 耗时: {elapsed:.2f} 秒")
            
            if result.stdout:
                # 限制输出长度，避免日志过长
                stdout_lines = result.stdout.strip().split('\n')
                if len(stdout_lines) > 20:
                    print(f"📤 标准输出 (前10行):")
                    for line in stdout_lines[:10]:
                        print(f"   {line}")
                    print(f"   ... (省略 {len(stdout_lines) - 20} 行) ...")
                    print(f"📤 标准输出 (后10行):")
                    for line in stdout_lines[-10:]:
                        print(f"   {line}")
                else:
                    print(f"📤 标准输出:")
                    for line in stdout_lines:
                        print(f"   {line}")
            
            if result.stderr:
                print(f"⚠️ 标准错误:\n{result.stderr}")
            
            print(f"{'='*60}\n")
            return result

        except subprocess.TimeoutExpired:
            print(f"⏰ 命令执行超时 (超过 6000 秒)")
            print(f"{'='*60}\n")
            return None
        except Exception as e:
            print(f"❌ 执行错误: {e}")
            print(f"{'='*60}\n")
            return None


# =========================
# 文件 / ASM 工具
# =========================

def read_assembly_file(file_path):
    """从汇编文件中读取代码内容。"""
    try:
        with open(file_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Assembly file not found: {file_path}")
        return None


def list_elf_files(directory):
    """
    列出目录中的 .elf 文件。
    （原函数名叫 read_all_asm_files_listdir，其实读的是 elf，这里改个更直白的名字）
    """
    if not os.path.exists(directory):
        print(f"❌ 目录 '{directory}' 不存在")
        return []

    all_files = os.listdir(directory)
    elf_files = [
        f for f in all_files
        if os.path.isfile(os.path.join(directory, f))
        and f.lower().endswith('.elf')
    ]
    return elf_files


class AssemblyCodeParser:
    """解析 LLM 生成的汇编代码、清洗并保存到文件。"""

    def __init__(self, module_name: str, config: PathConfig):
        self.sections = {}
        self.instructions = []
        self.module_name = module_name
        self.file_hash = None
        self.config = config

    def generate_filename_hash(self, content, prefix="asm"):
        """基于内容生成 hash 文件名。"""
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.file_hash = content_hash
        return f"{prefix}_{timestamp}_{content_hash}.S"

    def parse_from_llm_output(self, text):
        """从 LLM 输出中提取汇编代码块并解析。支持多种格式。"""
        code_text = None
        
        # 尝试多种代码块格式
        patterns = [
            r"```assembly\s*\n(.*?)\n```",      # ```assembly
            r"```asm\s*\n(.*?)\n```",           # ```asm
            r"```riscv\s*\n(.*?)\n```",         # ```riscv
            r"```s\s*\n(.*?)\n```",             # ```s
            r"```\s*\n(.*?)\n```",              # ``` (无语言标记)
            r"'''assembly\s*\n(.*?)\n'''",      # '''assembly
            r"'''asm\s*\n(.*?)\n'''",           # '''asm
        ]
        
        for pattern in patterns:
            code_match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if code_match:
                code_text = code_match.group(1)
                break
        
        # 如果还是没找到，尝试查找 .section .text 或 .global _start
        if not code_text:
            # 查找以 .section 或 .global 开头的代码段
            match = re.search(
                r'(\.(?:section|global)[^\n]*\n(?:.*?\n)*?(?:ecall|unimp))',
                text, re.DOTALL | re.IGNORECASE
            )
            if match:
                code_text = match.group(1)
        
        if not code_text:
            return False
        
        self._parse_assembly_code(code_text)
        return True

    def _parse_assembly_code(self, code_text):
        """解析汇编代码结构，按 section 分类。"""
        lines = code_text.split('\n')
        current_section = '.text'  # 默认段

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 段定义
            if line.startswith('.section'):
                section_match = re.match(r'\.section\s+([\.\w]+)', line)
                if section_match:
                    current_section = section_match.group(1)
                    self.sections[current_section] = []
            elif line.startswith('.'):
                # 其他伪指令
                if current_section not in self.sections:
                    self.sections[current_section] = []
                self.sections[current_section].append(line)
            else:
                # 指令
                instruction = self._clean_instruction(line)
                if instruction:
                    if current_section not in self.sections:
                        self.sections[current_section] = []
                    self.sections[current_section].append(instruction)
                    self.instructions.append(instruction)

    @staticmethod
    def _clean_instruction(line):
        """移除行内注释，返回干净的指令行。"""
        line = re.sub(r'#.*$', '', line).strip()
        line = re.sub(r'//.*$', '', line).strip()
        return line if line else None

    def generate_clean_assembly(self):
        """生成干净的汇编文本。"""
        output = []
        for section, content in self.sections.items():
            output.append(f".section {section}")
            for item in content:
                if item.startswith('.'):
                    output.append(item)
                else:
                    output.append(f"    {item}")
            output.append("")
        return '\n'.join(output)

    def save_to_file(self):
        """保存汇编到 testcase 目录，返回相对文件名（不含路径）。"""
        clean_code = self.generate_clean_assembly()
        name = self.generate_filename_hash(clean_code)
        os.makedirs(self.config.testcase_dir, exist_ok=True)

        filename = os.path.join(self.config.testcase_dir, f"{self.module_name}_{name}")
        with open(filename, 'w') as f:
            f.write(clean_code)

        print(f"汇编代码已保存到: {filename}")
        # 返回相对 testcase 目录的文件名，后续拼 elf 需要
        return f"{self.module_name}_{name}"

    def analyze_coverage(self):
        """简单分析与覆盖相关的指令。"""
        coverage_related = []
        for instr in self.instructions:
            if any(keyword in instr for keyword in ['li', 'sw', 'ecall', 'jmp', 'call']):
                coverage_related.append(instr)
        return coverage_related


# =========================
# 未覆盖代码仓库
# =========================

class UncoveredCodeRepository:
    """负责管理 uncovered_code.json 和内存中的全局未覆盖代码。"""

    def __init__(self, config: PathConfig , Coverage_filename_origin, Coverage_filename_later):
        self.config = config
        self.all_module_code = self._load()
        self.baseline_len = len(self.all_module_code)
        self.Coverage_filename_origin = Coverage_filename_origin
        self.Coverage_filename_later = Coverage_filename_later
        

    def _load(self):
        try:
            with open(self.config.uncovered_code_file, 'r', encoding='utf-8') as f:
                all_code = json.load(f)
                print(f"Loaded {len(all_code)} uncovered code lines from file")
                return all_code
        except FileNotFoundError:
            print("uncovered_code.json not found. Please run the collection script first.")
            return []
        except json.JSONDecodeError:
            print("Error decoding JSON file. The file may be corrupted.")
            return []

    def save(self):
        with open(self.config.uncovered_code_file, 'w', encoding='utf-8') as f:
            json.dump(self.all_module_code, f, ensure_ascii=False, indent=2)

    def update_after_coverage(self):
        """
        调用 get_uncovered_code() 获取新的全局未覆盖代码，
        并与当前 self.all_module_code 做交集。
        """
        new_all_module_code, flag = get_uncovered_code(self.Coverage_filename_origin, self.Coverage_filename_later)
        if not flag:
            return False

        self.all_module_code = [
            line for line in self.all_module_code if line in new_all_module_code
        ]

        if len(self.all_module_code) < self.baseline_len:
            print(
                f"🎉✅✅✅ 覆盖成功！本次测试覆盖了 "
                f"{self.baseline_len - len(self.all_module_code)} 行代码"
            )
            print(f"🎉✅✅✅ 剩余 {len(self.all_module_code)} 行代码")
            self.baseline_len = len(self.all_module_code)
            self.save()
            return True

        print(f"good seed 更新后所有模块未覆盖代码行数: {len(self.all_module_code)}")
        return False


# =========================
# 其他小工具
# =========================

def filter_print_cond_blocks(code_lines):
    """
    过滤掉所有打印相关的代码行，包括：
    1. if (`PRINTF_COND) begin ... $fwrite 的代码块
    2. 所有包含 $fwrite 的行（不管是否在 PRINTF_COND 块中）
    3. 所有包含 PRINTF_COND 的行
    这样可以避免大量打印语句导致页面卡死
    """
    filtered = []
    skip = False
    fwrite_continuation = False  # 标记是否在 $fwrite 的续行中

    for line in code_lines:
        stripped = line.strip()
        
        # 跳过空行和纯注释行
        if not stripped or stripped.startswith('//'):
            continue
        
        # 1. 检测 PRINTF_COND 块开始
        if 'if (`PRINTF_COND)' in line or 'if(PRINTF_COND)' in line:
            skip = True
            continue
        
        # 2. 检测 $fwrite 语句（包括续行）
        if '$fwrite' in stripped:
            skip = True
            fwrite_continuation = True
            continue
        
        # 3. 检测 $fwrite 的续行（通常以逗号或分号结尾，或者包含 io_timer 等）
        if fwrite_continuation:
            # 如果遇到分号，说明 $fwrite 语句结束
            if ';' in stripped:
                fwrite_continuation = False
                skip = False
            # 如果遇到 end 或 begin，说明块结束
            elif stripped.startswith('end') or stripped.startswith('begin'):
                fwrite_continuation = False
                skip = False
            # 否则继续跳过（续行）
            continue
        
        # 4. 检测 PRINTF_COND 相关的其他模式
        if 'PRINTF_COND' in stripped:
            skip = True
            continue
        
        # 5. 如果遇到 end，结束 skip 状态
        if skip and (stripped.startswith('end') or stripped.startswith('endmodule')):
            skip = False
            # 不添加 end 行本身（如果它是 PRINTF_COND 块的结束）
            if 'PRINTF_COND' not in stripped:
                filtered.append(line)
            continue
        
        # 6. 只有在不跳过的情况下才添加
        if not skip and not fwrite_continuation:
            filtered.append(line)

    return filtered



def build_fix_prompt(broken_code: str, error_msg: str, uncovered_code: str) -> str:
    """
    生成让 LLM 修复代码的 prompt（修复模式）
    
    参数:
        broken_code: 有错误的汇编代码
        error_msg: 编译器的错误信息
        uncovered_code: 目标未覆盖代码
    """
    error_feedback = generate_error_feedback(error_msg)
    
    prompt = f"""你是一个 RISC-V 汇编专家。以下汇编代码编译失败，请修复它。

## 编译错误信息：
{error_feedback}

## 原始错误输出（前 500 字符）：
```
{error_msg[:500]}
```

## 需要修复的汇编代码：
```assembly
{broken_code}
```

## 目标：触发以下未覆盖代码
```verilog
{uncovered_code[:1000]}
```

## 重要修复规则：
1. **寄存器限制**：RISC-V 只有 t0-t6（没有 t7/t8/t9），s0-s11，a0-a7
2. **CSR 寄存器**：使用数字编号（如 0x300 而非 mstatus）
3. **立即数范围**：大多数指令的立即数必须在 12 位范围内（-2048 到 2047）
4. **标签语法**：标签后必须有冒号，如 `loop:`
5. **指令格式**：确保操作数顺序正确（目标寄存器在前）

请直接输出修复后的完整汇编代码，用 ```assembly 和 ``` 包裹。
只输出修复后的代码，不要解释。
"""
    return prompt


def build_analysis_prompt(asm_code: str, uncovered_code: str, coverage_result: str) -> str:
    """
    生成让 LLM 分析为什么没有覆盖到目标代码的 prompt
    
    参数:
        asm_code: 执行的汇编代码
        uncovered_code: 目标未覆盖代码
        coverage_result: 覆盖率结果描述
    """
    prompt = f"""你是一个硬件验证专家。以下汇编代码编译和执行都成功了，但没有覆盖到目标代码。请分析原因并生成改进后的代码。

## 执行的汇编代码：
```assembly
{asm_code[:1500]}
```

## 目标未覆盖代码：
```verilog
{uncovered_code[:1000]}
```

## 覆盖结果：
{coverage_result}

## 请分析：
1. 为什么当前代码没有触发目标分支？
2. 需要什么条件才能触发？
3. 生成一个改进后的汇编代码

请直接输出改进后的完整汇编代码，用 ```assembly 和 ``` 包裹。
在代码前用注释简要说明改进思路（1-2行）。
"""
    return prompt


def build_prompt(uncovered_code, good_seeds, scala_code, compile_error=None, no_coverage_count=0, agent_memory=None, module_name=None, use_spec=False):
    """
    生成发给 LLM 的 prompt。
    
    参数:
        uncovered_code: 未覆盖的代码
        good_seeds: 成功的汇编代码示例
        scala_code: 对应的 Scala 代码
        compile_error: 上次编译的错误信息（如果有）
        no_coverage_count: 连续无覆盖次数
        agent_memory: AgentMemory 实例，用于提供上下文记忆
        module_name: 当前测试的模块名（用于查找 spec 信息）
        use_spec: 是否使用 spec 文件信息（通过命令行参数控制）
    """
    
    # 分析目标代码，提取关键信息（只分析一次，避免重复）
    analyzer = VerilogAnalyzer()
    analysis_result = analyzer.analyze_uncovered_code(uncovered_code)
    code_type = analysis_result['code_type']
    
    # 生成格式化的分析结果
    code_analysis = f"代码类型: {code_type}"
    if analysis_result['conditions']:
        code_analysis += f"\n关键条件: {len(analysis_result['conditions'])} 个"
        for cond in analysis_result['conditions'][:3]:
            code_analysis += f"\n  - [{cond['type']}] {cond['expression'][:50]}"
    if analysis_result['values']:
        code_analysis += f"\n关键常量值: {', '.join(analysis_result['values'][:5])}"
    if analysis_result['suggestions']:
        code_analysis += f"\n测试建议:"
        for i, sug in enumerate(analysis_result['suggestions'][:3], 1):
            code_analysis += f"\n  {i}. {sug}"
    
    # 基于代码类型选择模板
    type_templates = {
        'csr': [asm_template_csr, asm_template],
        'memory': [asm_template_memory, asm_template_with_loop],
        'branch': [asm_template_branch, asm_template_with_loop],
        'alu': [asm_template_muldiv, asm_template_boundary, asm_template_with_loop],
        'float': [asm_template_boundary, asm_template],
        'exception': [asm_template_csr, asm_template_boundary],
        'general': [asm_template, asm_template_with_loop, asm_template_boundary],
    }
    
    available_templates = type_templates.get(code_type, type_templates['general'])
    selected_template = random.choice(available_templates)
    
    prompt = f"""你是一个 RISC-V 汇编专家，正在进行硬件模糊测试。请生成能够触发以下未覆盖代码执行的 RISC-V 汇编程序。

{RISCV_INSTRUCTION_GUIDE}

## 未覆盖的 Verilog 代码：
```verilog
{uncovered_code}
```

## 代码分析结果：
{code_analysis}

## 生成要求：
1. **先分析**：仔细阅读上面的代码分析结果，理解触发条件
2. **针对性生成**：根据分析结果，生成能触发这些条件的指令序列
3. **使用建议的值**：如果分析中提到了关键常量值，尝试使用这些值
4. **测试边界情况**：使用边界值（0, -1, MAX, MIN）测试
5. **灵活使用控制流**：可以使用循环、分支、跳转等任何合法指令来增加测试覆盖
6. **代码长度**：生成足够长的指令序列（建议 50-200 条指令），确保能充分触发硬件逻辑
7. 【关键】寄存器只能用: t0-t6, s0-s11, a0-a7（没有 t7/t8/t9！）

## 输出格式：
```assembly
.section .text
.global _start

_start:
    # 简要说明测试策略（1-2行注释）
    # 你的测试代码...
    
    # 程序退出（必须保留）
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
```

## 参考示例：
```assembly
{selected_template}
```
"""
    
    # 如果有记忆系统，添加上下文记忆
    if agent_memory:
        memory_context = agent_memory.get_context_summary(uncovered_code)
        if memory_context:
            prompt += f"\n\n{memory_context}\n"
    
    # 添加 SPEC 文件信息（如果可用）
    # 优先使用传入的 module_name，否则尝试从代码中提取
    detected_module_name = module_name
    
    if not detected_module_name:
        # 从 uncovered_code 中提取模块名
        module_match = re.search(r'(\w+)\.sv', uncovered_code[:200])
        if module_match:
            detected_module_name = module_match.group(1)
    
    # 只有在启用 spec 分析时才添加 spec 信息
    if use_spec and detected_module_name:
        try:
            spec_hints = get_module_spec_hints(detected_module_name, uncovered_code)
            if spec_hints:
                prompt += f"\n\n{spec_hints}\n"
        except Exception as e:
            # spec 分析失败不影响主流程
            pass

    # 如果有编译错误，添加简洁的错误反馈
    if compile_error:
        error_feedback = generate_error_feedback(compile_error)
        prompt += f"""

## ⚠️ 上次编译失败：
{error_feedback}

请修正错误后重新生成。
"""

    # 如果连续多次无覆盖，增加提示
    if no_coverage_count >= 2:
        prompt += f"""

## ⚠️ 连续 {no_coverage_count} 次测试未覆盖新代码
请尝试以下策略：
1. 使用不同的边界值（0, -1, MAX_INT, MIN_INT）
2. 尝试触发不同的条件分支
3. 使用更多的寄存器组合
4. 尝试异常情况（除零、溢出等）
"""

    # 添加成功的种子作为参考（概率性）
    if good_seeds and random.random() < 0.4:
        selected_seed = random.choice(good_seeds)
        # 限制长度
        if len(selected_seed) > 1000:
            selected_seed = selected_seed[:1000] + "\n    # ...\n"
        prompt += f"""

## 成功案例参考：
```assembly
{selected_seed}
```
"""

    return prompt


# =========================
# 组合逻辑：模块级测试会话
# =========================

class ModuleCoverageSession:
    """围绕一个 module 的完整测试会话（包含已有 good seeds + LLM 新生成）。"""

    def __init__(self, module_name: str, config: PathConfig, Coverage_filename_origin, Coverage_filename_later, model, global_coverage_manager=None, use_spec=False, use_llm_report=True):
        self.module_name = module_name
        self.config = config
        self.use_llm_report = use_llm_report  # 是否使用 LLM 分析覆盖代码生成用例报告
        self.emulator = EmulatorRunner(config)
        self.subproc = SubprocessRunner()
        self.uncovered_repo = UncoveredCodeRepository(config, Coverage_filename_origin, Coverage_filename_later)
        self.Coverage_filename_origin = Coverage_filename_origin
        self.Coverage_filename_later = Coverage_filename_later
        self.model = model
        self.use_spec = use_spec  # 是否使用 spec 文件分析

        # 使用传入的全局覆盖率管理器，或创建新的（向后兼容）
        if global_coverage_manager is not None:
            self.global_coverage_manager = global_coverage_manager
            print(f"🌍 使用共享的全局覆盖率管理器")
        else:
            self.global_coverage_manager = GlobalCoverageManager(
                project_root=config.project_root,
                annotated_dir=config.global_annotated_dir,
                sum_dat_file=config.sum_dat_file
            )
            print(f"🌍 全局覆盖率管理器已初始化")
        
        print(f"   annotated 目录: {config.global_annotated_dir}")
        print(f"   累积覆盖率文件: {config.sum_dat_file}")

        # 初始化统计数据
        self.statistics = {
            "llm_generation_count": 0,  # LLM 生成次数
            "emulator_success_count": 0,  # 模拟器成功执行次数
            "coverage_improved_count": 0,  # 成功覆盖的 case 个数（带来覆盖率提升的用例数）
            "coverage_data": [],  # 覆盖率变化数据 [{timestamp, coverage_percentage, uncovered_lines, iteration}]
            "start_time": time.time(),
        }
        
        # 获取该模块的未覆盖代码
        print(f"📖 正在读取模块 [{self.module_name}] 的未覆盖代码...")
        self.uncovered_module_lines, self.file_infos, self.scala_lines = \
            extract_lines_with_prefix_origin(self.module_name, self.Coverage_filename_origin)

        print(f"   ✅ 读取完成，未覆盖代码行数: {len(self.uncovered_module_lines)}")
        
        # 过滤 printf block 和所有 $fwrite 相关代码（避免大量打印语句导致页面卡死）
        self.uncovered_module_lines = filter_print_cond_blocks(self.uncovered_module_lines)
        print(f"the total uncovered code line after filter is {len(self.uncovered_module_lines)}")
        
        # 只打印前 20 行作为示例，避免输出过多导致卡顿
        print("前 20 行未覆盖代码示例:")
        for item in self.uncovered_module_lines[:20]:
            print(item)
        if len(self.uncovered_module_lines) > 20:
            print(f"... 还有 {len(self.uncovered_module_lines) - 20} 行未覆盖代码")

        self.good_seeds = []  # 新生成且成功覆盖的 asm 文本
        self.fail_num = 0

        # 初始化 Agent Memory 系统
        self.agent_memory = get_agent_memory(module_name)
        print(f"🧠 Agent Memory 系统已初始化（已有 {len(self.agent_memory.history)} 条历史记录）")

        # 整个工程的全局未覆盖（用于打印信息）
        print(f"📊 全局未覆盖代码行数: {len(self.uncovered_repo.all_module_code)}")
        print(f"✅ 模块 [{self.module_name}] 初始化完成")

    # -------- 运行已有 good seeds (success 目录中的 elf) --------

    def run_existing_success_elfs(self):
        success_dir = os.path.join(self.config.success_root, self.module_name)
        os.makedirs(success_dir, exist_ok=True)

        elf_files = list_elf_files(success_dir)
        if not elf_files:
            print(f"📂 模块 [{self.module_name}] 无已有成功用例，跳过")
            return

        print(f"📂 模块 [{self.module_name}] 发现 {len(elf_files)} 个已有成功用例，开始运行...")
        
        # 收集所有 dat 文件，批量处理以减少覆盖率更新次数
        dat_files = []
        for idx, elf_file_name in enumerate(elf_files, 1):
            print(f"   [{idx}/{len(elf_files)}] 运行用例: {elf_file_name}")
            elf_rel_path = f"successed/{self.module_name}/{elf_file_name}"
            dat_file, ok = self.emulator.run_elf(elf_rel_path)
            if not ok or not dat_file:
                print(f"      ⚠️ 运行失败，跳过")
                continue
            
            dat_files.append(dat_file)
            print(f"      ✅ 运行成功，生成: {dat_file}")
        
        if not dat_files:
            print(f"   ⚠️ 所有用例运行失败，跳过覆盖率更新")
            return
        
        # 优化：逐个合并到 sum_gj.dat，但只更新一次 annotated 报告（大幅减少耗时）
        print(f"\n🔄 批量处理 {len(dat_files)} 个覆盖率文件...")
        print(f"   策略：逐个合并到累积文件，最后统一更新报告（减少更新次数）")
        
        # 逐个合并 dat 文件到 sum_gj.dat（只合并，不更新报告）
        for idx, dat_file in enumerate(dat_files, 1):
            print(f"   [{idx}/{len(dat_files)}] 合并覆盖率文件: {os.path.basename(dat_file)}")
            
            # 只合并，不更新 annotated 报告
            if not self.global_coverage_manager.merge_coverage_dat(dat_file):
                print(f"      ❌ 合并失败，跳过此文件")
                continue
            print(f"      ✅ 合并成功")
        
        # 所有文件合并完成后，只更新一次 annotated 报告和 coverage.info
        print(f"\n🔄 所有覆盖率文件已合并，正在更新全局覆盖率报告...")
        print(f"   注意：这可能需要 30-60 秒，请耐心等待...")
        
        # 更新 annotated 报告（只执行一次）
        if self.global_coverage_manager.update_annotated_report():
            print(f"   ✅ Annotated 报告已更新")
        else:
            print(f"   ⚠️ Annotated 报告更新失败")
        
        # 更新 coverage.info（只执行一次）
        if self.global_coverage_manager.update_coverage_info():
            print(f"   ✅ Coverage.info 已更新")
        else:
            print(f"   ⚠️ Coverage.info 更新失败")
        
        # 重新统计未覆盖代码行（用于更新模块级未覆盖列表）
        print(f"   📊 正在重新统计未覆盖代码...")
        new_uncovered_lines = self.global_coverage_manager.get_all_uncovered_lines()
        cov = self.global_coverage_manager.get_total_coverage_from_genhtml(use_cache=False)
        pct = cov.get("coverage_percentage", 0) or 0
        print(f"   📊 当前覆盖率: {pct:.2f}%")
        
        # 更新模块的未覆盖代码列表（从全局 annotated 目录读取）
        global_module_file = os.path.join(
            self.config.global_annotated_dir, 
            f"{self.module_name}.sv"
        )
        if os.path.exists(global_module_file):
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, global_module_file
            )
            # 更新模块未覆盖代码列表
            self.uncovered_module_lines = [
                line for line in self.uncovered_module_lines
                if line in uncovered_code_stage
            ]
            print(f"   ✅ 模块 [{self.module_name}] 未覆盖代码列表已更新: {len(self.uncovered_module_lines)} 行")
        
        print(f"✅ 模块 [{self.module_name}] 已有成功用例处理完成")

    # -------- 处理 coverage.dat -> 更新未覆盖行 --------

    def _apply_coverage_dat(self, dat_file: str, from_good_seed: bool):
        """
        调用 verilator_coverage + 更新模块未覆盖 & 全局未覆盖行。
        
        优化：直接更新全局覆盖率，不再重复更新临时目录（logs2/annotated）
        因为全局 annotated 目录已经包含了所有信息，模块级检查可以直接从全局目录读取
        """
        # 使用全局覆盖率管理器检查全局覆盖率变化
        # 这会自动：1) 合并 dat 到 sum_gj.dat  2) 更新全局 annotated 目录  3) 更新 coverage.info
        print(f"📌 [阶段] 开始对当前 case 生成的覆盖率进行统计分析（合并 dat、更新 annotated、更新 coverage.info）")
        print(f"📌 [阶段] 正在合并并更新覆盖率（约需数秒），请稍候...")
        print(f"🔄 正在应用覆盖率数据: {dat_file}")
        global_improved, global_reduced, global_newly_covered = \
            self.global_coverage_manager.check_global_improvement(dat_file)
        
        # 保存全局覆盖率提升的标记，供后续判断是否保存测试用例
        self._last_global_improved = global_improved
        self._last_global_reduced = global_reduced
        self._last_global_newly_covered = global_newly_covered

        # 从更新后的全局 annotated 目录读取模块的未覆盖代码
        # 这样可以确保模块级检查也反映全局最新状态
        global_module_file = os.path.join(
            self.config.global_annotated_dir, 
            f"{self.module_name}.sv"
        )
        
        # 优先使用全局 annotated 目录，如果文件存在的话
        if os.path.exists(global_module_file):
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, global_module_file
            )
        else:
            # 回退到原来的目录
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, self.Coverage_filename_later
            )
        
        # 计算本模块新覆盖的行
        covered_lines = [
            line for line in self.uncovered_module_lines
            if line not in uncovered_code_stage
        ]
        
        # 更新模块未覆盖代码列表
        self.uncovered_module_lines = [
            line for line in self.uncovered_module_lines
            if line in uncovered_code_stage
        ]

        if from_good_seed:
            print(f"good seed 更新后该模块未覆盖代码行数: {len(self.uncovered_module_lines)}")
        else:
            print(f"更新后未覆盖代码行数: {len(self.uncovered_module_lines)}")

        # 如果有全局覆盖率提升，打印确认信息
        if global_improved:
            print(f"✅ 全局覆盖率已更新到: {self.config.global_annotated_dir}")

        # 更新旧的全局未覆盖信息（保持兼容）
        updated = self.uncovered_repo.update_after_coverage()
        if from_good_seed and not updated:
            print(f"good seed 更新后所有模块未覆盖代码行数: "
                  f"{len(self.uncovered_repo.all_module_code)}")

        return covered_lines

    # -------- LLM 驱动的循环生成 --------

    def _select_uncovered_batch(self):
        """
        智能选择一批未覆盖代码行 + 对应 scala 行。
        
        策略：
        1. 如果未覆盖代码很多，选择一批（30-50行）给 LLM 处理
        2. 根据失败次数动态调整选择范围，避免重复选择相同代码
        3. 优先选择不同类型的代码（通过分析代码特征）
        """
        # 动态批次大小：根据未覆盖代码数量调整
        if len(self.uncovered_module_lines) >= 50:
            batch_size = 50
        elif len(self.uncovered_module_lines) >= 20:
            batch_size = 30
        else:
            batch_size = len(self.uncovered_module_lines)
        
        # 根据失败次数选择不同的批次（避免重复）
        batch_offset = (self.fail_num // 5) * batch_size
        
        if len(self.uncovered_module_lines) > batch_size:
            start_idx = min(batch_offset, len(self.uncovered_module_lines) - batch_size)
            end_idx = start_idx + batch_size
            uncovered_code = self.uncovered_module_lines[start_idx:end_idx]
            
            # 对应的 scala 行（如果可用）
            scala_start = min(start_idx, len(self.scala_lines))
            scala_end = min(end_idx, len(self.scala_lines))
            scala_lines = self.scala_lines[scala_start:scala_end] if scala_start < len(self.scala_lines) else []
        else:
            uncovered_code = self.uncovered_module_lines
            scala_lines = self.scala_lines

        uncovered_code_txt = "".join(line + "\n" for line in uncovered_code)
        scala_code_txt = "".join(
            (line + "\n") for line in scala_lines if line is not None
        )
        
        print(f"📋 选择了 {len(uncovered_code)} 行未覆盖代码（批次偏移: {batch_offset}）")
        return uncovered_code_txt, scala_code_txt

    def get_module_coverage_stats(self) -> dict:
        """获取当前模块的覆盖率统计信息"""
        return {
            "module_name": self.module_name,
            "uncovered_lines": len(self.uncovered_module_lines),
            "good_seeds_count": len(self.good_seeds),
        }

    def run_llm_loop(self, max_iterations: int = 20, save_stats_callback=None) -> dict:
        """
        主循环：不断调用 LLM 生成新的测试用例并尝试覆盖。
        
        参数:
            max_iterations: 最大尝试次数，达到后自动退出
            save_stats_callback: 可选的保存统计数据回调函数，用于实时保存统计数据
            
        返回:
            dict: 包含执行结果的字典
                - status: "completed" (无未覆盖代码) / "max_iterations" (达到最大次数) / "error"
                - iterations: 实际执行的迭代次数
                - initial_uncovered: 初始未覆盖行数
                - final_uncovered: 最终未覆盖行数
                - covered_count: 本次覆盖的行数
        """
        compile_error_info = None
        consecutive_compile_errors = 0
        consecutive_no_coverage = 0  # 连续无覆盖次数
        iteration_count = 0
        last_asm_code = None  # 保存上次生成的代码，用于修复模式
        fix_attempt_count = 0  # 修复尝试次数
        MAX_FIX_ATTEMPTS = 2  # 每次编译失败最多修复尝试次数
        
        # 记录初始状态
        initial_uncovered_count = len(self.uncovered_module_lines)
        initial_uncovered_lines = self.uncovered_module_lines.copy()
        
        print(f"\n{'='*60}")
        print(f"📊 模块 [{self.module_name}] 开始测试")
        print(f"   初始未覆盖代码行数: {initial_uncovered_count}")
        print(f"   最大尝试次数: {max_iterations}")
        print(f"   启用修复模式: 是（每次最多 {MAX_FIX_ATTEMPTS} 次修复尝试）")
        print(f"{'='*60}")
        
        while len(self.uncovered_module_lines) >= 1:
            iteration_count += 1
            
            # 检查是否达到最大尝试次数
            if iteration_count > max_iterations:
                print(f"\n⚠️ 模块 [{self.module_name}] 达到最大尝试次数 ({max_iterations})，切换到下一个模块")
                
                # 保存记忆
                self.agent_memory.finalize()
                
                return {
                    "status": "max_iterations",
                    "iterations": iteration_count - 1,
                    "initial_uncovered": initial_uncovered_count,
                    "final_uncovered": len(self.uncovered_module_lines),
                    "covered_count": initial_uncovered_count - len(self.uncovered_module_lines),
                    "initial_lines": initial_uncovered_lines,
                    "final_lines": self.uncovered_module_lines.copy(),
                }
            print(f"\n{'='*60}")
            print(f"📊 模块 [{self.module_name}] 第 {iteration_count}/{max_iterations} 次尝试")
            print(f"📊 剩余未覆盖代码行数: {len(self.uncovered_module_lines)}")
            print(f"📊 失败计数: {self.fail_num}, 连续编译错误: {consecutive_compile_errors}")
            print(f"{'='*60}")

            uncovered_code_line, scala_code_line = self._select_uncovered_batch()
            
            # 使用改进的 prompt，传入编译错误信息、无覆盖次数、记忆系统、模块名和 spec 开关
            prompt = build_prompt(
                uncovered_code_line, 
                self.good_seeds, 
                scala_code_line,
                compile_error=compile_error_info,
                no_coverage_count=consecutive_no_coverage,
                agent_memory=self.agent_memory,
                module_name=self.module_name,  # 传入模块名用于 spec 分析
                use_spec=self.use_spec  # 是否启用 spec 分析
            )

            # 调用 LLM
            start_time = time.time()
            print(f"📌 [阶段] LLM 开始生成 case（可能需数分钟），请勿中断...")
            print(f"📌 [阶段] 等待 LLM 生成用例（约需数分钟），请稍候...")
            print(f"🤖 正在调用 LLM ({self.model})...")
            
            # 统计 LLM 生成次数
            self.statistics["llm_generation_count"] += 1
            
            # 每5次LLM调用保存一次统计数据（实时更新）
            if save_stats_callback and self.statistics["llm_generation_count"] % 5 == 0:
                try:
                    save_stats_callback()
                except Exception as e:
                    print(f"⚠️ 保存统计数据时出错: {e}")
            
            # LLM 调用：失败时重试 1 次，仍失败则跳过本 case，避免长时间卡死整轮
            result = None
            for llm_attempt in range(2):
                try:
                    if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                        result = callOpenAI_KJY(prompt, self.model)
                    else:
                        result = callOpenAI(prompt)
                    break
                except Exception as e:
                    print(f"❌ LLM 调用失败 (尝试 {llm_attempt + 1}/2): {e}")
                    if llm_attempt == 0:
                        print(f"   将重试一次...")
                    else:
                        print(f"   跳过本 case，继续下一轮迭代（避免长时间卡死）")
                        self.fail_num += 1
                        compile_error_info = None
            if result is None:
                continue
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"⏱️ LLM 响应时间: {elapsed_time:.2f} 秒")
            
            # 保存 LLM 输出用于调试
            debug_dir = "/root/ChipFuzzer/LLMoutput"
            os.makedirs(debug_dir, exist_ok=True)
            
            debug_path = os.path.join(
                debug_dir,
                f"llm_result_{self.module_name}_{int(time.time())}.txt"
            )

            if isinstance(result, str):
                debug_text = result
            else:
                try:
                    debug_text = json.dumps(result, ensure_ascii=False, indent=2)
                except Exception:
                    debug_text = str(result)
    
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(debug_text)
    
            print(f"💾 LLM 原始输出已保存: {debug_path}")

            # 解析 LLM 输出
            parser = AssemblyCodeParser(self.module_name, self.config)
            parsed_ok = parser.parse_from_llm_output(result)
            if not parsed_ok:
                print("⚠️ LLM 输出中未找到有效的汇编代码块，跳过")
                self.fail_num += 1
                compile_error_info = None
                continue
            
            # 获取解析后的汇编代码并验证
            raw_asm_code = parser.generate_clean_assembly()
            
            print("🔍 正在验证汇编代码...")
            is_valid, validation_errors = validate_asm(raw_asm_code)
            
            if not is_valid:
                print(f"⚠️ 汇编代码验证发现 {len(validation_errors)} 个问题:")
                for err in validation_errors[:5]:
                    print(f"   - {err}")
                
                # 尝试自动修复
                print("🔧 正在尝试自动修复...")
                fixed_code, fixes_applied = fix_asm(raw_asm_code)
                
                if fixes_applied:
                    print(f"✅ 已应用 {len(fixes_applied)} 个修复:")
                    for fix in fixes_applied[:5]:
                        print(f"   - {fix}")
                    
                    # 使用修复后的代码重新解析
                    parser.sections = {}
                    parser.instructions = []
                    parser._parse_assembly_code(fixed_code)

            # 保存汇编文件
            asm_file_name = parser.save_to_file()
            elf_file_name = asm_file_name.split(".")[0] + ".bin"
            print(f"📄 生成的文件: {asm_file_name}")

            # 编译与仿真
            print(f"📌 [阶段] 开始对当前 case 进行编译与仿真（大模型生成的 case）")
            print(f"📌 [阶段] 正在编译...")
            compiler_dir = self.config.testcase_dir
            compiler_cmd = f"sh complier.sh {asm_file_name}"
            compile_result = self.subproc.run(compiler_dir, compiler_cmd)

            if compile_result is None or compile_result.stderr:
                error_msg = compile_result.stderr if compile_result else "编译超时"
                print(f"❌ 编译失败:\n{error_msg[:500]}")
                print("验证流程: 编译失败")
                
                consecutive_compile_errors += 1
                self.fail_num += 1
                
                # 记录失败的交互
                self.agent_memory.record_interaction(
                    uncovered_code=uncovered_code_line,
                    prompt_type="generate",
                    asm_code=raw_asm_code,
                    success=False,
                    compile_success=False,
                    coverage_improved=False,
                    error_message=error_msg,
                    strategy=f"failed_iteration_{iteration_count}"
                )
                
                # 保存当前代码用于修复
                last_asm_code = raw_asm_code
                
                # 尝试修复模式
                if fix_attempt_count < MAX_FIX_ATTEMPTS:
                    fix_attempt_count += 1
                    print(f"🔧 启动修复模式（第 {fix_attempt_count}/{MAX_FIX_ATTEMPTS} 次修复尝试）...")
                    print(f"📌 [阶段] LLM 开始修复编译失败的 case（可能需数分钟），请勿中断...")
                    print(f"📌 [阶段] 等待 LLM 修复代码（约需数分钟），请稍候...")
                    
                    # 生成修复 prompt
                    uncovered_code_line, _ = self._select_uncovered_batch()
                    fix_prompt = build_fix_prompt(raw_asm_code, error_msg, uncovered_code_line)
                    
                    # 调用 LLM 进行修复（添加超时和异常处理）
                    print(f"🤖 正在调用 LLM 修复代码...")
                    try:
                        import signal
                        
                        # 设置超时（5分钟）
                        def timeout_handler(signum, frame):
                            raise TimeoutError("LLM 修复调用超时（5分钟）")
                        
                        # 使用信号超时（仅限 Unix 系统）
                        if hasattr(signal, 'SIGALRM'):
                            signal.signal(signal.SIGALRM, timeout_handler)
                            signal.alarm(300)  # 5分钟超时
                        
                        try:
                            if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                                fix_result = callOpenAI_KJY(fix_prompt, self.model)
                            else:
                                fix_result = callOpenAI(fix_prompt)
                        finally:
                            # 取消超时
                            if hasattr(signal, 'SIGALRM'):
                                signal.alarm(0)
                    except TimeoutError as e:
                        print(f"❌ LLM 修复调用超时: {e}")
                        print(f"   跳过本次修复尝试，继续下一次迭代")
                        fix_attempt_count -= 1  # 回退计数，因为这次没有真正尝试
                        compile_error_info = error_msg
                        continue
                    except Exception as e:
                        print(f"❌ LLM 修复调用失败: {e}")
                        print(f"   跳过本次修复尝试，继续下一次迭代")
                        import traceback
                        traceback.print_exc()
                        fix_attempt_count -= 1  # 回退计数，因为这次没有真正尝试
                        compile_error_info = error_msg
                        continue
                    
                    # 解析修复后的代码
                    fix_parser = AssemblyCodeParser(self.module_name, self.config)
                    if fix_parser.parse_from_llm_output(fix_result):
                        fixed_code = fix_parser.generate_clean_assembly()
                        
                        # 验证修复后的代码
                        is_valid, _ = validate_asm(fixed_code)
                        if not is_valid:
                            fixed_code, _ = fix_asm(fixed_code)
                        
                        # 保存并编译修复后的代码
                        asm_file_name = fix_parser.save_to_file()
                        elf_file_name = asm_file_name.split(".")[0] + ".bin"
                        print(f"📄 修复后的文件: {asm_file_name}")
                        
                        compile_result = self.subproc.run(compiler_dir, f"sh complier.sh {asm_file_name}")
                        
                        if compile_result and not compile_result.stderr:
                            print("✅ 修复后编译成功！")
                            print("验证流程: 编译成功")
                            compile_error_info = None
                            consecutive_compile_errors = 0
                            fix_attempt_count = 0
                            
                            # 记录修复成功的交互
                            self.agent_memory.record_interaction(
                                uncovered_code=uncovered_code_line,
                                prompt_type="fix",
                                asm_code=fixed_code,
                                success=False,  # 暂时，等覆盖率结果
                                compile_success=True,
                                coverage_improved=False,
                                strategy=f"fix_attempt_{fix_attempt_count}"
                            )
                            
                            # 继续执行模拟器（不要 continue）
                            print(f"📌 [阶段] 正在启动仿真（约需数秒），请稍候...")
                            elf_rel_path = f"testcase/{elf_file_name}"
                            dat_file, ok = self.emulator.run_elf(elf_rel_path)
                            if ok and dat_file:
                                print("验证流程: 仿真成功")
                                # 统计模拟器成功执行次数
                                self.statistics["emulator_success_count"] += 1
                                
                                covered_lines = self._apply_coverage_dat(dat_file, from_good_seed=True)
                                self._handle_success_seed_if_any(
                                    covered_lines=covered_lines,
                                    asm_file_name=asm_file_name,
                                    elf_file_name=elf_file_name
                                )
                                
                                # 记录覆盖率数据（修复模式）
                                try:
                                    coverage_info = self.global_coverage_manager.get_total_coverage_from_genhtml()
                                    if coverage_info and "coverage_percentage" in coverage_info:
                                        current_coverage = coverage_info["coverage_percentage"]
                                        if self.statistics["coverage_data"]:
                                            last_pct = self.statistics["coverage_data"][-1].get("coverage_percentage", 0) or 0
                                            current_coverage = max(current_coverage, last_pct)
                                        uncovered_count = self.global_coverage_manager.baseline_uncovered_count
                                        self.statistics["coverage_data"].append({
                                            "timestamp": time.time(),
                                            "coverage_percentage": current_coverage,
                                            "uncovered_lines": uncovered_count,
                                            "iteration": iteration_count,
                                            "module": self.module_name,
                                        })
                                except Exception as e:
                                    pass
                                
                                # 每次更新后立即保存统计数据
                                if save_stats_callback:
                                    try:
                                        save_stats_callback()
                                    except Exception as e:
                                        print(f"⚠️ 保存统计数据时出错: {e}")
                                
                                global_improved = getattr(self, '_last_global_improved', False)
                                if global_improved or bool(covered_lines):
                                    print("🎉 修复后的代码成功覆盖了新代码！")
                                    self.global_coverage_manager.print_total_coverage("更新后总覆盖率")
                                    
                                    # 更新记忆为成功
                                    if self.agent_memory.history:
                                        last_entry = self.agent_memory.history[-1]
                                        if fixed_code[:100] in last_entry.asm_code:
                                            last_entry.success = True
                                            last_entry.coverage_improved = True
                                            last_entry.coverage_lines = covered_lines
                                    
                                    self.fail_num = 0
                                    consecutive_no_coverage = 0
                                else:
                                    print("验证流程: 无新覆盖")
                                    print("验证流程: 没有覆盖成功")
                                    print(f"验证流程: 无覆盖用例: {asm_file_name}")
                                    consecutive_no_coverage += 1
                            else:
                                print("验证流程: 仿真失败")
                            continue
                        else:
                            print(f"❌ 修复后仍然编译失败")
                            print("验证流程: 编译失败")
                            compile_error_info = compile_result.stderr if compile_result else "编译超时"
                    else:
                        print("⚠️ 无法解析修复后的代码")
                    
                    continue
                
                # 修复尝试用完，重置状态
                fix_attempt_count = 0
                compile_error_info = error_msg
                
                # 如果连续编译错误太多，清除错误信息重新开始
                # 但保留最后一次错误信息，因为可能包含有用的提示
                if consecutive_compile_errors >= 5:
                    print("⚠️ 连续编译错误过多（5次），清除错误信息重新尝试")
                    print("   提示：如果问题持续，可能需要检查 LLM 输出格式或汇编语法")
                    compile_error_info = None
                    consecutive_compile_errors = 0
                    fix_attempt_count = 0  # 重置修复计数
                
                continue
            else:
                compile_error_info = None
                consecutive_compile_errors = 0
                fix_attempt_count = 0
                print("✅ 编译成功")
                print("验证流程: 编译成功")
                
                # 记录编译成功（但还未知道覆盖率结果）
                self.agent_memory.record_interaction(
                    uncovered_code=uncovered_code_line,
                    prompt_type="generate",
                    asm_code=raw_asm_code,
                    success=False,  # 暂时为 False，等覆盖率结果出来再更新
                    compile_success=True,
                    coverage_improved=False,
                    strategy=f"iteration_{iteration_count}"
                )

            # 运行模拟器
            print(f"📌 [阶段] 正在启动仿真（约需数秒），请稍候...")
            elf_rel_path = f"testcase/{elf_file_name}"
            dat_file, ok = self.emulator.run_elf(elf_rel_path)
            if not ok or not dat_file:
                print("⚠️ 模拟器运行失败，跳过本次结果")
                print("验证流程: 仿真失败")
                self.fail_num += 1
                continue
            
            print("验证流程: 仿真成功")
            # 统计模拟器成功执行次数
            self.statistics["emulator_success_count"] += 1

            # 应用 coverage.dat
            covered_lines = self._apply_coverage_dat(dat_file, from_good_seed=True)

            # 如果全局未覆盖行数减少，说明这次是“好种子”，做额外记录
            # UncoveredCodeRepository.update_after_coverage 中已经打印成功信息
            # 这里再做种子保存
            self._handle_success_seed_if_any(
                covered_lines=covered_lines,
                asm_file_name=asm_file_name,
                elf_file_name=elf_file_name
            )

            # 获取全局覆盖率提升信息
            global_improved = getattr(self, '_last_global_improved', False)
            
            # 判断是否有覆盖率提升：全局提升 或 当前模块提升
            has_improvement = global_improved or bool(covered_lines)
            
            # 记录覆盖率数据（每次模拟器成功执行后都记录）
            try:
                coverage_info = self.global_coverage_manager.get_total_coverage_from_genhtml()
                if coverage_info and "coverage_percentage" in coverage_info:
                    current_coverage = coverage_info["coverage_percentage"]
                    # 保证单调不降：若因缓存/重启等出现比上一点低则用上一点，避免图表“先升后降”
                    if self.statistics["coverage_data"]:
                        last_pct = self.statistics["coverage_data"][-1].get("coverage_percentage", 0) or 0
                        current_coverage = max(current_coverage, last_pct)
                    uncovered_count = self.global_coverage_manager.baseline_uncovered_count
                    
                    self.statistics["coverage_data"].append({
                        "timestamp": time.time(),
                        "coverage_percentage": current_coverage,
                        "uncovered_lines": uncovered_count,
                        "iteration": iteration_count,
                        "module": self.module_name,
                    })
                    
                    # 每次更新覆盖率数据后立即保存统计数据（实时更新）
                    if save_stats_callback:
                        try:
                            save_stats_callback()
                        except Exception as e:
                            print(f"⚠️ 保存统计数据时出错: {e}")
            except Exception as e:
                # 如果获取覆盖率失败，不影响主流程
                pass
            
            if has_improvement:
                print("🎉 检测到覆盖率提升！")
                # 全局覆盖率已经在 _apply_coverage_dat -> check_global_improvement 中更新了
                # 这里不需要再重复执行 verilator_coverage 命令
                # 因为 GlobalCoverageManager.check_global_improvement 已经做了以下操作：
                # 1. 合并 .dat 文件到 sum_gj.dat
                # 2. 更新 annotated 报告
                # 3. 更新 coverage.info
                
                # 显示更新后的总覆盖率
                self.global_coverage_manager.print_total_coverage("更新后总覆盖率")
                
                # 记录成功的交互（更新之前的记录）
                # 找到最近的记录并更新
                if self.agent_memory.history:
                    last_entry = self.agent_memory.history[-1]
                    if last_entry.asm_code[:100] == raw_asm_code[:100]:  # 匹配最近的记录
                        # 更新为成功
                        last_entry.success = True
                        last_entry.coverage_improved = True
                        last_entry.coverage_lines = covered_lines
                        last_entry.strategy = f"successful_iteration_{iteration_count}"
                
                self.fail_num = 0  # 重置失败计数
                consecutive_no_coverage = 0  # 重置无覆盖计数
                last_asm_code = None
            else:
                print("ℹ️  本次测试没有新的代码被覆盖（包括全局）")
                print("验证流程: 无新覆盖")
                print("验证流程: 没有覆盖成功")
                print(f"验证流程: 无覆盖用例: {asm_file_name}")
                self.fail_num += 1
                consecutive_no_coverage += 1
                
                # 更新记忆：编译成功但未提升覆盖率
                if self.agent_memory.history:
                    last_entry = self.agent_memory.history[-1]
                    if last_entry.asm_code[:100] == raw_asm_code[:100]:
                        last_entry.success = False  # 虽然编译成功，但未提升覆盖率
                        last_entry.coverage_improved = False
                
                # 如果连续多次没有覆盖新代码，触发分析模式
                if consecutive_no_coverage >= 3 and consecutive_no_coverage % 3 == 0:
                    print(f"🔍 连续 {consecutive_no_coverage} 次无新覆盖，启动分析模式...")
                    print(f"📌 [阶段] LLM 开始分析无覆盖原因并生成改进代码（可能需数分钟），请勿中断...")
                    print(f"📌 [阶段] 等待 LLM 分析原因并生成改进代码（约需数分钟），请稍候...")

                    uncovered_code_line, _ = self._select_uncovered_batch()
                    analysis_prompt = build_analysis_prompt(
                        raw_asm_code,
                        uncovered_code_line,
                        f"连续 {consecutive_no_coverage} 次执行成功但未覆盖新代码"
                    )
                    
                    print(f"🤖 正在调用 LLM 分析原因并生成改进代码...")
                    try:
                        if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                            analysis_result = callOpenAI_KJY(analysis_prompt, self.model)
                        else:
                            analysis_result = callOpenAI(analysis_prompt)
                    except Exception as e:
                        print(f"❌ LLM 分析调用失败: {e}，跳过分析，继续下一轮（避免卡死）")
                        analysis_result = None
                    if analysis_result is not None:
                        # 保存分析结果用于下次参考
                        analysis_dir = "/root/ChipFuzzer_cursor/analysis_log"
                        os.makedirs(analysis_dir, exist_ok=True)
                        analysis_path = os.path.join(
                            analysis_dir,
                            f"analysis_{self.module_name}_{int(time.time())}.txt"
                        )
                        with open(analysis_path, "w", encoding="utf-8") as f:
                            f.write(f"模块: {self.module_name}\n")
                            f.write(f"连续无覆盖次数: {consecutive_no_coverage}\n")
                            f.write(f"目标代码:\n{uncovered_code_line[:500]}\n")
                            f.write(f"LLM 分析:\n{analysis_result}\n")
                        self.agent_memory.record_interaction(
                            uncovered_code=uncovered_code_line,
                            prompt_type="analysis",
                            asm_code=raw_asm_code,
                            success=False,
                            compile_success=True,
                            coverage_improved=False,
                            strategy=f"analysis_mode_iteration_{iteration_count}",
                            feedback=str(analysis_result)[:500]
                        )
                        print(f"💾 分析结果已保存: {analysis_path}")
        
        # 循环正常结束（无未覆盖代码）
        print(f"\n🎉 模块 [{self.module_name}] 测试完成！所有代码已覆盖！")
        
        # 保存记忆
        self.agent_memory.finalize()
        
        return {
            "status": "completed",
            "iterations": iteration_count,
            "initial_uncovered": initial_uncovered_count,
            "final_uncovered": 0,
            "covered_count": initial_uncovered_count,
            "initial_lines": initial_uncovered_lines,
            "final_lines": [],
        }
                
         
    def _handle_success_seed_if_any(self, covered_lines, asm_file_name, elf_file_name):
        """
        根据全局覆盖率是否提升来决定是否记录为 good seed.
        优先使用全局覆盖率提升作为判断依据，而不仅仅是当前模块的覆盖。
        """
        success_dir = os.path.join(self.config.success_root, self.module_name)
        os.makedirs(success_dir, exist_ok=True)
        os.makedirs(self.config.all_seed_dir, exist_ok=True)

        testcase_asm_path = os.path.join(self.config.testcase_dir, asm_file_name)
        testcase_elf_path = os.path.join(self.config.testcase_dir, elf_file_name)

        assembly_code = read_assembly_file(testcase_asm_path)
        
        GJ_SUCCESS_SEED_DIR = "/root/ChipFuzzer_cursor/GJ_Success_Seed"
        os.makedirs(GJ_SUCCESS_SEED_DIR, exist_ok=True)
        
        # 获取全局覆盖率提升信息
        global_improved = getattr(self, '_last_global_improved', False)
        global_reduced = getattr(self, '_last_global_reduced', 0)
        global_newly_covered = getattr(self, '_last_global_newly_covered', [])
        
        # 判断是否应该保存：全局覆盖率提升 或 当前模块有覆盖新行
        should_save = global_improved or bool(covered_lines)
        
        if should_save and assembly_code:
            # 1) 保存到 GJ_Success_Seed 目录（关键保存位置）
            # 保存 .S 文件
            with open(os.path.join(GJ_SUCCESS_SEED_DIR, asm_file_name), 'w') as f:
                f.write(assembly_code)
            print(f"✅ 成功案例已保存到 GJ_Success_Seed: {asm_file_name}")
            
            # 保存 .bin 文件到 GJ_Success_Seed
            bin_file_name = asm_file_name.replace(".S", ".bin")
            testcase_bin_path = os.path.join(self.config.testcase_dir, bin_file_name)
            if os.path.exists(testcase_bin_path):
                shutil.copy(testcase_bin_path, os.path.join(GJ_SUCCESS_SEED_DIR, bin_file_name))
                print(f"✅ BIN 文件已保存到 GJ_Success_Seed: {bin_file_name}")
            
            # 生成并保存报告文件（仅当启用 --llm-report 时）
            if self.use_llm_report:
                self._generate_case_report(
                    case_name=asm_file_name.replace(".S", ""),
                    module_name=self.module_name,
                    global_improved=global_improved,
                    global_reduced=global_reduced,
                    global_newly_covered=global_newly_covered,
                    covered_lines=covered_lines,
                    output_dir=GJ_SUCCESS_SEED_DIR
                )
            
            # 2) 保存到 all_seed_dir
            with open(os.path.join(self.config.all_seed_dir, asm_file_name), 'w') as f:
                f.write(assembly_code)
            
            # 3) 复制 elf 到 success_dir
            if os.path.exists(testcase_elf_path):
                shutil.copy(testcase_elf_path, os.path.join(success_dir, elf_file_name))
                print(f"✅ ELF 文件已保存到: {os.path.join(success_dir, elf_file_name)}")
            
            # 4) 添加到 good_seeds 内存列表，并统计成功覆盖的 case 数
            self.good_seeds.append(assembly_code)
            self.statistics["coverage_improved_count"] = self.statistics.get("coverage_improved_count", 0) + 1
            print(f"当前参考案例数: {len(self.good_seeds)}")
            
            # 5) 保存到模块专属 success_dir
            with open(os.path.join(success_dir, asm_file_name), 'w') as f:
                f.write(assembly_code)
            
            print(f"✅ 汇编代码已保存到: {os.path.join(self.config.all_seed_dir, asm_file_name)}")

        # 打印覆盖情况（仅输出：当前覆盖率、本次多覆盖行数、测试用例名+多覆盖行数）
        if global_improved:
            cov = self.global_coverage_manager.get_total_coverage_from_genhtml(use_cache=True)
            pct = cov.get("coverage_percentage", 0) or 0
            print(f"📊 当前覆盖率: {pct:.2f}%")
            print(f"📊 本次多覆盖: {global_reduced} 行代码")
            print(f"✅ 测试用例: {asm_file_name}，多覆盖 {global_reduced} 行代码")
            print("验证流程: 覆盖成功")
        
        if covered_lines and not global_improved:
            print(f"📦 当前模块覆盖了 {len(covered_lines)} 行代码")

    def _analyze_covered_modules(self, covered_lines: list) -> dict:
        """
        使用 LLM 分析覆盖的代码行，确定主要覆盖的模块和功能
        
        参数:
            covered_lines: 覆盖的代码行列表（字符串列表）
            
        返回:
            {
                "main_module": "模块名",
                "module_distribution": {"模块名": 行数},
                "main_function": "功能描述"
            }
        """
        if not covered_lines:
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}
        
        # 限制分析范围，只取前 30 行作为样本（避免 prompt 太长）
        lines_to_analyze = covered_lines[:30]
        
        # 清理代码行：移除覆盖率标记和路径信息
        cleaned_lines = []
        for line in lines_to_analyze:
            # 移除覆盖率标记 %000000
            clean_line = re.sub(r'%\d{6}\s*', '', str(line)).strip()
            # 移除路径信息 @[xxx:yy]
            clean_line = re.sub(r'@\[[^\]]+\]\s*', '', clean_line).strip()
            if clean_line and len(clean_line) > 5:
                cleaned_lines.append(clean_line)
        
        if not cleaned_lines:
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}
        
        # 构造 prompt，让 LLM 分析代码
        code_sample = "\n".join(cleaned_lines[:20])  # 最多 20 行
        
        prompt = f"""请分析以下 SystemVerilog 代码片段，判断这些代码主要属于哪个模块，以及实现了什么功能。

代码片段：
{code_sample}

请以 JSON 格式返回分析结果，格式如下：
{{
    "main_module": "模块名称（如 Bku, L2Cache, DecodeUnit 等）",
    "main_function": "功能描述（简洁描述，如：寄存器写回、缓存查找、分支预测等）"
}}

只返回 JSON，不要其他解释。如果无法确定，模块名返回"未知"，功能描述返回"未知"。"""

        try:
            # 调用 LLM 分析
            llm_response = callOpenAI_KJY(prompt, self.model)
            
            # 尝试从响应中提取 JSON
            # 移除可能的 markdown 代码块标记
            llm_response = re.sub(r'```json\s*', '', llm_response)
            llm_response = re.sub(r'```\s*', '', llm_response).strip()
            
            # 尝试解析 JSON
            result = json.loads(llm_response)
            
            main_module = result.get("main_module", "未知")
            main_function = result.get("main_function", "未知")
            
            # 构建返回结果
            module_distribution = {}
            if main_module != "未知":
                module_distribution[main_module] = len(cleaned_lines)
            
            return {
                "main_module": main_module,
                "module_distribution": module_distribution,
                "main_function": main_function
            }
            
        except Exception as e:
            # 如果 LLM 调用失败或解析失败，返回默认值
            print(f"⚠️ LLM 分析覆盖代码失败: {e}")
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}
    
    def _generate_case_report(self, case_name: str, module_name: str, global_improved: bool,
                              global_reduced: int, global_newly_covered: list, covered_lines: list,
                              output_dir: str):
        """
        生成测试用例报告文件
        
        参数:
            case_name: 用例名称（不含扩展名）
            module_name: 测试的目标模块名（不一定是主要覆盖的模块）
            global_improved: 是否全局覆盖率提升
            global_reduced: 全局未覆盖行数减少量
            global_newly_covered: 新覆盖的代码行列表（全局）
            covered_lines: 当前模块覆盖的代码行列表
            output_dir: 输出目录
        """
        report_file = os.path.join(output_dir, f"{case_name}.txt")
        
        # 分析实际覆盖的模块和功能（仅在启用 --llm-report 时才会调用此函数）
        # 优先使用 global_newly_covered（全局新覆盖的代码），如果没有则使用 covered_lines
        lines_to_analyze = global_newly_covered if global_newly_covered else covered_lines
        if lines_to_analyze:
            analysis = self._analyze_covered_modules(lines_to_analyze)
        else:
            analysis = {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}
        
        main_covered_module = analysis["main_module"]
        module_dist = analysis["module_distribution"]
        main_function = analysis["main_function"]
        
        # 构建报告内容（三句话左右）
        report_lines = []
        
        # 第一句：主要覆盖的模块
        if main_covered_module != "未知":
            report_lines.append(f"本测试用例主要覆盖了 {main_covered_module} 模块。")
        else:
            report_lines.append(f"本测试用例主要覆盖了 {module_name} 模块。")
        
        # 第二句：覆盖的代码实现了什么功能
        if main_function != "未知":
            if global_improved and global_reduced > 0:
                report_lines.append(f"覆盖的代码主要实现了 {main_function} 功能，成功提升了全局代码覆盖率，减少了 {global_reduced} 行未覆盖代码。")
            elif global_improved:
                report_lines.append(f"覆盖的代码主要实现了 {main_function} 功能，成功提升了全局代码覆盖率。")
            elif lines_to_analyze:
                covered_count = len(lines_to_analyze)
                report_lines.append(f"覆盖的代码主要实现了 {main_function} 功能，共覆盖了 {covered_count} 行代码。")
            else:
                report_lines.append(f"覆盖的代码主要实现了 {main_function} 功能。")
        else:
            if global_improved and global_reduced > 0:
                report_lines.append(f"该用例成功提升了全局代码覆盖率，减少了 {global_reduced} 行未覆盖代码。")
            elif global_improved:
                report_lines.append(f"该用例成功提升了全局代码覆盖率。")
            elif lines_to_analyze:
                covered_count = len(lines_to_analyze)
                report_lines.append(f"该用例覆盖了 {covered_count} 行之前未覆盖的代码。")
            else:
                report_lines.append(f"该用例成功执行并产生了有效的覆盖率数据。")
        
        # 第三句：模块分布或代码示例
        if len(module_dist) > 1:
            # 显示前2-3个主要模块
            sorted_modules = sorted(module_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            module_names = [f"{name}({count}行)" for name, count in sorted_modules]
            if len(module_dist) > 3:
                report_lines.append(f"覆盖的模块包括：{', '.join(module_names)} 等。")
            else:
                report_lines.append(f"覆盖的模块包括：{', '.join(module_names)}。")
        elif lines_to_analyze and len(lines_to_analyze) <= 5:
            # 只有少量代码行，显示示例
            sample_lines = lines_to_analyze[:2]
            sample_text = "、".join([re.sub(r'%\d{6}\s*', '', line).strip()[:40] + "..." if len(line) > 40 else re.sub(r'%\d{6}\s*', '', line).strip() for line in sample_lines])
            if len(lines_to_analyze) > 2:
                report_lines.append(f"覆盖的代码包括：{sample_text} 等。")
            else:
                report_lines.append(f"覆盖的代码包括：{sample_text}。")
        else:
            # 默认描述
            if global_improved:
                report_lines.append(f"该用例通过执行特定的指令序列触发了关键代码路径，有效提升了代码覆盖率。")
            else:
                report_lines.append(f"该用例通过执行特定的指令序列触发了目标模块的关键代码路径。")
        
        # 写入报告文件
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(report_lines))
            print(f"✅ 用例报告已保存: {report_file}")
        except Exception as e:
            print(f"⚠️ 保存用例报告失败: {e}")


# =========================
# main 入口
# =========================




def parse_arguments():
    parser = argparse.ArgumentParser(description='代码覆盖测试工具')
    parser.add_argument(
        '--coverage_filename_origin',
        type=str,
        default="/root/XiangShan/logs_testcase/annotated/",
        #required=True,
        help='The path to the original coverage file (Coverage_filename_origin).'
    )
    
    parser.add_argument(
        '--coverage_filename_later',
        type=str,
        default="/root/XiangShan/logs2/annotated/",
        #required=True,
        help='The path to the later coverage file (Coverage_filename_later).'
    )
    
    parser.add_argument(
        '--global_annotated_dir',
        type=str,
        default="/root/XiangShan/logs_global/annotated",
        help='全局覆盖率统计使用的 annotated 目录'
    )
    
    parser.add_argument(
        '--module',
        type=str,
        default="CSR",
       # required=True,
        help='目标/起始模块。开启 auto_switch 时表示从此模块开始验证；若指定了 --start-index 则以此序号为准'
    )
    parser.add_argument(
        '--start-index',
        type=int,
        default=None,
        metavar='N',
        help='从第 N 个模块开始验证（1=第一个）。与 auto_switch 配合：执行时先取前 num 个模块列表，从第 N 个开始往后验证，前面跳过'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default="KJY",
       # required=True,
        help='target module'
    )

    parser.add_argument(
        '--num',
        type=int,
        default=100,
        help='模块索引或自动模式下的模块数量（默认 100）'
    )
    
    parser.add_argument(
        '--dat',
        type=str,
        required=False,
        help='任务专属的 .dat 文件路径'
    )
    
    parser.add_argument(
        '--mode',
        type=str,
        choices=['continue', 'fresh'],
        default='continue',
        help='运行模式: continue=继续使用现有覆盖率文件, fresh=创建新的覆盖率文件'
    )
    
    parser.add_argument(
        '--max_iterations',
        type=int,
        default=13,
        help='每个模块的最大尝试次数（默认 13 次），达到后自动切换到下一个模块'
    )
    
    parser.add_argument(
        '--auto_switch',
        action='store_true',
        default=False,  # store_true 的 default 应该是 False
        help='启用自动切换模块模式：当前模块完成或达到最大次数后自动切换到下一个模块（默认开启，除非显式禁用）'
    )
    
    parser.add_argument(
        '--no-auto-switch',
        action='store_false',
        dest='auto_switch',
        help='禁用自动切换模块模式（默认是开启的）'
    )
    
    parser.add_argument(
        '--use_spec',
        action='store_true',
        default=False,
        help='启用 SPEC 文件分析：使用 spec 文件中的模块接口信息来指导测试生成'
    )
    
    parser.add_argument(
        '--run_existing_seeds',
        action='store_true',
        default=False,
        help='运行已有的成功用例：在开始 LLM 生成之前，先运行 successed/<module>/ 目录下的已有成功用例（默认：fresh 模式运行，continue 模式跳过）'
    )

    parser.add_argument(
        '--llm-report',
        action='store_true',
        default=False,
        help='启用 LLM 生成用例报告：成功用例保存时调用大模型分析覆盖代码并生成报告（默认不写报告）'
    )

    return parser.parse_args()




def write_module_report(report_file: str, module_name: str, result: dict, start_time: str, end_time: str):
    """将模块测试报告写入日志文件"""
    with open(report_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"模块测试报告: {module_name}\n")
        f.write(f"{'='*80}\n")
        f.write(f"开始时间: {start_time}\n")
        f.write(f"结束时间: {end_time}\n")
        f.write(f"完成状态: {result['status']}\n")
        f.write(f"执行次数: {result['iterations']}\n")
        f.write(f"初始未覆盖行数: {result['initial_uncovered']}\n")
        f.write(f"最终未覆盖行数: {result['final_uncovered']}\n")
        f.write(f"本次覆盖行数: {result['covered_count']}\n")
        f.write(f"\n--- 初始未覆盖代码行 ({result['initial_uncovered']} 行) ---\n")
        for line in result.get('initial_lines', [])[:50]:  # 最多显示 50 行
            f.write(f"  {line}\n")
        if result['initial_uncovered'] > 50:
            f.write(f"  ... 还有 {result['initial_uncovered'] - 50} 行\n")
        f.write(f"\n--- 最终未覆盖代码行 ({result['final_uncovered']} 行) ---\n")
        for line in result.get('final_lines', [])[:50]:
            f.write(f"  {line}\n")
        if result['final_uncovered'] > 50:
            f.write(f"  ... 还有 {result['final_uncovered'] - 50} 行\n")
        f.write(f"{'='*80}\n\n")


def main():
    args = parse_arguments()
    num = args.num
    model = args.model
    run_mode = args.mode
    new_dat_file = args.dat
    
    # 创建配置，更新全局 annotated 目录
    config = PathConfig()
    config.global_annotated_dir = args.global_annotated_dir
    
    # 获取模块列表（可以是单个模块或多个模块）
    # 如果指定了 --module，则只测试该模块
    # 否则根据 --num 获取未覆盖代码最多的模块列表
    # auto_switch 默认开启（除非显式指定 --no-auto-switch）
    # 如果开启了 auto_switch，即使指定了单个模块，也会在完成后自动切换到下一个模块
    
    # 默认启用 auto_switch（如果用户没有显式指定 --no-auto-switch）
    # 由于 argparse 的 store_true/store_false 机制：
    # - 如果用户指定了 --auto_switch，args.auto_switch = True
    # - 如果用户指定了 --no-auto-switch，args.auto_switch = False
    # - 如果用户都没有指定，args.auto_switch = False（store_true 的默认值）
    # 我们需要默认启用，所以检查 sys.argv 来判断用户是否显式指定了 --no-auto-switch
    import sys
    if '--no-auto-switch' not in sys.argv and '--auto_switch' not in sys.argv:
        # 用户既没有显式启用也没有显式禁用，默认启用
        args.auto_switch = True
        print(f"ℹ️  自动切换模块模式：默认启用（如需禁用，请使用 --no-auto-switch）")
    
    # 优先支持「起始序号」：只填数字 N，从第 N 个模块开始（避免前端拉百条下拉）
    if getattr(args, 'start_index', None) is not None and args.start_index >= 1:
        all_modules = getTopUncoveredModules(num, args.coverage_filename_origin)
        start_idx = min(args.start_index - 1, len(all_modules))  # 1-based -> 0-based
        module_list = all_modules[start_idx:]
        print(f"🔄 从第 {args.start_index} 个模块开始验证，共 {len(module_list)} 个模块（前 {start_idx} 个已跳过）")
    elif args.module and args.module != "auto":
        # 单模块模式
        if args.auto_switch:
            all_modules = getTopUncoveredModules(num, args.coverage_filename_origin)
            if args.module in all_modules:
                start_idx = all_modules.index(args.module)
                module_list = all_modules[start_idx:]
            else:
                module_list = [args.module] + all_modules
            print(f"🔄 自动切换模式：将从模块 {args.module} 开始，共 {len(module_list)} 个模块")
        else:
            module_list = [args.module]
    else:
        module_list = getTopUncoveredModules(num, args.coverage_filename_origin)
    
    # 每模块最大尝试次数
    max_iterations_per_module = args.max_iterations
    
    print(f"=" * 60)
    print(f"🚀 启动 ChipFuzzer 覆盖率提升工具")
    print(f"   待测模块列表: {module_list}")
    print(f"   每模块最大尝试次数: {max_iterations_per_module}")
    print(f"   使用模型: {model}")
    print(f"   运行模式: {run_mode} ({'继续累积覆盖率' if run_mode == 'continue' else '创建新的覆盖率文件'})")
    print(f"   SPEC 文件分析: {'启用' if args.use_spec else '禁用'}")
    print(f"   LLM 用例报告: {'启用' if args.llm_report else '不写报告（默认）'}")
    print(f"   全局 annotated 目录: {config.global_annotated_dir}")
    print(f"   累积覆盖率文件: {config.sum_dat_file}")
    print(f"=" * 60)
    
    # 创建报告文件
    report_file = f"/root/ChipFuzzer_cursor/GJ_log/module_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"ChipFuzzer 多模块测试报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"模块列表: {module_list}\n")
        f.write(f"运行模式: {run_mode}\n")
        f.write(f"每模块最大尝试次数: {max_iterations_per_module}\n")
        f.write(f"\n")
    
    # 创建全局覆盖率管理器（所有模块共享同一个实例，确保基线一致）
    global_coverage_manager = GlobalCoverageManager(
        project_root=config.project_root,
        annotated_dir=config.global_annotated_dir,
        sum_dat_file=config.sum_dat_file
    )
    
    # 根据运行模式处理覆盖率文件
    if run_mode == 'fresh':
        print(f"\n⚠️  Fresh 模式：将重置覆盖率文件")
        global_coverage_manager.reset_coverage(backup=True)
        print(f"\n📊 Fresh 模式：初始覆盖率为 0%（从零开始）")
        global_coverage_manager.print_module_group_stats("L2")
        print()
    else:
        if os.path.exists(config.sum_dat_file):
            stat = os.stat(config.sum_dat_file)
            print(f"\n📂 Continue 模式：使用现有覆盖率文件")
            print(f"   文件大小: {stat.st_size / 1024:.1f} KB")
            print(f"   修改时间: {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            global_coverage_manager.print_total_coverage("初始总覆盖率")
        else:
            print(f"\n📂 Continue 模式：覆盖率文件不存在，将创建新文件")
        
        global_coverage_manager.print_module_group_stats("L2")
        print()
    
    # 多模块测试循环
    all_results = []
    
    # 初始化全局统计数据文件路径（用于实时保存）
    stats_file_path = f"/root/ChipFuzzer_cursor/GJ_log/statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # 全局字典：存储正在运行的模块的统计数据（用于实时保存）
    # 格式: {module_name: {"statistics": session.statistics, "module_name": module_name}}
    running_modules_stats = {}
    
    def save_statistics_realtime():
        """实时保存统计数据到JSON文件（包括已完成和正在运行的模块）"""
        try:
            all_statistics = {
                "run_id": new_dat_file.split("/")[-1].replace(".dat", "") if new_dat_file else "unknown",
                "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "modules": []
            }
            
            total_llm_count = 0
            total_emulator_success = 0
            total_coverage_improved = 0
            all_coverage_data = []
            
            # 1. 添加已完成的模块统计数据
            for r in all_results:
                if "statistics" in r:
                    stats = r["statistics"]
                    total_llm_count += stats.get("llm_generation_count", 0)
                    total_emulator_success += stats.get("emulator_success_count", 0)
                    total_coverage_improved += stats.get("coverage_improved_count", 0)
                    all_coverage_data.extend(stats.get("coverage_data", []))
                    
                    all_statistics["modules"].append({
                        "module_name": r["module_name"],
                        "statistics": stats
                    })
            
            # 2. 添加正在运行的模块统计数据（实时更新）
            for module_name, module_data in running_modules_stats.items():
                stats = module_data.get("statistics", {})
                total_llm_count += stats.get("llm_generation_count", 0)
                total_emulator_success += stats.get("emulator_success_count", 0)
                total_coverage_improved += stats.get("coverage_improved_count", 0)
                all_coverage_data.extend(stats.get("coverage_data", []))
                
                all_statistics["modules"].append({
                    "module_name": module_name,
                    "statistics": stats
                })
            
            all_statistics["summary"] = {
                "total_llm_generations": total_llm_count,
                "total_emulator_success": total_emulator_success,
                "total_coverage_improved": total_coverage_improved,
                "total_coverage_points": len(all_coverage_data)
            }
            
            # 保存到 JSON 文件（时间戳命名，便于历史）
            with open(stats_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_statistics, f, ensure_ascii=False, indent=2)
            
            # 同时按 run_id 写一份，便于统计 API 精确匹配当前任务，避免“成功覆盖 case 数”读错文件
            current_run_id = all_statistics.get("run_id", "")
            if current_run_id and current_run_id != "unknown":
                safe_run_id = current_run_id.replace("\\", "_").replace("/", "_").replace("..", "_").strip()
                run_id_stats_path = os.path.join(os.path.dirname(stats_file_path), f"statistics_{safe_run_id}.json")
                try:
                    with open(run_id_stats_path, 'w', encoding='utf-8') as f:
                        json.dump(all_statistics, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"⚠️ 按 run_id 保存统计失败: {e}")
            
            print(f"📊 统计数据已实时保存: {stats_file_path}")
            print(f"   当前 LLM 生成次数: {total_llm_count}")
            print(f"   当前模拟器成功执行次数: {total_emulator_success}")
            print(f"   当前成功覆盖 case 数: {total_coverage_improved}")
        except Exception as e:
            print(f"⚠️ 保存统计数据失败: {e}")
    
    for idx, module_name in enumerate(module_list):
        print(f"\n{'#'*60}")
        print(f"# 开始测试模块 [{idx+1}/{len(module_list)}]: {module_name}")
        print(f"{'#'*60}")
        
        # 为当前模块构造覆盖率文件路径
        Coverage_filename_origin = args.coverage_filename_origin + module_name + ".sv"
        Coverage_filename_later = args.coverage_filename_later + module_name + ".sv"
        
        # 检查模块文件是否存在
        if not os.path.exists(Coverage_filename_origin):
            print(f"⚠️ 模块文件不存在: {Coverage_filename_origin}，跳过")
            continue
        
        module_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            # 创建模块测试会话（传入共享的全局覆盖率管理器和 spec 开关）
            print(f"🔧 正在初始化模块 [{module_name}] 的测试会话...")
            session = ModuleCoverageSession(
                module_name, config, 
                Coverage_filename_origin, Coverage_filename_later, 
                model,
                global_coverage_manager=global_coverage_manager,  # 共享同一个实例
                use_spec=args.use_spec,  # 从命令行参数获取
                use_llm_report=args.llm_report  # 是否使用 LLM 写用例报告（默认否）
            )
            
            # 先跑已有的成功用例（这可能需要较长时间，特别是如果有多个用例）
            # 设计说明：
            # - 默认不运行已有成功用例（无论 Fresh 还是 Continue 模式），以节省时间
            # - 可以通过 --run_existing_seeds 参数显式启用
            if args.run_existing_seeds:
                mode_desc = "Fresh 模式" if run_mode == 'fresh' else "Continue 模式"
                print(f"🔄 [{mode_desc}] 开始运行模块 [{module_name}] 的已有成功用例（--run_existing_seeds 已启用）...")
                print(f"   注意：这可能需要较长时间，特别是如果有多个用例")
                session.run_existing_success_elfs()
                print(f"✅ 模块 [{module_name}] 的已有成功用例处理完成")
            else:
                # 默认跳过运行已有用例，直接开始 LLM 生成，节省时间
                print(f"⏭️  跳过运行已有成功用例（默认行为，如需运行请使用 --run_existing_seeds 参数）")
            
            # 检查是否还有未覆盖代码
            if len(session.uncovered_module_lines) == 0:
                print(f"✅ 模块 [{module_name}] 已无未覆盖代码，跳过")
                result = {
                    "status": "already_completed",
                    "iterations": 0,
                    "initial_uncovered": 0,
                    "final_uncovered": 0,
                    "covered_count": 0,
                    "initial_lines": [],
                    "final_lines": [],
                }
            else:
                # 注册当前模块的统计数据到全局字典（用于实时保存）
                running_modules_stats[module_name] = {
                    "statistics": session.statistics,
                    "module_name": module_name
                }
                # 立即保存一次（确保文件存在）
                save_statistics_realtime()
                
                # 运行 LLM 循环（传入保存函数和统计字典引用，以便定期保存）
                result = session.run_llm_loop(
                    max_iterations=max_iterations_per_module,
                    save_stats_callback=save_statistics_realtime  # 传入保存回调函数
                )
                
                # 模块完成后，从运行中字典移除
                if module_name in running_modules_stats:
                    del running_modules_stats[module_name]
            
        except Exception as e:
            print(f"❌ 模块 [{module_name}] 测试出错: {e}")
            import traceback
            traceback.print_exc()
            result = {
                "status": "error",
                "iterations": 0,
                "initial_uncovered": -1,
                "final_uncovered": -1,
                "covered_count": 0,
                "error": str(e),
                "initial_lines": [],
                "final_lines": [],
            }
        
        module_end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 记录结果
        result["module_name"] = module_name
        # 添加统计数据到结果
        if hasattr(session, 'statistics'):
            result["statistics"] = session.statistics
        all_results.append(result)
        
        # 写入报告
        write_module_report(report_file, module_name, result, module_start_time, module_end_time)
        
        # 实时保存统计数据（每个模块完成后保存一次）
        save_statistics_realtime()
        
        # 打印当前模块测试摘要
        print(f"\n📊 模块 [{module_name}] 测试摘要:")
        print(f"   状态: {result['status']}")
        print(f"   执行次数: {result['iterations']}")
        print(f"   覆盖率变化: {result['initial_uncovered']} → {result['final_uncovered']} (减少 {result['covered_count']} 行)")
    
    # 最终总结
    print(f"\n{'='*60}")
    print(f"📋 所有模块测试完成！总结报告:")
    print(f"{'='*60}")
    
    total_covered = 0
    for r in all_results:
        status_emoji = "✅" if r['status'] == 'completed' else "⏱️" if r['status'] == 'max_iterations' else "⚠️"
        print(f"  {status_emoji} {r['module_name']}: {r['initial_uncovered']} → {r['final_uncovered']} (覆盖 {r['covered_count']} 行, {r['iterations']} 次)")
        total_covered += r['covered_count']
    
    print(f"\n  📈 本次运行总共覆盖: {total_covered} 行代码")
    print(f"  📄 详细报告已保存: {report_file}")
    
    # 显示最终总覆盖率
    global_coverage_manager.print_total_coverage("最终总覆盖率")
    global_coverage_manager.print_module_group_stats("L2")
    
    # 最终保存统计数据到 JSON 文件（使用实时保存的文件路径）
    # 注意：统计数据已经在每个模块完成后实时保存，这里只是最终确认保存
    save_statistics_realtime()
    
    # 读取最终统计数据用于打印
    try:
        with open(stats_file_path, 'r', encoding='utf-8') as f:
            final_stats = json.load(f)
        final_summary = final_stats.get("summary", {})
        print(f"\n📊 最终统计数据:")
        print(f"   LLM 生成次数: {final_summary.get('total_llm_generations', 0)}")
        print(f"   模拟器成功执行次数: {final_summary.get('total_emulator_success', 0)}")
        print(f"   成功覆盖 case 数: {final_summary.get('total_coverage_improved', 0)}")
        print(f"   覆盖率数据点: {final_summary.get('total_coverage_points', 0)}")
    except Exception as e:
        print(f"⚠️ 读取最终统计数据失败: {e}")


if __name__ == '__main__':
    main()
