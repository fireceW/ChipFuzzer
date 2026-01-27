pkill -9 -f "uvicorn app:app" && \
cd /root/ChipFuzzer/web-api && \
source .venv/bin/activate && \
nohup uvicorn app:app --host 0.0.0.0 --port 8088 > /root/ChipFuzzer/web-api/webapi.out 2>&1 & \
echo $! > /root/ChipFuzzer/web-api/webapi.pid && \
sleep 2 && \
curl -sS http://127.0.0.1:8088/api/health && \
echo -e "\n✅ 服务已重启"