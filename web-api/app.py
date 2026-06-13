from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ChipFuzzer Web API", version="0.1.0")

# Add CORS support, allowing web pages to access the API from file:// or any domain name
app.add_middleware(
    CORSMiddleware,
    allow_origins=["null", "http://localhost:5173", "http://localhost:8080"],  # Allow file:// (null) and local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Convention: The log of each run is placed in /root/ChipFuzzer/runs/<run_id>/run.log
BASE_DIR = Path(os.environ.get("CHIPFUZZER_BASE", "/root/ChipFuzzer")).resolve()
RUNS_DIR = Path(os.environ.get("CHIPFUZZER_RUNS", str(BASE_DIR / "runs"))).resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Coverage caching (avoids frequent execution of genhtml)
coverage_cache = {
    "data": None,
    "mtime": 0,
}

# Your background command (the default is what you provide)
BACKEND_SCRIPT = os.environ.get("CHIPFUZZER_BACKEND_SCRIPT", "xiangshan_fuzzing.py")
PYTHON_BIN = os.environ.get("CHIPFUZZER_PYTHON", "/root/anaconda3/bin/python")

# coverage command working directory
COVERAGE_DIR = Path(os.environ.get("CHIPFUZZER_COVERAGE_DIR", "/root/XiangShan")).resolve()

# Successful Case Directory
SUCCESS_SEED_DIR = BASE_DIR / "GJ_Success_Seed"


def _run_log_path(run_id: str) -> Path:
    # run_id is used as the file name prefix and is saved to the /root/ChipFuzzer/GJ_log/ directory
    safe = run_id.replace("\\", "_").replace("/", "_").strip()
    log_dir = BASE_DIR / "GJ_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{safe}.log"

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
    coverage_filename_origin: str = "/root/XiangShan/logs/annotated/"
    coverage_filename_later: str = "/root/XiangShan/logs2/annotated/"
    num: int = None  # Optional parameter to maintain backward compatibility

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

@app.post("/api/runs/start")
def start_run(req: StartRunReq) -> dict:
    """
    Start the background program:
      python xiangshan_fuzzing.py --num <num> --module <module> --model <model> ...

    product:
      /root/ChipFuzzer/runs/<runId>/run.log
      /root/ChipFuzzer/runs/<runId>/pid
    """
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = _run_log_path(run_id)
    
    # Create a task-specific .dat file (in the /root/ChipFuzzer directory)
    dat_file_path = BASE_DIR / f"{run_id}.dat"
    dat_file_path.write_text(f"runId: {run_id}\n", encoding="utf-8")

    # Build complete command line parameters
    cmd = [
        PYTHON_BIN,
        BACKEND_SCRIPT,
        "--module", req.module,
        "--model", req.model,
        "--coverage_filename_origin", req.coverage_filename_origin,
        "--coverage_filename_later", req.coverage_filename_later,
        "--dat", str(dat_file_path),  # Add .dat file path parameter
    ]
    
    # If num argument is provided, added to the command line (backward compatibility)
    if req.num is not None:
        cmd.extend(["--num", str(req.num)])
    
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
    Execute genhtml coverage.info in the /root/XiangShan directory and parse the output
    Use cache to avoid frequent execution (only re-execute when coverage.info changes)
    """
    coverage_info_path = COVERAGE_DIR / "coverage.info"
    
    # Check if the file exists
    if not coverage_info_path.exists():
        return {
            "coverage_percentage": 0.0,
            "total_covered_lines": 0,
            "total_lines": 0,
        }
    
    # Check the file modification time and return to the cache if it has not changed
    current_mtime = coverage_info_path.stat().st_mtime
    if coverage_cache["data"] and coverage_cache["mtime"] == current_mtime:
        return coverage_cache["data"]
    
    try:
        # Execute the genhtml command in the /root/XiangShan directory to obtain coverage
        # Increase the timeout to 300 seconds (5 minutes) as large projects may take a long time
        result = subprocess.run(
            ["genhtml", "coverage.info", "--output-directory", "coverage_gj"],
            cwd=str(COVERAGE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        output = result.stdout + result.stderr
        
        # Parse "Overall coverage rate: lines......: 72.2% (463483 of 642121 lines)"
        import re
        match = re.search(r'lines\.+:\s*([\d.]+)%\s*\((\d+)\s+of\s+(\d+)\s+lines\)', output)
        
        if match:
            percentage = float(match.group(1))
            covered = int(match.group(2))
            total = int(match.group(3))
            data = {
                "coverage_percentage": percentage,
                "total_covered_lines": covered,
                "total_lines": total,
            }
        else:
            # If parsing fails, return the default value
            data = {
                "coverage_percentage": 0.0,
                "total_covered_lines": 0,
                "total_lines": 0,
            }
        
        # Update cache
        coverage_cache["data"] = data
        coverage_cache["mtime"] = current_mtime
        
        return data
        
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

