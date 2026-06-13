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

# Add CORS support to allow all origins to access the API (including file:// protocol)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all sources
    allow_credentials=False,  # Credentials cannot be set when using *
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Path configuration (can be overridden through environment variables)
# ============================================================

# Project root directory (where ChipFuzzer_cursor is located)
BASE_DIR = Path(os.environ.get("CHIPFUZZER_BASE", "/root/ChipFuzzer_cursor")).resolve()

# Run record directory
RUNS_DIR = Path(os.environ.get("CHIPFUZZER_RUNS", str(BASE_DIR / "runs"))).resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Coverage caching (avoids frequent execution of genhtml)
coverage_cache = {
    "data": None,
    "mtime": 0,
}

# Background scripts and Python paths
BACKEND_SCRIPT = os.environ.get("CHIPFUZZER_BACKEND_SCRIPT", "xiangshan_fuzzing.py")
PYTHON_BIN = os.environ.get("CHIPFUZZER_PYTHON", "python")  # Use system default Python

# XiangShan project directory (for coverage statistics)
COVERAGE_DIR = Path(os.environ.get("CHIPFUZZER_COVERAGE_DIR", "/root/XiangShan")).resolve()

# Success case directory (under the ChipFuzzer_cursor directory)
SUCCESS_SEED_DIR = Path("/root/ChipFuzzer_cursor/GJ_Success_Seed")

# Log directory
LOG_DIR = Path("/root/ChipFuzzer_cursor/GJ_log")

# Statistics directory
STATS_DIR = Path("/root/ChipFuzzer_cursor/GJ_log")


def _run_log_path(run_id: str) -> Path:
    # run_id is used as the file name prefix and is saved to the log directory
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
    model: str = "qwen3:235b"
    # origin: used to read the initial uncovered code (baseline)
    coverage_filename_origin: str = "/root/XiangShan/logs/annotated/"
    # later: used for coverage check after a single test
    coverage_filename_later: str = "/root/XiangShan/logs2/annotated/"
    # global: used to accumulate global coverage
    global_annotated_dir: str = "/root/XiangShan/logs_global/annotated"
    mode: str = "continue"  # continue or fresh
    num: int = 100  # Module index or number of modules in automatic mode
    max_iterations: int = 13  # Maximum number of attempts per module
    auto_switch: bool = True  # Whether to automatically switch modules (enabled by default)
    use_spec: bool = False  # Whether to use SPEC file analysis
    run_existing_seeds: bool = False  # Whether to run existing successful use cases

# Record the current running mode and use it to determine whether to display the old coverage
current_run_mode = {"mode": "continue", "fresh_start_time": 0}

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/success-seeds")
def success_seeds() -> dict:
    """
    Get statistics on successful cases
    Count the number of files in the GJ_Success_Seed directory
    """
    if not SUCCESS_SEED_DIR.exists():
        SUCCESS_SEED_DIR.mkdir(parents=True, exist_ok=True)
        return {"count": 0, "files": []}
    
    # Statistics .S and .asm files
    files = [
        f.name for f in SUCCESS_SEED_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in ('.s', '.asm', '.S')
    ]
    
    return {
        "count": len(files),
        "files": sorted(files, reverse=True)[:20]  # Only the most recent 20 filenames are returned
    }


@app.get("/api/runs")
def list_runs() -> dict:
    runs = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.iterdir(), reverse=True):
            if p.is_dir():
                runs.append({"runId": p.name})
    return {"runs": runs}


@app.get("/api/recent-assembly-codes")
def get_recent_assembly_codes(limit: int = Query(10, ge=1, le=50)) -> dict:
    """
    Get the most recently generated assembly code snippet (critical part)
    Return the key codes of the latest N .S files (the first 5 lines + the last 5 lines)
    Scan both testcase/ and all_seed/ directories at the same time
    """
    try:
        # Scan two directories
        search_dirs = [
            Path("/root/XiangShan/testcase"),
            Path("/root/XiangShan/all_seed")
        ]
        
        # Get all .S files, sorted by modification time
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
        
        # Arrange in reverse order of modification time, taking the most recent N
        asm_files.sort(key=lambda x: x["mtime"], reverse=True)
        asm_files = asm_files[:limit]
        
        result = []
        for item in asm_files:
            try:
                with open(item["path"], 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read().strip()
                
                if not content:
                    continue
                
                # Extract key codes (first 10 lines + last 10 lines, increase the amount of information)
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
    Safely read file contents (only files in the specified directory are allowed to be read)
    Allowed directories:
    - /root/XiangShan/testcase/ (assembly file)
    - /root/ChipFuzzer_cursor/LLMoutput/ (LLM output file)
    """
    try:
        file_path = Path(path).resolve()
        
        # Security check: only allow reading of specified directories
        allowed_dirs = [
            Path("/root/XiangShan/testcase").resolve(),
            Path("/root/XiangShan/all_seed").resolve(),  # Add all_seed directory
            Path("/root/ChipFuzzer_cursor/LLMoutput").resolve(),
            Path("/root/ChipFuzzer/LLMoutput").resolve(),  # Compatible with old paths
        ]
        
        is_allowed = False
        file_path_str = str(file_path)
        for allowed_dir in allowed_dirs:
            allowed_dir_str = str(allowed_dir)
            # Make sure the path starts with the directory path (followed by / or an exact match)
            if file_path_str == allowed_dir_str or file_path_str.startswith(allowed_dir_str + '/'):
                is_allowed = True
                break
        
        if not is_allowed:
            raise HTTPException(status_code=403, detail=f"不允许读取该路径: {path}")
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"不是文件: {path}")
        
        # Limit file size (max 1MB)
        if file_path.stat().st_size > 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大（超过 1MB）")
        
        # Read file contents
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
    Start the background program:
      python xiangshan_fuzzing.py --num <num> --module <module> --model <model> ...

    product:
      Log: /root/ChipFuzzer/GJ_log/<runId>.log
      PID:  /root/ChipFuzzer_cursor/runs/<runId>/pid
    """
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = _run_log_path(run_id)
    
    # Record operating mode
    current_run_mode["mode"] = req.mode
    if req.mode == "fresh":
        current_run_mode["fresh_start_time"] = time.time()
        # Clear coverage cache
        coverage_cache["data"] = None
        coverage_cache["mtime"] = 0
    
    # Create task-specific .dat files
    dat_file_path = RUNS_DIR / run_id / f"{run_id}.dat"
    dat_file_path.write_text(f"runId: {run_id}\n", encoding="utf-8")

    # Build complete command line parameters
    cmd = [
        PYTHON_BIN,
        BACKEND_SCRIPT,
        "--module", req.module,
        "--model", req.model,
        "--coverage_filename_origin", req.coverage_filename_origin,
        "--coverage_filename_later", req.coverage_filename_later,
        "--global_annotated_dir", req.global_annotated_dir,
        "--mode", req.mode,
        "--max_iterations", str(req.max_iterations),
        "--num", str(req.num),
        "--dat", str(dat_file_path),  # Add .dat file path parameter
    ]
    
    # If automatic switching module is enabled
    if req.auto_switch:
        cmd.append("--auto_switch")
    
    # If SPEC file analysis is enabled
    if req.use_spec:
        cmd.append("--use_spec")
    
    # If enabled, there are already successful use cases running
    if req.run_existing_seeds:
        cmd.append("--run_existing_seeds")
    
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

    # Stop the process group gently first
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

    # Simplified version of status determination: guess from the end of the log (can be improved based on your real output)
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
    Get overall coverage information
    Generated directly from sum_gj.dat to ensure data consistency
    """
    sum_dat_path = COVERAGE_DIR / "sum_gj.dat"
    coverage_info_path = COVERAGE_DIR / "coverage.info"
    
    # Check if sum_gj.dat exists (this is the only source of cumulative coverage)
    if not sum_dat_path.exists() or sum_dat_path.stat().st_size == 0:
        # Check if it is Fresh mode: sum_gj.dat does not exist and the annotated directory is empty
        annotated_dir = COVERAGE_DIR / "logs_global" / "annotated"
        is_fresh_mode = False
        if annotated_dir.exists():
            import glob
            sv_files = glob.glob(str(annotated_dir / "*.sv"))
            is_fresh_mode = len(sv_files) == 0
        else:
            # The annotated directory does not exist and is also considered to be in Fresh mode.
            is_fresh_mode = True
        
        return {
            "coverage_percentage": 0.0,
            "total_covered_lines": 0,
            "total_lines": 0,
            "status": "fresh_mode" if is_fresh_mode else "no_data",
            "message": "Fresh 模式：等待首次测试数据" if is_fresh_mode else "暂无覆盖率数据（sum_gj.dat 不存在）",
        }
    
    # Check file modification time
    current_mtime = sum_dat_path.stat().st_mtime
    
    # Check the file modification time and return to the cache if it has not changed
    if coverage_cache["data"] and coverage_cache["mtime"] == current_mtime:
        return coverage_cache["data"]
    
    try:
        import re
        
        # Update coverage.info first (generated from sum_gj.dat)
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
        
        # Get coverage percentage using genhtml
        result = subprocess.run(
            ["genhtml", "coverage.info", "--output-directory", "coverage_gj"],
            cwd=str(COVERAGE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        output = result.stdout + result.stderr
        
        # Parse "Overall coverage rate: lines......: 72.2% (463483 of 642121 lines)"
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
            # Update cache (only updated if parsed successfully)
            coverage_cache["data"] = data
            coverage_cache["mtime"] = current_mtime
            return data
        else:
            # If parsing fails, check if there is cached data
            if coverage_cache["data"] and coverage_cache["data"].get("coverage_percentage", 0) > 0:
                # There is a valid cache, return the cached data and log a warning
                print(f"⚠️ genhtml 输出解析失败，使用缓存数据: {coverage_cache['data']['coverage_percentage']:.2f}%")
                print(f"   genhtml 输出（前500字符）: {output[:500]}")
                return {
                    **coverage_cache["data"],
                    "status": "parse_error_using_cache",
                    "warning": "genhtml 输出解析失败，使用上次有效值"
                }
            else:
                # There is no valid cache, and an error status is returned (but does not return 0 to avoid misleading)
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
        # The execution of genhtml times out, but if there is cache, the cached data will be returned.
        if coverage_cache["data"]:
            return coverage_cache["data"]
        raise HTTPException(status_code=408, detail="genhtml 执行超时且无缓存数据")
    except FileNotFoundError:
        # The genhtml command does not exist, try to return the cache or default value directly
        if coverage_cache["data"]:
            return coverage_cache["data"]
        return {
            "coverage_percentage": 0.0,
            "total_covered_lines": 0,
            "total_lines": 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取覆盖率失败: {str(e)}")


# L2 module group configuration
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
    """Get coverage statistics for a single module"""
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
                # Skip empty lines and plain comment lines
                if not stripped or stripped.startswith('//'):
                    continue
                
                # Check for coverage markers (maybe at the beginning of the line or in the middle of the line)
                # Verilator coverage tag format: %000000 or %000001, etc.
                if '%' in stripped:
                    # Extract coverage tags (format: % followed by 6 digits)
                    import re
                    coverage_markers = re.findall(r'%(\d{6})', stripped)
                    
                    if coverage_markers:
                        total_lines += 1
                        # Check if there is a non-zero coverage flag (indicating coverage)
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
    """Get the current running mode"""
    return {
        "mode": current_run_mode["mode"],
        "fresh_start_time": current_run_mode["fresh_start_time"],
    }


def parse_coverage_info_for_modules(coverage_info_path: Path, module_names: List[str]) -> dict:
    """
    Parse coverage statistics for a specified module directly from the coverage.info file
    This ensures that the same data source is used for overall coverage
    
    return:
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
    file_lines = {}  # Record line coverage for each file
    
    try:
        with open(coverage_info_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # Resolve source file path (SF:)
                if line.startswith('SF:'):
                    file_path = line[3:].strip()
                    file_name = Path(file_path).name
                    current_file = file_path
                    current_module = None
                    
                    # Check if it is an L2 module file
                    # Matching rules: The file name exactly matches {module_name}.sv or the path contains the module name
                    for module_name in module_names:
                        # Exact file name match (e.g. L2Cache.sv)
                        if file_name == f"{module_name}.sv":
                            current_module = module_name
                            if current_file not in file_lines:
                                file_lines[current_file] = {
                                    "module": module_name,
                                    "lines": {}
                                }
                            break
                        # Or the path contains the module name (handling the case with suffix, such as L2DataStorage_1.sv)
                        elif f"/{module_name}.sv" in file_path or f"\\{module_name}.sv" in file_path:
                            current_module = module_name
                            if current_file not in file_lines:
                                file_lines[current_file] = {
                                    "module": module_name,
                                    "lines": {}
                                }
                            break
                
                # Parse line coverage data (DA:line_number,execution_count)
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
        
        # Count the coverage of each module
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
        
        # Calculate coverage percentage for each module
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
    Get coverage statistics for L2 module group
    Parse directly from the coverage.info file, ensuring the same data source is used for overall coverage
    """
    # First make sure coverage.info is up to date (generated from sum_gj.dat)
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
    
    # Check if coverage.info needs to be updated
    sum_dat_mtime = sum_dat_path.stat().st_mtime
    coverage_info_mtime = coverage_info_path.stat().st_mtime if coverage_info_path.exists() else 0
    
    if not coverage_info_path.exists() or sum_dat_mtime > coverage_info_mtime:
        # Update coverage.info
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
    
    # Parse L2 module statistics from coverage.info
    modules_stats = parse_coverage_info_for_modules(coverage_info_path, L2_MODULES)
    
    # Calculate summary statistics
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
    Get global coverage statistics (read from the global accumulation directory)
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
    
    # Count the total number of uncovered rows
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
    Get running statistics
    Read statistics_<run_id>.json first (dedicated to the current task). If not, match according to run_id content, and then fall back to the latest file.
    """
    import json
    import logging
    
    try:
        # 1) Prioritize reading files named directly by run_id (the backend will write this file every time it is saved to ensure that the "number of successfully covered cases" is consistent with the current task)
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
        
        # 2) Fallback: Match by run_id in the content
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
        
        # When the statistics file of the current run_id is not found, the "latest file" will not be returned (to avoid overwriting the value obtained by this task from the log with 0 from other tasks)
        if matched_file is None:
            logging.info(f"[统计API] 未找到 run_id={run_id} 的统计文件，返回 no_data")
            return {
                "status": "no_data",
                "message": "当前任务暂无统计数据（可能尚未写入），页面将保留日志中的实时数据",
                "debug": {"stats_dir": str(STATS_DIR), "run_id": run_id, "files_checked": len(stats_files)},
            }
        
        logging.info(f"[统计API] 找到匹配: {matched_file}, run_id={run_id}")
        
        # Read statistics file
        with open(matched_file, 'r', encoding='utf-8') as f:
            stats_data = json.load(f)
        
        # Calculate overall statistics
        summary = stats_data.get("summary", {})
        total_llm = summary.get("total_llm_generations", 0)
        total_emulator_success = summary.get("total_emulator_success", 0)
        total_coverage_improved = summary.get("total_coverage_improved", 0)
        
        # Debug information: record the data read
        logging.info(f"[统计API] 读取数据: total_llm={total_llm}, total_emulator_success={total_emulator_success}, total_coverage_improved={total_coverage_improved}")
        
        # Calculate the compilation success rate (statistics need to be collected from the log, here first return the simulator success rate)
        # Compilation success rate = number of successful simulator executions / number of LLM generation times
        compile_success_rate = 0.0
        if total_llm > 0:
            compile_success_rate = (total_emulator_success / total_llm) * 100
        
        # Simulator execution success rate (assuming that all successful compilations will execute the simulator)
        emulator_success_rate = compile_success_rate  # The same for now, more accurate statistics can be obtained from the log later.
        
        # The ratio of successfully covered cases to the number of LLM generation times
        coverage_improved_rate = 0.0
        if total_llm > 0:
            coverage_improved_rate = (total_coverage_improved / total_llm) * 100
        
        # Get coverage data
        all_coverage_data = []
        for module_data in stats_data.get("modules", []):
            module_stats = module_data.get("statistics", {})
            if module_stats:
                coverage_data = module_stats.get("coverage_data", [])
                all_coverage_data.extend(coverage_data)
        
        # Sort by time
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
            "coverage_data": all_coverage_data[-100:],  # Only return the most recent 100 data points
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

    illustrate:
    - This is the minimal implementation: incremental reading from the tail of the log file
    - Production suggestions: Add authentication + Nginx same domain reverse generation; do not run /api naked to the public network
    """

    log_path = _run_log_path(run_id)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="log not found")

    async def gen():
        # Starting from the beginning of the file, send the complete log history
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
                # File was rewritten
                pos = 0

            if size > pos:
                with log_path.open("rb") as f:
                    f.seek(pos)
                    data = f.read(size - pos)
                    pos = size

                text = data.decode(errors="ignore")
                for ln in text.splitlines():
                    # SSE requires row-by-row push
                    yield f"event: log\ndata: {ln}\n\n"

            await asyncio.sleep(0.35)

    return StreamingResponse(gen(), media_type="text/event-stream")

