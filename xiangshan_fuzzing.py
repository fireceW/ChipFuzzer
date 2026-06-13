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
# Basic tools/configuration
# =========================

@dataclass
class PathConfig:
    """Path configuration, this object will be used later to manage paths uniformly."""
    project_root: str = "/root/XiangShan/"
    testcase_dir: str = "/root/XiangShan/testcase"
    success_root: str = "/root/XiangShan/successed"
    all_seed_dir: str = "/root/XiangShan/all_seed"
    uncovered_code_file: str = "uncovered_code.json"
    annotated_logs_dir: str = "/root/XiangShan/logs/annotated"
    # annotated directory used by global coverage statistics
    global_annotated_dir: str = "/root/XiangShan/logs_global/annotated"
    # cumulative coverage file
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
        # It turns out to be: verilator_coverage -annotate logs/annotated/ <dat_file>
        return "verilator_coverage -annotate logs2/annotated/ "


class EmulatorRunner:
    """Responsible for calling the simulator and returning the path of coverage.dat."""

    def __init__(self, config: PathConfig):
        self.config = config

    def run_elf(self, elf_relative_path: str):
        """
        elf_relative_path example:
          - 'successed/<module>/<xxx>.elf'
          - 'testcase/<xxx>.elf'
        """
        exec_cmd = self.config.emulator_cmd_prefix + elf_relative_path
        return self._execute_emulator_fast(self.config.emulator_exec_dir, exec_cmd)

    @staticmethod
    def _execute_emulator_fast(directory, exec_cmd):
        """
        Execute the simulator command in the specified directory and return the coverage file name and whether the execution is successful.

        All commands and output are fully logged.
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

        # Shorten the timeout to 30 minutes (1800 seconds) to avoid long-term stucks
        # Consider increasing if the test case takes longer, but usually 30 minutes is enough
        timeout_seconds = 1800  # 30 minutes

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

            # Use a more reliable timeout mechanism: check process status periodically
            import threading
            import queue
            output_queue = queue.Queue()
            process_finished = threading.Event()
            timeout_occurred = threading.Event()

            def read_output():
                """Read output in background thread"""
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
                """Forcefully terminate the process after timeout"""
                time.sleep(timeout_seconds)
                if not process_finished.is_set():
                    timeout_occurred.set()
                    print(f"\n⏰ 模拟器执行超时 (超过 {timeout_seconds // 60} 分钟)，强制终止进程...")
                    try:
                        # Try to terminate gracefully first
                        process.terminate()
                        time.sleep(5)  # wait 5 seconds
                        if process.poll() is None:
                            # If it is still running, force kill
                            print(f"   进程未响应，强制杀死...")
                            process.kill()
                    except Exception as e:
                        print(f"   终止进程时出错: {e}")

            # Start the output reading thread
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()

            # Start timeout monitoring thread
            timeout_thread = threading.Thread(target=timeout_killer, daemon=True)
            timeout_thread.start()

            # Add progress monitoring: output waiting information every 5 minutes
            def progress_monitor():
                elapsed = 0
                while not process_finished.is_set() and not timeout_occurred.is_set():
                    time.sleep(60)  # Check every 60 seconds
                    if process_finished.is_set() or timeout_occurred.is_set():
                        break
                    elapsed += 60
                    if elapsed % 300 == 0:  # Output every 5 minutes
                        print(f"⏳ 模拟器仍在运行中... (已运行 {elapsed // 60} 分钟)")

            monitor_thread = threading.Thread(target=progress_monitor, daemon=True)
            monitor_thread.start()

            # Wait for process to complete or timeout
            # Use polling to wait so that timeouts can be responded to in a timely manner
            while process.poll() is None:
                if timeout_occurred.is_set():
                    # A timeout has occurred and the waiting process has been terminated
                    time.sleep(1)
                    continue
                time.sleep(0.5)  # Check process status every 0.5 seconds

            # Wait for output reading to complete (up to 10 seconds)
            process_finished.wait(timeout=10)

            # Get output
            try:
                total_output = output_queue.get(timeout=1)
            except queue.Empty:
                total_output = ""

            elapsed = time.time() - start_time

            # Check if timed out
            if timeout_occurred.is_set():
                print(f"⏰ 模拟器执行超时 (超过 {timeout_seconds // 60} 分钟)，已强制终止")
                print(f"   提示：如果测试用例确实需要更长时间，可以考虑增加超时时间")
                print(f"{'='*60}\n")
                return None, False

            # Output simulator log (limited length)
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

            # default value
            coverage_filename = "logs/coverage.dat"

            # Prioritize matching of new output formats:
            # For example: dump coverage data to /root/XiangShan/build/2025-11-25-21-45-06.coverage.dat...
            match = re.search(
                r'dump coverage data to\s*(.+?\.coverage\.dat)\.\.\.',
                total_output
            )
            if match:
                coverage_filename = match.group(1).strip()
                print(f"📁 找到 coverage 文件: {coverage_filename}")
            else:
                # Compatible with old formats: Generated coverage filename: xxx
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
            # Make sure the process is killed
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
    """Unified encapsulation to execute common commands in a certain directory."""

    @staticmethod
    def run(directory, command, shell=True, log_prefix="🔧"):
        """
        Use subprocess to execute commands in the specified directory.

        All commands will be fully logged, including:
        - working directory
        - Complete command
        -Execution results
        - Output content
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
                # Limit the output length to avoid too long logs
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
# File/ASM Tools
# =========================

def read_assembly_file(file_path):
    """Read the code content from the assembly file."""
    try:
        with open(file_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Assembly file not found: {file_path}")
        return None


def list_elf_files(directory):
    """
    List the .elf files in the directory.
    (The original function name is read_all_asm_files_listdir, but it actually reads elf. Let’s change it to a more straightforward name)
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
    """Parse LLM-generated assembly code, clean it, and save it to a file."""

    def __init__(self, module_name: str, config: PathConfig):
        self.sections = {}
        self.instructions = []
        self.module_name = module_name
        self.file_hash = None
        self.config = config

    def generate_filename_hash(self, content, prefix="asm"):
        """Generate hash file names based on content."""
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.file_hash = content_hash
        return f"{prefix}_{timestamp}_{content_hash}.S"

    def parse_from_llm_output(self, text):
        """Extract assembly code blocks from LLM output and parse them. Supports multiple formats."""
        code_text = None

        # Try various code block formats
        patterns = [
            r"```assembly\s*\n(.*?)\n```",      # ```assembly
            r"```asm\s*\n(.*?)\n```",           # ```asm
            r"```riscv\s*\n(.*?)\n```",         # ```riscv
            r"```s\s*\n(.*?)\n```",             # ```s
            r"```\s*\n(.*?)\n```",              # ``` (no language tag)
            r"'''assembly\s*\n(.*?)\n'''",      # '''assembly
            r"'''asm\s*\n(.*?)\n'''",           # '''asm
        ]

        for pattern in patterns:
            code_match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if code_match:
                code_text = code_match.group(1)
                break

        # If still not found, try looking for .section .text or .global _start
        if not code_text:
            # Find code sections starting with .section or .global
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
        """Parse the assembly code structure and classify it by section."""
        lines = code_text.split('\n')
        current_section = '.text'  # Default segment

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # segment definition
            if line.startswith('.section'):
                section_match = re.match(r'\.section\s+([\.\w]+)', line)
                if section_match:
                    current_section = section_match.group(1)
                    self.sections[current_section] = []
            elif line.startswith('.'):
                # Other directives
                if current_section not in self.sections:
                    self.sections[current_section] = []
                self.sections[current_section].append(line)
            else:
                # instruction
                instruction = self._clean_instruction(line)
                if instruction:
                    if current_section not in self.sections:
                        self.sections[current_section] = []
                    self.sections[current_section].append(instruction)
                    self.instructions.append(instruction)

    @staticmethod
    def _clean_instruction(line):
        """Remove inline comments, returning a clean command line."""
        line = re.sub(r'#.*$', '', line).strip()
        line = re.sub(r'//.*$', '', line).strip()
        return line if line else None

    def generate_clean_assembly(self):
        """Generate clean assembly text."""
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
        """Save the assembly to the testcase directory and return the relative file name (without path)."""
        clean_code = self.generate_clean_assembly()
        name = self.generate_filename_hash(clean_code)
        os.makedirs(self.config.testcase_dir, exist_ok=True)

        filename = os.path.join(self.config.testcase_dir, f"{self.module_name}_{name}")
        with open(filename, 'w') as f:
            f.write(clean_code)

        print(f"汇编代码已保存到: {filename}")
        # Returns the file name relative to the testcase directory. Subsequent spelling of elf is required.
        return f"{self.module_name}_{name}"

    def analyze_coverage(self):
        """Simple analysis of instructions related to coverage."""
        coverage_related = []
        for instr in self.instructions:
            if any(keyword in instr for keyword in ['li', 'sw', 'ecall', 'jmp', 'call']):
                coverage_related.append(instr)
        return coverage_related


# =========================
# Code repository not covered
# =========================

class UncoveredCodeRepository:
    """Responsible for managing uncovered_code.json and global uncovered code in memory."""

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
        Call get_uncovered_code() to get the new global uncovered code,
        And intersect with the current self.all_module_code.
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
# Other gadgets
# =========================

def filter_print_cond_blocks(code_lines):
    """
    Filter out all printing-related lines of code, including:
    1. if (`PRINTF_COND) begin ... $fwrite code block
    2. All lines containing $fwrite (whether in a PRINTF_COND block or not)
    3. All lines containing PRINTF_COND
    This can avoid page freezes caused by a large number of print statements.
    """
    filtered = []
    skip = False
    fwrite_continuation = False  # Whether the token is on the continuation line of $fwrite

    for line in code_lines:
        stripped = line.strip()

        # Skip empty lines and plain comment lines
        if not stripped or stripped.startswith('//'):
            continue

        # 1. Detection of PRINTF_COND block start
        if 'if (`PRINTF_COND)' in line or 'if(PRINTF_COND)' in line:
            skip = True
            continue

        # 2. Detect $fwrite statement (including line continuation)
        if '$fwrite' in stripped:
            skip = True
            fwrite_continuation = True
            continue

        # 3. Detect the continuation line of $fwrite (usually ends with a comma or semicolon, or contains io_timer, etc.)
        if fwrite_continuation:
            # If a semicolon is encountered, the $fwrite statement ends
            if ';' in stripped:
                fwrite_continuation = False
                skip = False
            # If end or begin is encountered, the block ends
            elif stripped.startswith('end') or stripped.startswith('begin'):
                fwrite_continuation = False
                skip = False
            # Otherwise continue to skip (continue line)
            continue

        # 4. Detect other patterns related to PRINTF_COND
        if 'PRINTF_COND' in stripped:
            skip = True
            continue

        # 5. If end is encountered, end the skip state
        if skip and (stripped.startswith('end') or stripped.startswith('endmodule')):
            skip = False
            # Do not add the end line itself (if it is the end of the PRINTF_COND block)
            if 'PRINTF_COND' not in stripped:
                filtered.append(line)
            continue

        # 6. Only add if not skipped
        if not skip and not fwrite_continuation:
            filtered.append(line)

    return filtered



def build_fix_prompt(broken_code: str, error_msg: str, uncovered_code: str) -> str:
    """
    Generate a prompt for LLM to repair code (repair mode)

    parameter:
        broken_code: assembly code with errors
        error_msg: compiler error message
        uncovered_code: target uncovered code
    """
    error_feedback = generate_error_feedback(error_msg)

    prompt = f"""你是一个 RISC-V 汇编专家。以下汇编代码编译失败，请修复它。

# Compilation error message:
{error_feedback}

# Raw error output (first 500 characters):
```
{error_msg[:500]}
```

# Assembly code that needs fixing:
```assembly
{broken_code}
```

# Goal: Trigger the following uncovered code
```verilog
{uncovered_code[:1000]}
```

# Important repair rules:
1. **寄存器限制**：RISC-V 只有 t0-t6（没有 t7/t8/t9），s0-s11，a0-a7
2. **CSR 寄存器**：使用数字编号（如 0x300 而非 mstatus）
3. **立即数范围**：大多数指令的立即数必须在 12 位范围内（-2048 到 2047）
4. **标签语法**：标签后必须有冒号，如 `loop:`
5. **Instruction format**: make sure operand order is correct, with the destination register first.

Output the complete fixed assembly code wrapped by ```assembly and ```.
Only output the fixed code; do not add extra explanation.
"""
    return prompt


def build_analysis_prompt(asm_code: str, uncovered_code: str, coverage_result: str) -> str:
    """
    Build the prompt used to analyze why the target code was not covered.

    Args:
        asm_code: executed assembly code.
        uncovered_code: target uncovered code.
        coverage_result: coverage-result description.
    """
    prompt = f"""You are a hardware verification expert. The following assembly code was compiled and executed successfully, but the target code was not covered. Please analyze the reason and generate improved code.

# Assembly code executed:
```assembly
{asm_code[:1500]}
```

# Target does not cover code:
```verilog
{uncovered_code[:1000]}
```

# Override results:
{coverage_result}

# Please analyze:
1. 为什么当前代码没有触发目标分支？
2. 需要什么条件才能触发？
3. 生成一个改进后的汇编代码

Output the complete improved assembly code wrapped by ```assembly and ```.
Add one or two comment lines before the code to summarize the improvement idea.
"""
    return prompt


def build_prompt(uncovered_code, good_seeds, scala_code, compile_error=None, no_coverage_count=0, agent_memory=None, module_name=None, use_spec=False):
    """
    Build the main prompt sent to the LLM.

    Args:
        uncovered_code: uncovered target code.
        good_seeds: successful assembly examples.
        scala_code: corresponding Scala code.
        compile_error: previous compilation error, if any.
        no_coverage_count: number of consecutive no-coverage attempts.
        agent_memory: AgentMemory instance for contextual memory.
        module_name: current module name, used for SPEC lookup.
        use_spec: whether to use SPEC information from command-line options.
    """

    # Analyze the target code once to avoid duplicated work.
    analyzer = VerilogAnalyzer()
    analysis_result = analyzer.analyze_uncovered_code(uncovered_code)
    code_type = analysis_result['code_type']

    # Generate formatted analysis results.
    code_analysis = f"code type: {code_type}"
    if analysis_result['conditions']:
        code_analysis += f"\nKey conditions: {len(analysis_result['conditions'])} "
        for cond in analysis_result['conditions'][:3]:
            code_analysis += f"\n  - [{cond['type']}] {cond['expression'][:50]}"
    if analysis_result['values']:
        code_analysis += f"\nKey constant value: {', '.join(analysis_result['values'][:5])}"
    if analysis_result['suggestions']:
        code_analysis += f"\nTest suggestion:"
        for i, sug in enumerate(analysis_result['suggestions'][:3], 1):
            code_analysis += f"\n  {i}. {sug}"

    # Choose a template based on code type.
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

    prompt = f"""You are a RISC-V assembly expert performing hardware fuzz testing. Please generate a RISC-V assembler that triggers execution of the following uncovered code.

{RISCV_INSTRUCTION_GUIDE}

# Verilog code not covered:
```verilog
{uncovered_code}
```

# Code analysis results:
{code_analysis}

# Build requirements:
1. **先分析**：仔细阅读上面的代码分析结果，理解触发条件
2. **针对性生成**：根据分析结果，生成能触发这些条件的指令序列
3. **使用建议的值**：如果分析中提到了关键常量值，尝试使用这些值
4. **测试边界情况**：使用边界值（0, -1, MAX, MIN）测试
5. **灵活使用控制流**：可以使用循环、分支、跳转等任何合法指令来增加测试覆盖
6. **代码长度**：生成足够长的指令序列（建议 50-200 条指令），确保能充分触发硬件逻辑
7. 【关键】寄存器只能用: t0-t6, s0-s11, a0-a7（没有 t7/t8/t9！）

# Output format:
```assembly
.section .text
.global _start

_start:
    # Briefly describe the testing strategy (1-2 lines of comments)
    # Your test code...

    # Program exits (must be retained)
    li      gp, 1
    li      a7, 93
    li      a0, 0
    ecall
    unimp
```

# Reference example:
```assembly
{selected_template}
```
"""

    # Add contextual memory if the memory system is available.
    if agent_memory:
        memory_context = agent_memory.get_context_summary(uncovered_code)
        if memory_context:
            prompt += f"\n\n{memory_context}\n"

    # Add SPEC file information if available.
    # Prefer the provided module name; otherwise try to extract it from the code.
    detected_module_name = module_name

    if not detected_module_name:
        # Extract module name from uncovered_code.
        module_match = re.search(r'(\w+)\.sv', uncovered_code[:200])
        if module_match:
            detected_module_name = module_match.group(1)

    # Add SPEC information only when SPEC analysis is enabled.
    if use_spec and detected_module_name:
        try:
            spec_hints = get_module_spec_hints(detected_module_name, uncovered_code)
            if spec_hints:
                prompt += f"\n\n{spec_hints}\n"
        except Exception as e:
            # SPEC analysis failure does not affect the main process.
            pass

    # Add concise error feedback when compilation failed.
    if compile_error:
        error_feedback = generate_error_feedback(compile_error)
        prompt += f"""

# ⚠️Last ​​compilation failed:
{error_feedback}

Please fix the errors and regenerate the assembly testcase.
"""

    # Add extra guidance after multiple no-coverage attempts.
    if no_coverage_count >= 2:
        prompt += f"""

# ⚠️ New code not covered by {no_coverage_count} consecutive tests
Try the following strategies:
1. Use different boundary values, such as 0, -1, MAX_INT, and MIN_INT.
2. Trigger different conditional branches.
3. Use more register combinations.
4. Try exceptional cases, such as divide-by-zero or overflow.
"""

    # Add successful seeds as references probabilistically.
    if good_seeds and random.random() < 0.4:
        selected_seed = random.choice(good_seeds)
        # Limit length.
        if len(selected_seed) > 1000:
            selected_seed = selected_seed[:1000] + "\n    # ...\n"
        prompt += f"""

# Success case reference:
```assembly
{selected_seed}
```
"""

    return prompt


# =========================
# Combinational logic: module-level test session
# =========================

class ModuleCoverageSession:
    """A complete testing session around a module (including existing good seeds + new LLM generation)."""

    def __init__(self, module_name: str, config: PathConfig, Coverage_filename_origin, Coverage_filename_later, model, global_coverage_manager=None, use_spec=False):
        self.module_name = module_name
        self.config = config
        self.emulator = EmulatorRunner(config)
        self.subproc = SubprocessRunner()
        self.uncovered_repo = UncoveredCodeRepository(config, Coverage_filename_origin, Coverage_filename_later)
        self.Coverage_filename_origin = Coverage_filename_origin
        self.Coverage_filename_later = Coverage_filename_later
        self.model = model
        self.use_spec = use_spec  # Whether to use spec file analysis

        # Use the global coverage manager passed in, or create a new one (backward compatibility)
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

        # Initialize statistics
        self.statistics = {
            "llm_generation_count": 0,  # LLM generation times
            "emulator_success_count": 0,  # Number of successful simulator executions
            "coverage_improved_count": 0,  # The number of cases successfully covered (the number of use cases that improve coverage)
            "coverage_data": [],  # Coverage change data [{timestamp, coverage_percentage, uncovered_lines, iteration}]
            "start_time": time.time(),
        }

        # Get the uncovered code for this module
        print(f"📖 正在读取模块 [{self.module_name}] 的未覆盖代码...")
        self.uncovered_module_lines, self.file_infos, self.scala_lines = \
            extract_lines_with_prefix_origin(self.module_name, self.Coverage_filename_origin)

        print(f"   ✅ 读取完成，未覆盖代码行数: {len(self.uncovered_module_lines)}")

        # Filter printf block and all $fwrite related code (to avoid page freezes caused by a large number of print statements)
        self.uncovered_module_lines = filter_print_cond_blocks(self.uncovered_module_lines)
        print(f"the total uncovered code line after filter is {len(self.uncovered_module_lines)}")

        # Only print the first 20 lines as examples to avoid lags caused by excessive output.
        print("前 20 行未覆盖代码示例:")
        for item in self.uncovered_module_lines[:20]:
            print(item)
        if len(self.uncovered_module_lines) > 20:
            print(f"... 还有 {len(self.uncovered_module_lines) - 20} 行未覆盖代码")

        self.good_seeds = []  # Newly generated and successfully overwritten asm text
        self.fail_num = 0

        # Initialize the Agent Memory system
        self.agent_memory = get_agent_memory(module_name)
        print(f"🧠 Agent Memory 系统已初始化（已有 {len(self.agent_memory.history)} 条历史记录）")

        # The entire project is not globally covered (used for printing information)
        print(f"📊 全局未覆盖代码行数: {len(self.uncovered_repo.all_module_code)}")
        print(f"✅ 模块 [{self.module_name}] 初始化完成")

    # -------- Run existing good seeds (elf in success directory) --------

    def run_existing_success_elfs(self):
        success_dir = os.path.join(self.config.success_root, self.module_name)
        os.makedirs(success_dir, exist_ok=True)

        elf_files = list_elf_files(success_dir)
        if not elf_files:
            print(f"📂 模块 [{self.module_name}] 无已有成功用例，跳过")
            return

        print(f"📂 模块 [{self.module_name}] 发现 {len(elf_files)} 个已有成功用例，开始运行...")

        # Collect all dat files and process them in batches to reduce the number of coverage updates
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

        # Optimization: merge into sum_gj.dat one by one, but only update the annotated report once (significantly reducing time consumption)
        print(f"\n🔄 批量处理 {len(dat_files)} 个覆盖率文件...")
        print(f"   策略：逐个合并到累积文件，最后统一更新报告（减少更新次数）")

        # Merge dat files one by one into sum_gj.dat (only merge, do not update the report)
        for idx, dat_file in enumerate(dat_files, 1):
            print(f"   [{idx}/{len(dat_files)}] 合并覆盖率文件: {os.path.basename(dat_file)}")

            # Only merge, do not update annotated reports
            if not self.global_coverage_manager.merge_coverage_dat(dat_file):
                print(f"      ❌ 合并失败，跳过此文件")
                continue
            print(f"      ✅ 合并成功")

        # After all files are merged, the annotated report and coverage.info are updated only once
        print(f"\n🔄 所有覆盖率文件已合并，正在更新全局覆盖率报告...")
        print(f"   注意：这可能需要 30-60 秒，请耐心等待...")

        # Update annotated report (only executed once)
        if self.global_coverage_manager.update_annotated_report():
            print(f"   ✅ Annotated 报告已更新")
        else:
            print(f"   ⚠️ Annotated 报告更新失败")

        # Update coverage.info (do this only once)
        if self.global_coverage_manager.update_coverage_info():
            print(f"   ✅ Coverage.info 已更新")
        else:
            print(f"   ⚠️ Coverage.info 更新失败")

        # Recount uncovered lines of code (used to update the module-level uncovered list)
        print(f"   📊 正在重新统计未覆盖代码...")
        new_uncovered_lines = self.global_coverage_manager.get_all_uncovered_lines()
        cov = self.global_coverage_manager.get_total_coverage_from_genhtml(use_cache=False)
        pct = cov.get("coverage_percentage", 0) or 0
        print(f"   📊 当前覆盖率: {pct:.2f}%")

        # Update the module's uncovered code list (read from the global annotated directory)
        global_module_file = os.path.join(
            self.config.global_annotated_dir,
            f"{self.module_name}.sv"
        )
        if os.path.exists(global_module_file):
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, global_module_file
            )
            # Code list not covered by update module
            self.uncovered_module_lines = [
                line for line in self.uncovered_module_lines
                if line in uncovered_code_stage
            ]
            print(f"   ✅ 模块 [{self.module_name}] 未覆盖代码列表已更新: {len(self.uncovered_module_lines)} 行")

        print(f"✅ 模块 [{self.module_name}] 已有成功用例处理完成")

    # -------- Process coverage.dat -> Update uncovered rows --------

    def _apply_coverage_dat(self, dat_file: str, from_good_seed: bool):
        """
        Call verilator_coverage + update module uncovered & global uncovered rows.

        Optimization: directly update global coverage and no longer repeatedly update the temporary directory (logs2/annotated)
        Because the global annotated directory already contains all information, module-level checks can read directly from the global directory
        """
        # Check for global coverage changes using the Global Coverage Manager
        # This automatically: 1) merges dat into sum_gj.dat 2) updates the global annotated directory 3) updates coverage.info
        print(f"📌 [阶段] 开始对当前 case 生成的覆盖率进行统计分析（合并 dat、更新 annotated、更新 coverage.info）")
        print(f"📌 [阶段] 正在合并并更新覆盖率（约需数秒），请稍候...")
        print(f"🔄 正在应用覆盖率数据: {dat_file}")
        global_improved, global_reduced, global_newly_covered = \
            self.global_coverage_manager.check_global_improvement(dat_file)

        # Save the mark of global coverage improvement for subsequent judgment whether to save the test case
        self._last_global_improved = global_improved
        self._last_global_reduced = global_reduced
        self._last_global_newly_covered = global_newly_covered

        # Read the module's uncovered code from the updated global annotated directory
        # This ensures that module level checks also reflect the global latest state
        global_module_file = os.path.join(
            self.config.global_annotated_dir,
            f"{self.module_name}.sv"
        )

        # Prefer the global annotated directory if the file exists
        if os.path.exists(global_module_file):
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, global_module_file
            )
        else:
            # Go back to the original directory
            uncovered_code_stage = extract_lines_with_prefix_stage(
                self.module_name, self.Coverage_filename_later
            )

        # Calculate the newly covered rows of this module
        covered_lines = [
            line for line in self.uncovered_module_lines
            if line not in uncovered_code_stage
        ]

        # Code list not covered by update module
        self.uncovered_module_lines = [
            line for line in self.uncovered_module_lines
            if line in uncovered_code_stage
        ]

        if from_good_seed:
            print(f"good seed 更新后该模块未覆盖代码行数: {len(self.uncovered_module_lines)}")
        else:
            print(f"更新后未覆盖代码行数: {len(self.uncovered_module_lines)}")

        # If there is global coverage improvement, print confirmation message
        if global_improved:
            print(f"✅ 全局覆盖率已更新到: {self.config.global_annotated_dir}")

        # Update old global uncovered information (to maintain compatibility)
        updated = self.uncovered_repo.update_after_coverage()
        if from_good_seed and not updated:
            print(f"good seed 更新后所有模块未覆盖代码行数: "
                  f"{len(self.uncovered_repo.all_module_code)}")

        return covered_lines

    # -------- LLM driven loop generation --------

    def _select_uncovered_batch(self):
        """
        Intelligently select a batch of uncovered code lines + corresponding scala lines.

        Strategy:
        1. If there is a lot of uncovered code, select a batch (30-50 lines) for LLM to process
        2. Dynamically adjust the selection range based on the number of failures to avoid repeatedly selecting the same code.
        3. Prioritize different types of code (by analyzing code characteristics)
        """
        # Dynamic batch size: adjusts based on the amount of uncovered code
        if len(self.uncovered_module_lines) >= 50:
            batch_size = 50
        elif len(self.uncovered_module_lines) >= 20:
            batch_size = 30
        else:
            batch_size = len(self.uncovered_module_lines)

        # Select different batches based on number of failures (avoid duplication)
        batch_offset = (self.fail_num // 5) * batch_size

        if len(self.uncovered_module_lines) > batch_size:
            start_idx = min(batch_offset, len(self.uncovered_module_lines) - batch_size)
            end_idx = start_idx + batch_size
            uncovered_code = self.uncovered_module_lines[start_idx:end_idx]

            # The corresponding scala line (if available)
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
        """Get coverage statistics of the current module"""
        return {
            "module_name": self.module_name,
            "uncovered_lines": len(self.uncovered_module_lines),
            "good_seeds_count": len(self.good_seeds),
        }

    def run_llm_loop(self, max_iterations: int = 20, save_stats_callback=None) -> dict:
        """
        Main loop: Continuously call LLM to generate new test cases and try to cover them.

        parameter:
            max_iterations: Maximum number of attempts, automatically exit after reaching
            save_stats_callback: Optional save statistics callback function, used to save statistics in real time

        return:
            dict: Dictionary containing execution results
                - status: "completed" (no uncovered code) / "max_iterations" (maximum number of times reached) / "error"
                - iterations: actual number of iterations performed
                - initial_uncovered: initial number of uncovered rows
                - final_uncovered: The final number of uncovered rows
                - covered_count: the number of rows covered this time
        """
        compile_error_info = None
        consecutive_compile_errors = 0
        consecutive_no_coverage = 0  # Number of consecutive no coverage times
        iteration_count = 0
        last_asm_code = None  # Save the last generated code for use in repair mode
        fix_attempt_count = 0  # Repair attempts
        MAX_FIX_ATTEMPTS = 2  # Maximum number of repair attempts per compilation failure

        # Record initial state
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

            # Check if the maximum number of attempts has been reached
            if iteration_count > max_iterations:
                print(f"\n⚠️ 模块 [{self.module_name}] 达到最大尝试次数 ({max_iterations})，切换到下一个模块")

                # save memory
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

            # Use the improved prompt, passing in compilation error information, no coverage times, memory system, module name and spec switch
            prompt = build_prompt(
                uncovered_code_line,
                self.good_seeds,
                scala_code_line,
                compile_error=compile_error_info,
                no_coverage_count=consecutive_no_coverage,
                agent_memory=self.agent_memory,
                module_name=self.module_name,  # Pass in the module name for spec analysis
                use_spec=self.use_spec  # Whether to enable spec analysis
            )

            # Call LLM
            start_time = time.time()
            print(f"📌 [阶段] LLM 开始生成 case（可能需数分钟），请勿中断...")
            print(f"📌 [阶段] 等待 LLM 生成用例（约需数分钟），请稍候...")
            print(f"🤖 正在调用 LLM ({self.model})...")

            # Count LLM generation times
            self.statistics["llm_generation_count"] += 1

            # Statistics are saved every 5 LLM calls (updated in real time)
            if save_stats_callback and self.statistics["llm_generation_count"] % 5 == 0:
                try:
                    save_stats_callback()
                except Exception as e:
                    print(f"⚠️ 保存统计数据时出错: {e}")

            if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                result = callOpenAI_KJY(prompt, self.model)
            else:
                result = callOpenAI(prompt)

            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"⏱️ LLM 响应时间: {elapsed_time:.2f} 秒")

            # Save LLM output for debugging
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

            # Parse LLM output
            parser = AssemblyCodeParser(self.module_name, self.config)
            parsed_ok = parser.parse_from_llm_output(result)
            if not parsed_ok:
                print("⚠️ LLM 输出中未找到有效的汇编代码块，跳过")
                self.fail_num += 1
                compile_error_info = None
                continue

            # Get the parsed assembly code and verify
            raw_asm_code = parser.generate_clean_assembly()

            print("🔍 正在验证汇编代码...")
            is_valid, validation_errors = validate_asm(raw_asm_code)

            if not is_valid:
                print(f"⚠️ 汇编代码验证发现 {len(validation_errors)} 个问题:")
                for err in validation_errors[:5]:
                    print(f"   - {err}")

                # Try automatic repair
                print("🔧 正在尝试自动修复...")
                fixed_code, fixes_applied = fix_asm(raw_asm_code)

                if fixes_applied:
                    print(f"✅ 已应用 {len(fixes_applied)} 个修复:")
                    for fix in fixes_applied[:5]:
                        print(f"   - {fix}")

                    # Reparse using the fixed code
                    parser.sections = {}
                    parser.instructions = []
                    parser._parse_assembly_code(fixed_code)

            # Save assembly file
            asm_file_name = parser.save_to_file()
            elf_file_name = asm_file_name.split(".")[0] + ".bin"
            print(f"📄 生成的文件: {asm_file_name}")

            # Compilation and simulation
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

                # Logging failed interactions
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

                # Save current code for repair
                last_asm_code = raw_asm_code

                # Try repair mode
                if fix_attempt_count < MAX_FIX_ATTEMPTS:
                    fix_attempt_count += 1
                    print(f"🔧 启动修复模式（第 {fix_attempt_count}/{MAX_FIX_ATTEMPTS} 次修复尝试）...")
                    print(f"📌 [阶段] LLM 开始修复编译失败的 case（可能需数分钟），请勿中断...")
                    print(f"📌 [阶段] 等待 LLM 修复代码（约需数分钟），请稍候...")

                    # Generate repair prompt
                    uncovered_code_line, _ = self._select_uncovered_batch()
                    fix_prompt = build_fix_prompt(raw_asm_code, error_msg, uncovered_code_line)

                    # Call LLM to fix (add timeouts and exception handling)
                    print(f"🤖 正在调用 LLM 修复代码...")
                    try:
                        import signal

                        # Set timeout (5 minutes)
                        def timeout_handler(signum, frame):
                            raise TimeoutError("LLM 修复调用超时（5分钟）")

                        # Using signal timeouts (Unix systems only)
                        if hasattr(signal, 'SIGALRM'):
                            signal.signal(signal.SIGALRM, timeout_handler)
                            signal.alarm(300)  # 5 minutes timeout

                        try:
                            if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                                fix_result = callOpenAI_KJY(fix_prompt, self.model)
                            else:
                                fix_result = callOpenAI(fix_prompt)
                        finally:
                            # Cancel timeout
                            if hasattr(signal, 'SIGALRM'):
                                signal.alarm(0)
                    except TimeoutError as e:
                        print(f"❌ LLM 修复调用超时: {e}")
                        print(f"   跳过本次修复尝试，继续下一次迭代")
                        fix_attempt_count -= 1  # Fallback count since no real attempt was made this time
                        compile_error_info = error_msg
                        continue
                    except Exception as e:
                        print(f"❌ LLM 修复调用失败: {e}")
                        print(f"   跳过本次修复尝试，继续下一次迭代")
                        import traceback
                        traceback.print_exc()
                        fix_attempt_count -= 1  # Fallback count since no real attempt was made this time
                        compile_error_info = error_msg
                        continue

                    # Parse the repaired code
                    fix_parser = AssemblyCodeParser(self.module_name, self.config)
                    if fix_parser.parse_from_llm_output(fix_result):
                        fixed_code = fix_parser.generate_clean_assembly()

                        # Verify the fixed code
                        is_valid, _ = validate_asm(fixed_code)
                        if not is_valid:
                            fixed_code, _ = fix_asm(fixed_code)

                        # Save and compile the repaired code
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

                            # Record successful repair interactions
                            self.agent_memory.record_interaction(
                                uncovered_code=uncovered_code_line,
                                prompt_type="fix",
                                asm_code=fixed_code,
                                success=False,  # For now, wait for coverage results
                                compile_success=True,
                                coverage_improved=False,
                                strategy=f"fix_attempt_{fix_attempt_count}"
                            )

                            # Continue executing the emulator (do not continue)
                            print(f"📌 [阶段] 正在启动仿真（约需数秒），请稍候...")
                            elf_rel_path = f"testcase/{elf_file_name}"
                            dat_file, ok = self.emulator.run_elf(elf_rel_path)
                            if ok and dat_file:
                                print("验证流程: 仿真成功")
                                # Count the number of successful executions of the simulator
                                self.statistics["emulator_success_count"] += 1

                                covered_lines = self._apply_coverage_dat(dat_file, from_good_seed=True)
                                self._handle_success_seed_if_any(
                                    covered_lines=covered_lines,
                                    asm_file_name=asm_file_name,
                                    elf_file_name=elf_file_name
                                )

                                # Record coverage data (repair mode)
                                try:
                                    coverage_info = self.global_coverage_manager.get_total_coverage_from_genhtml()
                                    if coverage_info and "coverage_percentage" in coverage_info:
                                        current_coverage = coverage_info["coverage_percentage"]
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

                                # Save statistics immediately after each update
                                if save_stats_callback:
                                    try:
                                        save_stats_callback()
                                    except Exception as e:
                                        print(f"⚠️ 保存统计数据时出错: {e}")

                                global_improved = getattr(self, '_last_global_improved', False)
                                if global_improved or bool(covered_lines):
                                    print("🎉 修复后的代码成功覆盖了新代码！")
                                    self.global_coverage_manager.print_total_coverage("更新后总覆盖率")

                                    # Update memory to success
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

                # Repair attempts exhausted, reset state
                fix_attempt_count = 0
                compile_error_info = error_msg

                # If there are too many consecutive compilation errors, clear the error messages and start again.
                # But keep the last error message as it may contain useful tips
                if consecutive_compile_errors >= 5:
                    print("⚠️ 连续编译错误过多（5次），清除错误信息重新尝试")
                    print("   提示：如果问题持续，可能需要检查 LLM 输出格式或汇编语法")
                    compile_error_info = None
                    consecutive_compile_errors = 0
                    fix_attempt_count = 0  # Reset repair count

                continue
            else:
                compile_error_info = None
                consecutive_compile_errors = 0
                fix_attempt_count = 0
                print("✅ 编译成功")
                print("验证流程: 编译成功")

                # Record compilation success (but coverage results are not known yet)
                self.agent_memory.record_interaction(
                    uncovered_code=uncovered_code_line,
                    prompt_type="generate",
                    asm_code=raw_asm_code,
                    success=False,  # It is False for now and will be updated after the coverage results come out.
                    compile_success=True,
                    coverage_improved=False,
                    strategy=f"iteration_{iteration_count}"
                )

            # Run emulator
            print(f"📌 [阶段] 正在启动仿真（约需数秒），请稍候...")
            elf_rel_path = f"testcase/{elf_file_name}"
            dat_file, ok = self.emulator.run_elf(elf_rel_path)
            if not ok or not dat_file:
                print("⚠️ 模拟器运行失败，跳过本次结果")
                print("验证流程: 仿真失败")
                self.fail_num += 1
                continue

            print("验证流程: 仿真成功")
            # Count the number of successful executions of the simulator
            self.statistics["emulator_success_count"] += 1

            # Apply coverage.dat
            covered_lines = self._apply_coverage_dat(dat_file, from_good_seed=True)

            # If the number of globally uncovered rows decreases, it means this is a "good seed" and additional records will be made.
            # Success information has been printed in UncoveredCodeRepository.update_after_coverage
            # Save seeds here
            self._handle_success_seed_if_any(
                covered_lines=covered_lines,
                asm_file_name=asm_file_name,
                elf_file_name=elf_file_name
            )

            # Get global coverage improvement information
            global_improved = getattr(self, '_last_global_improved', False)

            # Determine whether there is coverage improvement: global improvement or current module improvement
            has_improvement = global_improved or bool(covered_lines)

            # Record coverage data (recorded after each successful execution of the simulator)
            try:
                coverage_info = self.global_coverage_manager.get_total_coverage_from_genhtml()
                if coverage_info and "coverage_percentage" in coverage_info:
                    current_coverage = coverage_info["coverage_percentage"]
                    uncovered_count = self.global_coverage_manager.baseline_uncovered_count

                    # Record coverage data
                    self.statistics["coverage_data"].append({
                        "timestamp": time.time(),
                        "coverage_percentage": current_coverage,
                        "uncovered_lines": uncovered_count,
                        "iteration": iteration_count,
                        "module": self.module_name,
                    })

                    # Save statistics immediately after each coverage data update (live updates)
                    if save_stats_callback:
                        try:
                            save_stats_callback()
                        except Exception as e:
                            print(f"⚠️ 保存统计数据时出错: {e}")
            except Exception as e:
                # If acquisition of coverage fails, the main process will not be affected.
                pass

            if has_improvement:
                print("🎉 检测到覆盖率提升！")
                # Global coverage has been updated in _apply_coverage_dat -> check_global_improvement
                # There is no need to repeat the verilator_coverage command here.
                # Because GlobalCoverageManager.check_global_improvement has done the following:
                # 1. Merge .dat files into sum_gj.dat
                # 2. Update annotated report
                # 3. Update coverage.info

                # Show updated total coverage
                self.global_coverage_manager.print_total_coverage("更新后总覆盖率")

                # Record successful interactions (update previous records)
                # Find the most recent record and update it
                if self.agent_memory.history:
                    last_entry = self.agent_memory.history[-1]
                    if last_entry.asm_code[:100] == raw_asm_code[:100]:  # Match the most recent record
                        # updated successfully
                        last_entry.success = True
                        last_entry.coverage_improved = True
                        last_entry.coverage_lines = covered_lines
                        last_entry.strategy = f"successful_iteration_{iteration_count}"

                self.fail_num = 0  # Reset failure count
                consecutive_no_coverage = 0  # Reset no coverage count
                last_asm_code = None
            else:
                print("ℹ️  本次测试没有新的代码被覆盖（包括全局）")
                print("验证流程: 无新覆盖")
                print("验证流程: 没有覆盖成功")
                print(f"验证流程: 无覆盖用例: {asm_file_name}")
                self.fail_num += 1
                consecutive_no_coverage += 1

                # Update memory: Compilation successful but coverage not improved
                if self.agent_memory.history:
                    last_entry = self.agent_memory.history[-1]
                    if last_entry.asm_code[:100] == raw_asm_code[:100]:
                        last_entry.success = False  # Although the compilation was successful, the coverage was not improved
                        last_entry.coverage_improved = False

                # If new code is not covered multiple times in a row, analysis mode is triggered.
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
                    if self.model == "qwen3:235b" or self.model == "deepseek-r1:671b":
                        analysis_result = callOpenAI_KJY(analysis_prompt, self.model)
                    else:
                        analysis_result = callOpenAI(analysis_prompt)

                    # Save analysis results for next reference
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

                    # Logging analysis mode interactions
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

        # The loop ends normally (no uncovered code)
        print(f"\n🎉 模块 [{self.module_name}] 测试完成！所有代码已覆盖！")

        # save memory
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
        Whether to record as good seed is determined based on whether the global coverage is improved.
        Prioritize using global coverage improvement as a basis for judgment, rather than just the coverage of the current module.
        """
        success_dir = os.path.join(self.config.success_root, self.module_name)
        os.makedirs(success_dir, exist_ok=True)
        os.makedirs(self.config.all_seed_dir, exist_ok=True)

        testcase_asm_path = os.path.join(self.config.testcase_dir, asm_file_name)
        testcase_elf_path = os.path.join(self.config.testcase_dir, elf_file_name)

        assembly_code = read_assembly_file(testcase_asm_path)

        GJ_SUCCESS_SEED_DIR = "/root/ChipFuzzer_cursor/GJ_Success_Seed"
        os.makedirs(GJ_SUCCESS_SEED_DIR, exist_ok=True)

        # Get global coverage improvement information
        global_improved = getattr(self, '_last_global_improved', False)
        global_reduced = getattr(self, '_last_global_reduced', 0)
        global_newly_covered = getattr(self, '_last_global_newly_covered', [])

        # Determine whether it should be saved: global coverage improvement or current module has new lines covered
        should_save = global_improved or bool(covered_lines)

        if should_save and assembly_code:
            # 1) Save to GJ_Success_Seed directory (key save location)
            # Save .S file
            with open(os.path.join(GJ_SUCCESS_SEED_DIR, asm_file_name), 'w') as f:
                f.write(assembly_code)
            print(f"✅ 成功案例已保存到 GJ_Success_Seed: {asm_file_name}")

            # Save .bin file to GJ_Success_Seed
            bin_file_name = asm_file_name.replace(".S", ".bin")
            testcase_bin_path = os.path.join(self.config.testcase_dir, bin_file_name)
            if os.path.exists(testcase_bin_path):
                shutil.copy(testcase_bin_path, os.path.join(GJ_SUCCESS_SEED_DIR, bin_file_name))
                print(f"✅ BIN 文件已保存到 GJ_Success_Seed: {bin_file_name}")

            # Generate and save report files
            self._generate_case_report(
                case_name=asm_file_name.replace(".S", ""),
                module_name=self.module_name,
                global_improved=global_improved,
                global_reduced=global_reduced,
                global_newly_covered=global_newly_covered,
                covered_lines=covered_lines,
                output_dir=GJ_SUCCESS_SEED_DIR
            )

            # 2) Save to all_seed_dir
            with open(os.path.join(self.config.all_seed_dir, asm_file_name), 'w') as f:
                f.write(assembly_code)

            # 3) Copy elf to success_dir
            if os.path.exists(testcase_elf_path):
                shutil.copy(testcase_elf_path, os.path.join(success_dir, elf_file_name))
                print(f"✅ ELF 文件已保存到: {os.path.join(success_dir, elf_file_name)}")

            # 4) Add to the good_seeds memory list and count the number of successfully covered cases
            self.good_seeds.append(assembly_code)
            self.statistics["coverage_improved_count"] = self.statistics.get("coverage_improved_count", 0) + 1
            print(f"当前参考案例数: {len(self.good_seeds)}")

            # 5) Save to module-specific success_dir
            with open(os.path.join(success_dir, asm_file_name), 'w') as f:
                f.write(assembly_code)

            print(f"✅ 汇编代码已保存到: {os.path.join(self.config.all_seed_dir, asm_file_name)}")

        # Print coverage (only output: current coverage, number of multi-coverage lines this time, test case name + number of multi-coverage lines)
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
        Use LLM to analyze the covered lines of code to determine the main covered modules and functions

        parameter:
            covered_lines: list of covered lines of code (list of strings)

        return:
            {
                "main_module": "module name",
                "module_distribution": {"module name": number of lines},
                "main_function": "Function description"
            }
        """
        if not covered_lines:
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}

        # Limit the scope of analysis and only take the first 30 lines as samples (to avoid prompts that are too long)
        lines_to_analyze = covered_lines[:30]

        # Clean lines of code: remove coverage markers and path information
        cleaned_lines = []
        for line in lines_to_analyze:
            # Remove coverage tag %000000
            clean_line = re.sub(r'%\d{6}\s*', '', str(line)).strip()
            # Remove path information @[xxx:yy]
            clean_line = re.sub(r'@\[[^\]]+\]\s*', '', clean_line).strip()
            if clean_line and len(clean_line) > 5:
                cleaned_lines.append(clean_line)

        if not cleaned_lines:
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}

        # Construct a prompt to let LLM analyze the code
        code_sample = "\n".join(cleaned_lines[:20])  # Maximum 20 lines

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
            # Call LLM analysis
            llm_response = callOpenAI_KJY(prompt, self.model)

            # Try to extract JSON from the response
            # Remove possible markdown code block tags
            llm_response = re.sub(r'```json\s*', '', llm_response)
            llm_response = re.sub(r'```\s*', '', llm_response).strip()

            # Try to parse JSON
            result = json.loads(llm_response)

            main_module = result.get("main_module", "未知")
            main_function = result.get("main_function", "未知")

            # Build return results
            module_distribution = {}
            if main_module != "未知":
                module_distribution[main_module] = len(cleaned_lines)

            return {
                "main_module": main_module,
                "module_distribution": module_distribution,
                "main_function": main_function
            }

        except Exception as e:
            # Returns default value if LLM call fails or parsing fails
            print(f"⚠️ LLM 分析覆盖代码失败: {e}")
            return {"main_module": "未知", "module_distribution": {}, "main_function": "未知"}

    def _generate_case_report(self, case_name: str, module_name: str, global_improved: bool,
                              global_reduced: int, global_newly_covered: list, covered_lines: list,
                              output_dir: str):
        """
        Generate test case report files

        parameter:
            case_name: use case name (without extension)
            module_name: The target module name of the test (not necessarily the main module covered)
            global_improved: Whether global coverage is improved
            global_reduced: global reduction in the number of uncovered rows
            global_newly_covered: list of newly covered lines of code (global)
            covered_lines: List of lines of code covered by the current module
            output_dir: output directory
        """
        report_file = os.path.join(output_dir, f"{case_name}.txt")

        # Analyze the modules and functions actually covered
        # Prioritize using global_newly_covered (global newly covered code), if not, use covered_lines
        lines_to_analyze = global_newly_covered if global_newly_covered else covered_lines
        analysis = self._analyze_covered_modules(lines_to_analyze)

        main_covered_module = analysis["main_module"]
        module_dist = analysis["module_distribution"]
        main_function = analysis["main_function"]

        # Construct the report content (about three sentences)
        report_lines = []

        # First sentence: Mainly covered modules
        if main_covered_module != "未知":
            report_lines.append(f"本测试用例主要覆盖了 {main_covered_module} 模块。")
        else:
            report_lines.append(f"本测试用例主要覆盖了 {module_name} 模块。")

        # Second sentence: What functions does the covered code achieve:
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

        # Third sentence: Module distribution or code examples
        if len(module_dist) > 1:
            # Show the first 2-3 main modules
            sorted_modules = sorted(module_dist.items(), key=lambda x: x[1], reverse=True)[:3]
            module_names = [f"{name}({count}行)" for name, count in sorted_modules]
            if len(module_dist) > 3:
                report_lines.append(f"覆盖的模块包括：{', '.join(module_names)} 等。")
            else:
                report_lines.append(f"覆盖的模块包括：{', '.join(module_names)}。")
        elif lines_to_analyze and len(lines_to_analyze) <= 5:
            # Only a few lines of code, showing examples
            sample_lines = lines_to_analyze[:2]
            sample_text = "、".join([re.sub(r'%\d{6}\s*', '', line).strip()[:40] + "..." if len(line) > 40 else re.sub(r'%\d{6}\s*', '', line).strip() for line in sample_lines])
            if len(lines_to_analyze) > 2:
                report_lines.append(f"覆盖的代码包括：{sample_text} 等。")
            else:
                report_lines.append(f"覆盖的代码包括：{sample_text}。")
        else:
            # Default description
            if global_improved:
                report_lines.append(f"该用例通过执行特定的指令序列触发了关键代码路径，有效提升了代码覆盖率。")
            else:
                report_lines.append(f"该用例通过执行特定的指令序列触发了目标模块的关键代码路径。")

        # Write report file
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(report_lines))
            print(f"✅ 用例报告已保存: {report_file}")
        except Exception as e:
            print(f"⚠️ 保存用例报告失败: {e}")


# =========================
# main entrance
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
        help='target module'
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
        default=False,  # The default of store_true should be False
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

    return parser.parse_args()




def write_module_report(report_file: str, module_name: str, result: dict, start_time: str, end_time: str):
    """Write module test report to log file"""
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
        for line in result.get('initial_lines', [])[:50]:  # Display up to 50 lines
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

    # Create configuration and update global annotated directory
    config = PathConfig()
    config.global_annotated_dir = args.global_annotated_dir

    # Get a list of modules (can be a single module or multiple modules)
    # If --module is specified, only that module is tested
    # Otherwise, get the list of modules with the most uncovered code based on --num
    # auto_switch is enabled by default (unless --no-auto-switch is explicitly specified)
    # If auto_switch is turned on, even if a single module is specified, it will automatically switch to the next module after completion

    # auto_switch is enabled by default (if the user does not explicitly specify --no-auto-switch)
    # Due to argparse's store_true/store_false mechanism:
    # - If the user specified --auto_switch, args.auto_switch = True
    # - If the user specified --no-auto-switch, args.auto_switch = False
    # - args.auto_switch = False (default for store_true) if neither specified by the user
    # We need to enable it by default, so check sys.argv to see if the user explicitly specified --no-auto-switch
    import sys
    if '--no-auto-switch' not in sys.argv and '--auto_switch' not in sys.argv:
        # Neither explicitly enabled nor explicitly disabled by the user, enabled by default
        args.auto_switch = True
        print(f"ℹ️  自动切换模块模式：默认启用（如需禁用，请使用 --no-auto-switch）")

    if args.module and args.module != "auto":
        # Single module mode
        if args.auto_switch:
            # If automatic switching is turned on, first obtain the num modules with the most uncovered code
            # Then find the position of the current module in the list and start testing from that position
            all_modules = getTopUncoveredModules(num, args.coverage_filename_origin)
            if args.module in all_modules:
                # Find the position of the current module and start from that position
                start_idx = all_modules.index(args.module)
                module_list = all_modules[start_idx:]
            else:
                # If the current module is not in the list, test the current module first, then test the modules in the list
                module_list = [args.module] + all_modules
            print(f"🔄 自动切换模式：将从模块 {args.module} 开始，共 {len(module_list)} 个模块")
        else:
            # Do not enable automatic switching and only test specified modules
            module_list = [args.module]
    else:
        # Automatic selection mode: Get num modules with the most uncovered code
        module_list = getTopUncoveredModules(num, args.coverage_filename_origin)

    # Maximum number of attempts per module
    max_iterations_per_module = args.max_iterations

    print(f"=" * 60)
    print(f"🚀 启动 ChipFuzzer 覆盖率提升工具")
    print(f"   待测模块列表: {module_list}")
    print(f"   每模块最大尝试次数: {max_iterations_per_module}")
    print(f"   使用模型: {model}")
    print(f"   运行模式: {run_mode} ({'继续累积覆盖率' if run_mode == 'continue' else '创建新的覆盖率文件'})")
    print(f"   SPEC 文件分析: {'启用' if args.use_spec else '禁用'}")
    print(f"   全局 annotated 目录: {config.global_annotated_dir}")
    print(f"   累积覆盖率文件: {config.sum_dat_file}")
    print(f"=" * 60)

    # Create report file
    report_file = f"/root/ChipFuzzer_cursor/GJ_log/module_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    os.makedirs(os.path.dirname(report_file), exist_ok=True)

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"ChipFuzzer 多模块测试报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"模块列表: {module_list}\n")
        f.write(f"运行模式: {run_mode}\n")
        f.write(f"每模块最大尝试次数: {max_iterations_per_module}\n")
        f.write(f"\n")

    # Create a global coverage manager (all modules share the same instance to ensure consistent baselines)
    global_coverage_manager = GlobalCoverageManager(
        project_root=config.project_root,
        annotated_dir=config.global_annotated_dir,
        sum_dat_file=config.sum_dat_file
    )

    # Process coverage files based on run mode
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

    # Multi-module test loop
    all_results = []

    # Initialize the global statistics file path (for real-time saving)
    stats_file_path = f"/root/ChipFuzzer_cursor/GJ_log/statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # Global dictionary: stores statistics of running modules (for real-time saving)
    # Format: {module_name: {"statistics": session.statistics, "module_name": module_name}}
    running_modules_stats = {}

    def save_statistics_realtime():
        """Save statistics to JSON files in real time (including completed and running modules)"""
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

            # 1. Add completed module statistics
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

            # 2. Add running module statistics (updated in real time)
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

            # Save to JSON file (named with timestamp for historical convenience)
            with open(stats_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_statistics, f, ensure_ascii=False, indent=2)

            # At the same time, write a copy according to run_id, so that the statistics API can accurately match the current task and avoid reading the wrong file "successfully covering the number of cases"
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
        print(f"# Start testing module [{idx+1}/{len(module_list)}]: {module_name}")
        print(f"{'#'*60}")

        # Construct coverage file path for current module
        Coverage_filename_origin = args.coverage_filename_origin + module_name + ".sv"
        Coverage_filename_later = args.coverage_filename_later + module_name + ".sv"

        # Check if module file exists
        if not os.path.exists(Coverage_filename_origin):
            print(f"⚠️ 模块文件不存在: {Coverage_filename_origin}，跳过")
            continue

        module_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            # Create a module testing session (passing in the shared global coverage manager and spec switch)
            print(f"🔧 正在初始化模块 [{module_name}] 的测试会话...")
            session = ModuleCoverageSession(
                module_name, config,
                Coverage_filename_origin, Coverage_filename_later,
                model,
                global_coverage_manager=global_coverage_manager,  # Share the same instance
                use_spec=args.use_spec  # Get from command line parameters
            )

            # Run existing successful use cases first (this may take longer, especially if there are multiple use cases)
            # Design description:
            # - Existing successful use cases (regardless of Fresh or Continue mode) are not run by default to save time
            # - Can be enabled explicitly via the --run_existing_seeds parameter
            if args.run_existing_seeds:
                mode_desc = "Fresh 模式" if run_mode == 'fresh' else "Continue 模式"
                print(f"🔄 [{mode_desc}] 开始运行模块 [{module_name}] 的已有成功用例（--run_existing_seeds 已启用）...")
                print(f"   注意：这可能需要较长时间，特别是如果有多个用例")
                session.run_existing_success_elfs()
                print(f"✅ 模块 [{module_name}] 的已有成功用例处理完成")
            else:
                # By default, you skip running existing use cases and start LLM generation directly, saving time.
                print(f"⏭️  跳过运行已有成功用例（默认行为，如需运行请使用 --run_existing_seeds 参数）")

            # Check if there is any uncovered code
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
                # Register the statistics of the current module to the global dictionary (for real-time saving)
                running_modules_stats[module_name] = {
                    "statistics": session.statistics,
                    "module_name": module_name
                }
                # Save once now (make sure the file exists)
                save_statistics_realtime()

                # Run the LLM loop (passing in the save function and statistics dictionary reference for periodic saves)
                result = session.run_llm_loop(
                    max_iterations=max_iterations_per_module,
                    save_stats_callback=save_statistics_realtime  # Pass in the save callback function
                )

                # After the module is completed, it is removed from the running dictionary
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

        # Record results
        result["module_name"] = module_name
        # Add statistics to results
        if hasattr(session, 'statistics'):
            result["statistics"] = session.statistics
        all_results.append(result)

        # write report
        write_module_report(report_file, module_name, result, module_start_time, module_end_time)

        # Save statistical data in real time (save once after each module is completed)
        save_statistics_realtime()

        # Print current module test summary
        print(f"\n📊 模块 [{module_name}] 测试摘要:")
        print(f"   状态: {result['status']}")
        print(f"   执行次数: {result['iterations']}")
        print(f"   覆盖率变化: {result['initial_uncovered']} → {result['final_uncovered']} (减少 {result['covered_count']} 行)")

    # final summary
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

    # Show final total coverage
    global_coverage_manager.print_total_coverage("最终总覆盖率")
    global_coverage_manager.print_module_group_stats("L2")

    # Finally save the statistics to a JSON file (using the file path saved in real time)
    # Note: The statistical data has been saved in real time after each module is completed. This is just the final confirmation of saving.
    save_statistics_realtime()

    # Read final statistics for printing
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
