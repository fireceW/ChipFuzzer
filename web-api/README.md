# ChipFuzzer Web API

This directory mirrors the backend API used by the ChipFuzzer Web UI. It exposes run status, runtime logs, statistics, coverage summaries, and task-control endpoints over HTTP.

## API Endpoints

- `GET /api/runs`: list known runs.
- `POST /api/runs/start`: start a fuzzing task.
- `GET /api/runs/{run_id}/status`: return task state.
- `GET /api/runs/{run_id}/logs?cursor=...`: return incremental logs.
- `GET /api/runs/{run_id}/stream`: stream logs through SSE.
- `POST /api/runs/{run_id}/stop`: stop a running task.
- `GET /api/runs/{run_id}/statistics`: return run statistics.
- `GET /api/l2-coverage`: return L2 module coverage summaries.

## Quick Start

```bash
cd /root/ChipFuzzer
mkdir -p web-api

python3 -m venv /root/ChipFuzzer/web-api/.venv
source /root/ChipFuzzer/web-api/.venv/bin/activate
pip install -r /root/ChipFuzzer/web-api/requirements.txt

uvicorn app:app --host 0.0.0.0 --port 8088
```

## Frontend Configuration

Set the API base URL in the Web UI. For local testing, use:

```text
http://localhost:8088
```

If Nginx is used, configure the frontend to point to the proxied host.

## Notes

- The backend assumes that fuzzing runs write logs and statistics to the configured run directories.
- Polling is more portable, while SSE provides lower-latency log updates when network configuration permits it.
