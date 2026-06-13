# ChipFuzzer Web Deployment Guide

This document describes how to deploy the ChipFuzzer Web UI and backend API on a Linux server.

## Requirements

- Linux server, such as Ubuntu 20.04+ or CentOS 7+
- Python 3.8+
- Nginx for reverse proxying and static files
- systemd for service management

## 1. Prepare Directories

```bash
mkdir -p /root/ChipFuzzer/web-api
mkdir -p /root/ChipFuzzer/runs
mkdir -p /var/www/chipfuzzer
```

## 2. Upload Files

Upload backend files:

```bash
scp -r server/* root@<server-ip>:/root/ChipFuzzer/web-api/
```

Upload frontend files:

```bash
scp index.html root@<server-ip>:/var/www/chipfuzzer/
scp -r assets root@<server-ip>:/var/www/chipfuzzer/
```

SFTP tools such as FileZilla or WinSCP can also be used.

## 3. Deploy the Backend API

```bash
cd /root/ChipFuzzer/web-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8088
```

Test the API from another terminal:

```bash
curl http://127.0.0.1:8088/api/runs
```

## 4. Configure systemd

Install the service file:

```bash
cp chipfuzzer-webapi.service /etc/systemd/system/chipfuzzer-webapi.service
systemctl daemon-reload
systemctl enable chipfuzzer-webapi
systemctl start chipfuzzer-webapi
```

Check status:

```bash
systemctl status chipfuzzer-webapi
journalctl -u chipfuzzer-webapi -f
```

## 5. Configure Nginx

Install the Nginx config:

```bash
cp nginx-chipfuzzer-api.conf /etc/nginx/conf.d/chipfuzzer.conf
nginx -t
systemctl reload nginx
```

Example proxy fragment:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8088/api/;
    proxy_http_version 1.1;
    proxy_buffering off;
}
```

## 6. Verify the Deployment

Open the frontend in a browser and set the API base URL to the deployed host. Confirm that:

- `/api/runs` returns a JSON response.
- Runtime logs can be fetched through polling.
- SSE works if enabled.
- Coverage and statistics endpoints return data for active runs.

## Troubleshooting

### Backend does not start

Check Python dependencies, the virtual environment path, and systemd logs.

### Frontend cannot connect

Check the API base URL, Nginx proxy rules, CORS settings, and whether the backend port is reachable.

### Logs are empty

Confirm that the fuzzing process writes logs to the expected run directory and that the backend is configured to read that directory.
