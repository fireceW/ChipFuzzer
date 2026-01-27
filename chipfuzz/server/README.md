# ChipFuzzer 运行过程展示：服务器端 API（SSE/轮询）

目标：把服务器上 `/root/ChipFuzzer` 的运行过程（状态/日志）通过 HTTP API 暴露给网页展示。

## 你需要做的事

1. 在服务器上创建目录并上传本目录内容（`server/`）
2. 安装依赖并启动服务（systemd 推荐）
3. 用 Nginx 反代到你的域名（推荐同域，避免 CORS）

## API 约定（网页端已按此实现）

- `GET /api/runs`
  - 返回任务列表（你可以先返回空数组，后续再接入真实任务管理）
- `POST /api/runs/start`
  - 启动后台：`python xiangshan_fuzzing.py --num <num>`
  - 返回 `{ runId, pid, cmd }`
- `GET /api/runs/{run_id}/status`
  - 返回 `{ "state": "running|done|crashed|unknown" }`
- `GET /api/runs/{run_id}/logs?cursor=...`
  - 增量日志：返回 `{ "lines": ["..."], "nextCursor": "..." }`
- `GET /api/runs/{run_id}/stream`
  - SSE：事件 `log`（每行日志），可选事件 `status`
- `POST /api/runs/{run_id}/stop`
  - 停止任务（SIGTERM）

## 快速启动（服务器上）

在服务器执行：

```bash
cd /root/ChipFuzzer
mkdir -p web-api
# 把本地的 server/* 上传到 /root/ChipFuzzer/web-api/

python3 -m venv /root/ChipFuzzer/web-api/.venv
source /root/ChipFuzzer/web-api/.venv/bin/activate
pip install -r /root/ChipFuzzer/web-api/requirements.txt

uvicorn app:app --host 0.0.0.0 --port 8088
```

然后把网页的 API Base 设置成：`https://你的域名/api`

## 重要提示

- 这是“最小可用”骨架：
  - 默认工作目录：`/root/ChipFuzzer`
  - 默认脚本：`xiangshan_fuzzing.py`（可用环境变量覆盖）
  - 默认日志：`/root/ChipFuzzer/runs/<runId>/run.log`
- 可配置环境变量：
  - `CHIPFUZZER_BASE=/root/ChipFuzzer`
  - `CHIPFUZZER_RUNS=/root/ChipFuzzer/runs`
  - `CHIPFUZZER_BACKEND_SCRIPT=xiangshan_fuzzing.py`
  - `CHIPFUZZER_PYTHON=python3`

