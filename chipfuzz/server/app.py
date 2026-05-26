from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ChipFuzzer Web API", version="0.1.0")

# 添加 CORS 支持，允许所有来源访问 API（包括 file:// 协议）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=False,  # 使用 * 时不能设置 credentials
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 路径配置（可通过环境变量覆盖）
# ============================================================

# 项目根目录（ChipFuzzer_cursor 所在位置）
BASE_DIR = Path(os.environ.get("CHIPFUZZER_BASE", "/root/ChipFuzzer_cursor")).resolve()
# 确保可导入项目内模块（如 getmodulecoverstate）
import sys
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 运行记录目录
RUNS_DIR = Path(os.environ.get("CHIPFUZZER_RUNS", str(BASE_DIR / "runs"))).resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# 覆盖率缓存（避免频繁执行 genhtml）
coverage_cache = {
    "data": None,
    "mtime": 0,
}

# 后台脚本和 Python 路径
BACKEND_SCRIPT = os.environ.get("CHIPFUZZER_BACKEND_SCRIPT", "xiangshan_fuzzing.py")
PYTHON_BIN = os.environ.get("CHIPFUZZER_PYTHON", "python")  # 使用系统默认 Python

# XiangShan 项目目录（用于覆盖率统计）
COVERAGE_DIR = Path(os.environ.get("CHIPFUZZER_COVERAGE_DIR", "/root/XiangShan")).resolve()

# 成功案例目录（在 ChipFuzzer_cursor 目录下）
SUCCESS_SEED_DIR = Path("/root/ChipFuzzer_cursor/GJ_Success_Seed")

# 日志目录
LOG_DIR = Path("/root/ChipFuzzer_cursor/GJ_log")

# 统计数据目录
STATS_DIR = Path("/root/ChipFuzzer_cursor/GJ_log")


def _run_log_path(run_id: str) -> Path:
    # run_id 作为文件名前缀，保存到日志目录
    safe = run_id.replace("\\", "_").replace("/", "_").strip()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{safe}.log"

def _run_pid_path(run_id: str) -> Path:
    safe = run_id.replace("\\", "_").replace("/", "_").strip()
    return RUNS_DIR / safe / "pid"

def _run_meta_path(run_id: str) -> Path:
    safe = run_id.replace("\\", "_").replace("/", "_").replace("..", "_").strip()
    return RUNS_DIR / safe / "meta.json"


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class StartRunReq(BaseModel):
    module: str = "Bku"
    start_module_index: Optional[int] = None  # 从第 N 个模块开始（1=第一个），不传或 0 表示从头
    model: str = "qwen3:235b"
    # origin: 用于读取初始未覆盖代码（基线）
    coverage_filename_origin: str = "/root/XiangShan/logs/annotated/"
    # later: 用于单次测试后的覆盖率检查
    coverage_filename_later: str = "/root/XiangShan/logs2/annotated/"
    # global: 用于累积全局覆盖率
    global_annotated_dir: str = "/root/XiangShan/logs_global/annotated"
    mode: str = "continue"  # continue 或 fresh
    num: int = 100  # 模块索引或自动模式下的模块数量
    max_iterations: int = 13  # 每模块最大尝试次数
    auto_switch: bool = True  # 是否自动切换模块（默认开启）
    use_spec: bool = False  # 是否使用 SPEC 文件分析
    run_existing_seeds: bool = False  # 是否运行已有成功用例
    llm_report: bool = False  # 是否使用 LLM 生成用例报告（默认不写）

# 记录当前运行模式，用于判断是否显示旧覆盖率
current_run_mode = {"mode": "continue", "fresh_start_time": 0}

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/success-seeds")
def success_seeds() -> dict:
    """
    获取成功案例统计信息
    统计 GJ_Success_Seed 目录下的文件数量
    """
    if not SUCCESS_SEED_DIR.exists():
        SUCCESS_SEED_DIR.mkdir(parents=True, exist_ok=True)
        return {"count": 0, "files": []}
    
    # 统计 .S 和 .asm 文件
    files = [
        f.name for f in SUCCESS_SEED_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in ('.s', '.asm', '.S')
    ]
    
    return {
        "count": len(files),
        "files": sorted(files, reverse=True)[:20]  # 只返回最近 20 个文件名
    }


@app.get("/api/runs")
def list_runs() -> dict:
    runs = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.iterdir(), reverse=True):
            if p.is_dir():
                runs.append({"runId": p.name})
    return {"runs": runs}


# 默认 annotated 目录（与启动任务时的 coverage_filename_origin 一致）
DEFAULT_ANNOTATED_DIR = os.environ.get(
    "CHIPFUZZER_ANNOTATED_DIR",
    "/root/XiangShan/logs/annotated"
)


@app.get("/api/top-uncovered-modules")
def get_top_uncovered_modules(
    num: int = Query(100, ge=1, le=200, description="返回前 N 个模块"),
    annotated_dir: Optional[str] = Query(None, description="annotated 目录，不传则用默认"),
) -> dict:
    """
    获取未覆盖代码最多的模块列表，用于前端「起始模块」下拉。
    开启自动切换时，任务会从所选模块开始验证，前面的模块会跳过。
    返回: { "modules": [ {"rank": 1, "module": "LogPerfEndpoint", "uncovered": 41413}, ... ] }
    """
    try:
        from getmodulecoverstate import getTopUncoveredModulesWithCounts
        dir_path = annotated_dir or DEFAULT_ANNOTATED_DIR
        if not os.path.isdir(dir_path):
            return {"modules": [], "error": f"目录不存在: {dir_path}"}
        rows = getTopUncoveredModulesWithCounts(num, dir_path)
        modules = [
            {"rank": i + 1, "module": name, "uncovered": count}
            for i, (name, count) in enumerate(rows)
        ]
        return {"modules": modules}
    except Exception as e:
        import traceback
        return {"modules": [], "error": str(e), "detail": traceback.format_exc()}


@app.get("/api/recent-assembly-codes")
def get_recent_assembly_codes(limit: int = Query(10, ge=1, le=50)) -> dict:
    """
    获取最近生成的汇编代码片段（关键部分）
    返回最近 N 个 .S 文件的关键代码（前5行+后5行）
    同时扫描 testcase/ 和 all_seed/ 两个目录
    """
    try:
        # 扫描两个目录
        search_dirs = [
            Path("/root/XiangShan/testcase"),
            Path("/root/XiangShan/all_seed")
        ]
        
        # 获取所有 .S 文件，按修改时间排序
        asm_files = []
        for testcase_dir in search_dirs:
            if not testcase_dir.exists():
                continue
            for f in testcase_dir.glob("*.S"):
                try:
                    asm_files.append({
                        "path": str(f),
                        "name": f.name,
                        "mtime": f.stat().st_mtime
                    })
                except Exception as e:
                    print(f"⚠️ 读取文件信息失败 {f}: {e}")
                    continue
        
        if not asm_files:
            return {"codes": [], "error": "未找到 .S 文件"}
        
        # 按修改时间倒序排列，取最近 N 个
        asm_files.sort(key=lambda x: x["mtime"], reverse=True)
        asm_files = asm_files[:limit]
        
        result = []
        for item in asm_files:
            try:
                with open(item["path"], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip()
                
                if not content:
                    continue
                
                # 提取关键代码（前10行+后10行，增加信息量）
                lines = [l for l in content.split('\n') if l.strip()]
                if len(lines) <= 20:
                    key_code = content
                else:
                    head = '\n'.join(lines[:10])
                    tail = '\n'.join(lines[-10:])
                    key_code = f"{head}\n.....\n{tail}"
                
                result.append({
                    "name": item["name"],
                    "path": item["path"],
                    "key_code": key_code,
                    "mtime": item["mtime"]
                })
            except Exception as e:
                print(f"⚠️ 读取文件内容失败 {item['path']}: {e}")
                continue
        
        return {"codes": result, "count": len(result)}
    except Exception as e:
        import traceback
        error_msg = f"获取汇编代码失败: {str(e)}\n{traceback.format_exc()}"
        print(f"❌ {error_msg}")
        return {"codes": [], "error": error_msg}


@app.get("/api/files/read")
def read_file(path: str = Query(..., description="文件路径")) -> dict:
    """
    安全读取文件内容（仅允许读取指定目录下的文件）
    允许的目录：
    - /root/XiangShan/testcase/  (汇编文件)
    - /root/ChipFuzzer_cursor/LLMoutput/  (LLM 输出文件)
    """
    try:
        file_path = Path(path).resolve()
        
        # 安全检查：只允许读取指定目录
        allowed_dirs = [
            Path("/root/XiangShan/testcase").resolve(),
            Path("/root/XiangShan/all_seed").resolve(),  # 添加 all_seed 目录
            Path("/root/ChipFuzzer_cursor/LLMoutput").resolve(),
            Path("/root/ChipFuzzer/LLMoutput").resolve(),  # 兼容旧路径
        ]
        
        is_allowed = False
        file_path_str = str(file_path)
        for allowed_dir in allowed_dirs:
            allowed_dir_str = str(allowed_dir)
            # 确保路径以目录路径开头（后面跟 / 或者是完全匹配）
            if file_path_str == allowed_dir_str or file_path_str.startswith(allowed_dir_str + '/'):
                is_allowed = True
                break
        
        if not is_allowed:
            raise HTTPException(status_code=403, detail=f"不允许读取该路径: {path}")
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"不是文件: {path}")
        
        # 限制文件大小（最大 1MB）
        if file_path.stat().st_size > 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大（超过 1MB）")
        
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        return {
            "path": str(file_path),
            "content": content,
            "size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {str(e)}")

@app.post("/api/runs/start")
def start_run(req: StartRunReq) -> dict:
    """
    启动后台程序：
      python xiangshan_fuzzing.py --num <num> --module <module> --model <model> ...

    产物：
      日志: /root/ChipFuzzer/GJ_log/<runId>.log
      PID:  /root/ChipFuzzer_cursor/runs/<runId>/pid
    """
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = _run_log_path(run_id)
    
    # 记录运行模式
    current_run_mode["mode"] = req.mode
    if req.mode == "fresh":
        current_run_mode["fresh_start_time"] = time.time()
        # 清除覆盖率缓存
        coverage_cache["data"] = None
        coverage_cache["mtime"] = 0
    
    # 创建任务专属的 .dat 文件
    dat_file_path = RUNS_DIR / run_id / f"{run_id}.dat"
    dat_file_path.write_text(f"runId: {run_id}\n", encoding="utf-8")

    # 构建完整命令行参数
    cmd = [
        PYTHON_BIN,
        BACKEND_SCRIPT,
        "--module", req.module,
        "--model", req.model,
    ]
    if req.start_module_index is not None and req.start_module_index >= 1:
        cmd.extend(["--start-index", str(req.start_module_index)])
    cmd.extend([
        "--coverage_filename_origin", req.coverage_filename_origin,
        "--coverage_filename_later", req.coverage_filename_later,
        "--global_annotated_dir", req.global_annotated_dir,
        "--mode", req.mode,
        "--max_iterations", str(req.max_iterations),
        "--num", str(req.num),
        "--dat", str(dat_file_path),
    ])

    # 如果启用自动切换模块
    if req.auto_switch:
        cmd.append("--auto_switch")
    
    # 如果启用 SPEC 文件分析
    if req.use_spec:
        cmd.append("--use_spec")
    
    # 如果启用运行已有成功用例
    if req.run_existing_seeds:
        cmd.append("--run_existing_seeds")

    # 如果启用 LLM 生成用例报告
    if req.llm_report:
        cmd.append("--llm-report")

    try:
        with log_path.open("ab", buffering=0) as out:
            p = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"启动失败：{e}") from e

    _run_pid_path(run_id).write_text(str(p.pid), encoding="utf-8")
    return {"runId": run_id, "pid": p.pid, "cmd": cmd}


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    pid_path = _run_pid_path(run_id)
    if not pid_path.exists():
        raise HTTPException(status_code=404, detail="pid not found")
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid pid file") from e

    if not _is_pid_running(pid):
        return {"runId": run_id, "stopped": True, "alreadyStopped": True}

    # 先温和停止进程组
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"stop failed: {e}") from e

    return {"runId": run_id, "stopped": True}


@app.get("/api/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    log_path = _run_log_path(run_id)
    pid_path = _run_pid_path(run_id)
    if not log_path.exists() and not pid_path.exists():
        return {"runId": run_id, "state": "unknown"}

    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            pid = None

    running = _is_pid_running(pid) if pid else False

    # 简化版状态判定：从日志尾部猜测（可按你的真实输出改进）
    tail = ""
    if log_path.exists():
        try:
            tail = log_path.read_text(errors="ignore")[-6000:]
        except Exception:
            tail = ""

    state = "running" if running else "done"
    if "CRASH" in tail or "panic" in tail or "ASSERT" in tail:
        state = "crashed"
    if "DONE" in tail or "FINISH" in tail or "completed" in tail:
        state = "done"
    if not tail and not running:
        state = "unknown"
    return {"runId": run_id, "state": state, "pid": pid}


@app.get("/api/runs/{run_id}/coverage")
def run_coverage(run_id: str) -> dict:
    """
    获取总体覆盖率信息
    直接从 sum_gj.dat 生成，确保数据一致性
    """
    sum_dat_path = COVERAGE_DIR / "sum_gj.dat"
    coverage_info_path = COVERAGE_DIR / "coverage.info"
    
    # 检查 sum_gj.dat 是否存在（这是累积覆盖率的唯一来源）
    if not sum_dat_path.exists() or sum_dat_path.stat().st_size == 0:
        # 检查是否是 Fresh 模式：sum_gj.dat 不存在且 annotated 目录为空
        annotated_dir = COVERAGE_DIR / "logs_global" / "annotated"
        is_fresh_mode = False
        if annotated_dir.exists():
            import glob
            sv_files = glob.glob(str(annotated_dir / "*.sv"))
            is_fresh_mode = len(sv_files) == 0
        else:
            # annotated 目录不存在，也认为是 Fresh 模式
            is_fresh_mode = True
        
        return {
            "coverage_percentage": 0.0,
            "total_covered_lines": 0,
            "total_lines": 0,
            "status": "fresh_mode" if is_fresh_mode else "no_data",
            "message": "Fresh 模式：等待首次测试数据" if is_fresh_mode else "暂无覆盖率数据（sum_gj.dat 不存在）",
        }
    
    # 检查文件修改时间
    current_mtime = sum_dat_path.stat().st_mtime
    
    # 检查文件修改时间，如果未变化则返回缓存
    if coverage_cache["data"] and coverage_cache["mtime"] == current_mtime:
        return coverage_cache["data"]
    
    try:
        import re
        
        # 先更新 coverage.info（从 sum_gj.dat 生成）
        update_result = subprocess.run(
            ["verilator_coverage", "-write-info", "coverage.info", str(sum_dat_path)],
            cwd=str(COVERAGE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if update_result.returncode != 0:
            return {
                "coverage_percentage": 0.0,
                "total_covered_lines": 0,
                "total_lines": 0,
                "status": "error",
                "message": f"更新 coverage.info 失败: {update_result.stderr}",
            }
        
        # 使用 genhtml 获取覆盖率百分比
        result = subprocess.run(
            ["genhtml", "coverage.info", "--output-directory", "coverage_gj"],
            cwd=str(COVERAGE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        output = result.stdout + result.stderr
        
        # 解析 "Overall coverage rate: lines......: 72.2% (463483 of 642121 lines)"
        match = re.search(r'lines\.+:\s*([\d.]+)%\s*\((\d+)\s+of\s+(\d+)\s+lines\)', output)
        
        if match:
            percentage = float(match.group(1))
            covered = int(match.group(2))
            total = int(match.group(3))
            data = {
                "coverage_percentage": percentage,
                "total_covered_lines": covered,
                "total_lines": total,
                "sum_dat_mtime": current_mtime,
            }
            # 更新缓存（只有成功解析时才更新）
            coverage_cache["data"] = data
            coverage_cache["mtime"] = current_mtime
            return data
        else:
            # 如果解析失败，检查是否有缓存数据
            if coverage_cache["data"] and coverage_cache["data"].get("coverage_percentage", 0) > 0:
                # 有有效缓存，返回缓存数据并记录警告
                print(f"⚠️ genhtml 输出解析失败，使用缓存数据: {coverage_cache['data']['coverage_percentage']:.2f}%")
                print(f"   genhtml 输出（前500字符）: {output[:500]}")
                return {
                    **coverage_cache["data"],
                    "status": "parse_error_using_cache",
                    "warning": "genhtml 输出解析失败，使用上次有效值"
                }
            else:
                # 没有有效缓存，返回错误状态（但不返回0，避免误导）
                print(f"⚠️ genhtml 输出解析失败，且无有效缓存数据")
                print(f"   genhtml 输出（前500字符）: {output[:500]}")
                return {
                    "coverage_percentage": 0.0,
                    "total_covered_lines": 0,
                    "total_lines": 0,
                    "status": "parse_error",
                    "message": "genhtml 输出解析失败，且无历史数据"
                }
        
    except subprocess.TimeoutExpired:
        # genhtml 执行超时，但如果有缓存就返回缓存的数据
        if coverage_cache["data"]:
            return coverage_cache["data"]
        raise HTTPException(status_code=408, detail="genhtml 执行超时且无缓存数据")
    except FileNotFoundError:
        # genhtml 命令不存在，尝试直接返回缓存或默认值
        if coverage_cache["data"]:
            return coverage_cache["data"]
        return {
            "coverage_percentage": 0.0,
            "total_covered_lines": 0,
            "total_lines": 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取覆盖率失败: {str(e)}")


# L2 模块组配置
L2_MODULES = [
    "L2Cache",
    "L2DataStorage",
    "L2DataStorage_1",
    "L2Directory",
    "L2Directory_1",
    "L2TLB",
    "L2TLBWrapper",
    "L2TlbPrefetch",
    "L2Top",
]

def get_module_coverage_stats(annotated_dir: Path, module_name: str) -> dict:
    """获取单个模块的覆盖率统计"""
    sv_file = annotated_dir / f"{module_name}.sv"
    
    if not sv_file.exists():
        return {"exists": False, "module": module_name}
    
    total_lines = 0
    covered_lines = 0
    uncovered_lines = 0
    
    try:
        with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                stripped = line.strip()
                # 跳过空行和纯注释行
                if not stripped or stripped.startswith('//'):
                    continue
                
                # 检查覆盖率标记（可能在行首，也可能在行中）
                # Verilator 覆盖率标记格式：%000000 或 %000001 等
                if '%' in stripped:
                    # 提取覆盖率标记（格式：%后跟6位数字）
                    import re
                    coverage_markers = re.findall(r'%(\d{6})', stripped)
                    
                    if coverage_markers:
                        total_lines += 1
                        # 检查是否有非零的覆盖率标记（表示已覆盖）
                        has_covered = any(marker != '000000' for marker in coverage_markers)
                        
                        if has_covered:
                            covered_lines += 1
                        else:
                            uncovered_lines += 1
        
        coverage_rate = (covered_lines / total_lines * 100) if total_lines > 0 else 0
        
        return {
            "exists": True,
            "module": module_name,
            "total_lines": total_lines,
            "covered_lines": covered_lines,
            "uncovered_lines": uncovered_lines,
            "coverage_rate": round(coverage_rate, 2),
        }
    except Exception as e:
        return {"exists": False, "module": module_name, "error": str(e)}


@app.get("/api/run-mode")
def get_run_mode() -> dict:
    """获取当前运行模式"""
    return {
        "mode": current_run_mode["mode"],
        "fresh_start_time": current_run_mode["fresh_start_time"],
    }


def parse_coverage_info_for_modules(coverage_info_path: Path, module_names: List[str]) -> dict:
    """
    直接从 coverage.info 文件解析指定模块的覆盖率统计
    这样可以确保与总体覆盖率使用相同的数据源
    
    返回:
        {
            "module_name": {
                "exists": bool,
                "total_lines": int,
                "covered_lines": int,
                "uncovered_lines": int,
                "coverage_rate": float,
            }
        }
    """
    result = {name: {
        "exists": False,
        "total_lines": 0,
        "covered_lines": 0,
        "uncovered_lines": 0,
        "coverage_rate": 0.0,
        "module": name,
    } for name in module_names}
    
    if not coverage_info_path.exists():
        return result
    
    current_file = None
    current_module = None
    file_lines = {}  # 记录每个文件的行覆盖情况
    
    try:
        with open(coverage_info_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # 解析源文件路径 (SF:)
                if line.startswith('SF:'):
                    file_path = line[3:].strip()
                    file_name = Path(file_path).name
                    current_file = file_path
                    current_module = None
                    
                    # 检查是否是 L2 模块文件
                    # 匹配规则：文件名完全匹配 {module_name}.sv 或路径中包含模块名
                    for module_name in module_names:
                        # 精确匹配文件名（如 L2Cache.sv）
                        if file_name == f"{module_name}.sv":
                            current_module = module_name
                            if current_file not in file_lines:
                                file_lines[current_file] = {
                                    "module": module_name,
                                    "lines": {}
                                }
                            break
                        # 或者路径中包含模块名（处理带后缀的情况，如 L2DataStorage_1.sv）
                        elif f"/{module_name}.sv" in file_path or f"\\{module_name}.sv" in file_path:
                            current_module = module_name
                            if current_file not in file_lines:
                                file_lines[current_file] = {
                                    "module": module_name,
                                    "lines": {}
                                }
                            break
                
                # 解析行覆盖率数据 (DA:line_number,execution_count)
                elif line.startswith('DA:') and current_module and current_file:
                    try:
                        parts = line[3:].strip().split(',')
                        if len(parts) == 2:
                            line_num = int(parts[0])
                            exec_count = int(parts[1])
                            
                            if current_file not in file_lines:
                                file_lines[current_file] = {
                                    "module": current_module,
                                    "lines": {}
                                }
                            
                            file_lines[current_file]["lines"][line_num] = exec_count
                    except (ValueError, IndexError):
                        continue
        
        # 统计每个模块的覆盖率
        for file_path, file_data in file_lines.items():
            module_name = file_data["module"]
            if module_name not in result:
                continue
            
            lines_data = file_data["lines"]
            total = len(lines_data)
            covered = sum(1 for count in lines_data.values() if count > 0)
            uncovered = total - covered
            
            result[module_name]["exists"] = True
            result[module_name]["total_lines"] += total
            result[module_name]["covered_lines"] += covered
            result[module_name]["uncovered_lines"] += uncovered
        
        # 计算每个模块的覆盖率百分比
        for module_name in module_names:
            stats = result[module_name]
            if stats["total_lines"] > 0:
                stats["coverage_rate"] = round(
                    (stats["covered_lines"] / stats["total_lines"]) * 100, 2
                )
    
    except Exception as e:
        print(f"⚠️ 解析 coverage.info 失败: {e}")
    
    return result


@app.get("/api/l2-coverage")
def l2_module_coverage() -> dict:
    """
    获取 L2 模块组的覆盖率统计
    直接从 coverage.info 文件解析，确保与总体覆盖率使用相同的数据源
    """
    # 先确保 coverage.info 是最新的（从 sum_gj.dat 生成）
    sum_dat_path = COVERAGE_DIR / "sum_gj.dat"
    coverage_info_path = COVERAGE_DIR / "coverage.info"
    
    if not sum_dat_path.exists():
        return {
            "modules": {},
            "summary": {
                "total_lines": 0,
                "covered_lines": 0,
                "uncovered_lines": 0,
                "coverage_rate": 0.0,
            },
            "status": "no_data",
            "message": "sum_gj.dat 不存在",
        }
    
    # 检查是否需要更新 coverage.info
    sum_dat_mtime = sum_dat_path.stat().st_mtime
    coverage_info_mtime = coverage_info_path.stat().st_mtime if coverage_info_path.exists() else 0
    
    if not coverage_info_path.exists() or sum_dat_mtime > coverage_info_mtime:
        # 更新 coverage.info
        try:
            update_result = subprocess.run(
                ["verilator_coverage", "-write-info", "coverage.info", str(sum_dat_path)],
                cwd=str(COVERAGE_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if update_result.returncode != 0:
                return {
                    "modules": {},
                    "summary": {
                        "total_lines": 0,
                        "covered_lines": 0,
                        "uncovered_lines": 0,
                        "coverage_rate": 0.0,
                    },
                    "status": "error",
                    "message": f"更新 coverage.info 失败: {update_result.stderr}",
                }
        except Exception as e:
            return {
                "modules": {},
                "summary": {
                    "total_lines": 0,
                    "covered_lines": 0,
                    "uncovered_lines": 0,
                    "coverage_rate": 0.0,
                },
                "status": "error",
                "message": f"更新 coverage.info 异常: {str(e)}",
            }
    
    # 从 coverage.info 解析 L2 模块统计
    modules_stats = parse_coverage_info_for_modules(coverage_info_path, L2_MODULES)
    
    # 计算汇总统计
    total_lines = sum(s["total_lines"] for s in modules_stats.values())
    covered_lines = sum(s["covered_lines"] for s in modules_stats.values())
    uncovered_lines = sum(s["uncovered_lines"] for s in modules_stats.values())
    overall_rate = (covered_lines / total_lines * 100) if total_lines > 0 else 0
    
    return {
        "modules": modules_stats,
        "summary": {
            "total_lines": total_lines,
            "covered_lines": covered_lines,
            "uncovered_lines": uncovered_lines,
            "coverage_rate": round(overall_rate, 2),
        },
        "status": "ok",
    }


@app.get("/api/global-stats")
def global_stats() -> dict:
    """
    获取全局覆盖率统计信息（从全局累积目录读取）
    """
    annotated_dir = COVERAGE_DIR / "logs_global" / "annotated"
    sum_dat_file = COVERAGE_DIR / "sum_gj.dat"
    
    result = {
        "sum_dat_exists": sum_dat_file.exists(),
        "annotated_dir": str(annotated_dir),
    }
    
    if sum_dat_file.exists():
        stat = sum_dat_file.stat()
        result["sum_dat_size"] = stat.st_size
        result["sum_dat_mtime"] = stat.st_mtime
    
    # 统计总未覆盖行数
    total_uncovered = 0
    if annotated_dir.exists():
        for sv_file in annotated_dir.glob("*.sv"):
            try:
                with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if '%000000' in line and 'PRINTF_COND' not in line:
                            total_uncovered += 1
            except Exception:
                pass
    
    result["total_uncovered_lines"] = total_uncovered
    
    return result


@app.get("/api/runs/{run_id}/logs")
def run_logs(run_id: str, cursor: Optional[str] = None) -> JSONResponse:
    log_path = _run_log_path(run_id)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="log not found")

    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0

    data = log_path.read_bytes()
    if start > len(data):
        start = len(data)

    chunk = data[start:]
    text = chunk.decode(errors="ignore")
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    return JSONResponse({"runId": run_id, "lines": lines, "nextCursor": str(len(data))})


@app.get("/api/runs/{run_id}/statistics")
def get_statistics(run_id: str) -> dict:
    """
    获取运行统计信息
    优先读取 statistics_<run_id>.json（当前任务专用），若无则按 run_id 内容匹配，再回退到最新文件
    """
    import json
    import logging
    
    try:
        # 1) 优先直接按 run_id 命名的文件读取（后端每次保存都会写这份，确保“成功覆盖 case 数”等与当前任务一致）
        safe_run_id = run_id.replace("\\", "_").replace("/", "_").replace("..", "_").strip()
        run_id_file = STATS_DIR / f"statistics_{safe_run_id}.json"
        if run_id_file.exists():
            with open(run_id_file, 'r', encoding='utf-8') as f:
                stats_data = json.load(f)
            summary = stats_data.get("summary", {})
            total_llm = summary.get("total_llm_generations", 0)
            total_emulator_success = summary.get("total_emulator_success", 0)
            total_coverage_improved = summary.get("total_coverage_improved", 0)
            compile_success_rate = (total_emulator_success / total_llm * 100) if total_llm > 0 else 0.0
            emulator_success_rate = compile_success_rate
            coverage_improved_rate = (total_coverage_improved / total_llm * 100) if total_llm > 0 else 0.0
            all_coverage_data = []
            for module_data in stats_data.get("modules", []):
                module_stats = module_data.get("statistics", {}) or {}
                all_coverage_data.extend(module_stats.get("coverage_data", []))
            all_coverage_data.sort(key=lambda x: x.get("timestamp", 0))
            return {
                "status": "success",
                "summary": {
                    "total_llm_generations": total_llm,
                    "total_emulator_success": total_emulator_success,
                    "total_coverage_improved": total_coverage_improved,
                    "coverage_improved_rate": round(coverage_improved_rate, 2),
                    "compile_success_rate": round(compile_success_rate, 2),
                    "emulator_success_rate": round(emulator_success_rate, 2),
                },
                "modules": [
                    {
                        "module_name": m.get("module_name", "unknown"),
                        "llm_count": (m.get("statistics") or {}).get("llm_generation_count", 0),
                        "emulator_success": (m.get("statistics") or {}).get("emulator_success_count", 0),
                    }
                    for m in stats_data.get("modules", [])
                ],
                "coverage_data": all_coverage_data[-100:],
                "debug": {"stats_file": str(run_id_file), "source": "run_id_file"},
            }
        
        # 2) 回退：按内容中的 run_id 匹配
        stats_files = sorted(STATS_DIR.glob("statistics_*.json"), reverse=True)
        if not stats_files:
            return {
                "status": "no_data",
                "message": "暂无统计数据",
                "debug": {"stats_dir": str(STATS_DIR), "files_found": 0},
            }
        
        matched_file = None
        for stats_file in stats_files:
            if stats_file.name == run_id_file.name:
                continue
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                    if file_data.get("run_id", "") == run_id:
                        matched_file = stats_file
                        break
            except Exception:
                continue
        
        # 未找到当前 run_id 的统计文件时，不退回“最新文件”（避免用其他任务的 0 覆盖本任务从日志得到的值）
        if matched_file is None:
            logging.info(f"[统计API] 未找到 run_id={run_id} 的统计文件，返回 no_data")
            return {
                "status": "no_data",
                "message": "当前任务暂无统计数据（可能尚未写入），页面将保留日志中的实时数据",
                "debug": {"stats_dir": str(STATS_DIR), "run_id": run_id, "files_checked": len(stats_files)},
            }
        
        logging.info(f"[统计API] 找到匹配: {matched_file}, run_id={run_id}")
        
        # 读取统计文件
        with open(matched_file, 'r', encoding='utf-8') as f:
            stats_data = json.load(f)
        
        # 计算总体统计
        summary = stats_data.get("summary", {})
        total_llm = summary.get("total_llm_generations", 0)
        total_emulator_success = summary.get("total_emulator_success", 0)
        total_coverage_improved = summary.get("total_coverage_improved", 0)
        
        # 调试信息：记录读取的数据
        logging.info(f"[统计API] 读取数据: total_llm={total_llm}, total_emulator_success={total_emulator_success}, total_coverage_improved={total_coverage_improved}")
        
        # 计算编译成功率（需要从日志中统计，这里先返回模拟器成功率）
        # 编译成功率 = 模拟器成功执行次数 / LLM 生成次数
        compile_success_rate = 0.0
        if total_llm > 0:
            compile_success_rate = (total_emulator_success / total_llm) * 100
        
        # 模拟器执行成功率（假设所有成功编译的都会执行模拟器）
        emulator_success_rate = compile_success_rate  # 暂时相同，后续可以从日志中更精确统计
        
        # 成功覆盖的 case 占 LLM 生成次数的比例
        coverage_improved_rate = 0.0
        if total_llm > 0:
            coverage_improved_rate = (total_coverage_improved / total_llm) * 100
        
        # 获取覆盖率数据
        all_coverage_data = []
        for module_data in stats_data.get("modules", []):
            module_stats = module_data.get("statistics", {})
            if module_stats:
                coverage_data = module_stats.get("coverage_data", [])
                all_coverage_data.extend(coverage_data)
        
        # 按时间排序
        all_coverage_data.sort(key=lambda x: x.get("timestamp", 0))
        
        result = {
            "status": "success",
            "summary": {
                "total_llm_generations": total_llm,
                "total_emulator_success": total_emulator_success,
                "total_coverage_improved": total_coverage_improved,
                "coverage_improved_rate": round(coverage_improved_rate, 2),
                "compile_success_rate": round(compile_success_rate, 2),
                "emulator_success_rate": round(emulator_success_rate, 2),
            },
            "modules": [
                {
                    "module_name": m.get("module_name", "unknown"),
                    "llm_count": (m.get("statistics") or {}).get("llm_generation_count", 0),
                    "emulator_success": (m.get("statistics") or {}).get("emulator_success_count", 0),
                }
                for m in stats_data.get("modules", [])
            ],
            "coverage_data": all_coverage_data[-100:],  # 只返回最近100个数据点
            "debug": {
                "stats_file": str(matched_file),
                "files_found": len(stats_files),
                "modules_count": len(stats_data.get("modules", [])),
            }
        }
        
        return result
    except Exception as e:
        import traceback
        error_msg = f"读取统计数据失败: {str(e)}"
        logging.error(f"[统计API] {error_msg}\n{traceback.format_exc()}")
        return {
            "status": "error",
            "message": error_msg,
            "debug": {
                "error_type": type(e).__name__,
                "stats_dir": str(STATS_DIR),
            }
        }


@app.get("/api/runs/{run_id}/stream")
async def run_stream(run_id: str, request: Request) -> StreamingResponse:
    """
    SSE:
      event: log
      data: <line>

    说明：
    - 这是最小实现：从日志文件尾部增量读取
    - 生产建议：加鉴权 + Nginx 同域反代；不要把 /api 裸奔到公网
    """

    log_path = _run_log_path(run_id)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="log not found")

    async def gen():
        # 从文件开头开始，发送完整日志历史
        pos = 0
        yield "event: status\ndata: {\"state\":\"running\"}\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                yield "event: status\ndata: {\"state\":\"unknown\"}\n\n"
                break

            if size < pos:
                # 文件被重写
                pos = 0

            if size > pos:
                with log_path.open("rb") as f:
                    f.seek(pos)
                    data = f.read(size - pos)
                    pos = size

                text = data.decode(errors="ignore")
                for ln in text.splitlines():
                    # SSE 需要逐行推送
                    yield f"event: log\ndata: {ln}\n\n"

            await asyncio.sleep(0.35)

    return StreamingResponse(gen(), media_type="text/event-stream")

