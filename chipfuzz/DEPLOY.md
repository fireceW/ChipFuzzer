# ChipFuzzer 网页项目部署指南

本文档详细说明如何在 Linux 服务器上部署 ChipFuzzer 展示系统。

## 📋 系统要求

- **操作系统**：Linux（推荐 Ubuntu 20.04+ 或 CentOS 7+）
- **Python**：3.8+
- **Nginx**：用于反向代理和静态文件服务
- **systemd**：用于服务管理

## 🚀 部署步骤

### 第一步：准备服务器目录结构

```bash
# 创建项目目录
mkdir -p /root/ChipFuzzer/web-api
mkdir -p /root/ChipFuzzer/runs
mkdir -p /var/www/chipfuzzer
```

### 第二步：上传项目文件

将本地文件上传到服务器：

```bash
# 上传后端文件到服务器（在本地执行）
scp -r server/* root@你的服务器IP:/root/ChipFuzzer/web-api/

# 上传前端文件到服务器（在本地执行）
scp index.html root@你的服务器IP:/var/www/chipfuzzer/
scp -r assets root@你的服务器IP:/var/www/chipfuzzer/
```

或者使用 FTP/SFTP 工具（如 FileZilla、WinSCP）上传。

### 第三步：部署后端 API 服务

#### 3.1 安装 Python 依赖

```bash
# SSH 登录到服务器后执行
cd /root/ChipFuzzer/web-api

# 创建 Python 虚拟环境
python3 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

#### 3.2 测试后端服务

```bash
# 测试运行（确保 8088 端口未被占用）
cd /root/ChipFuzzer/web-api
source .venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8088

# 在另一个终端测试 API
curl http://127.0.0.1:8088/api/health
# 应该返回：{"ok":true}
```

如果测试成功，按 `Ctrl+C` 停止测试服务。

#### 3.3 配置 systemd 服务

```bash
# 复制 service 文件
sudo cp /root/ChipFuzzer/web-api/chipfuzzer-webapi.service /etc/systemd/system/

# 如果你的路径与默认不同，需要编辑 service 文件
sudo nano /etc/systemd/system/chipfuzzer-webapi.service
```

**重要**：确保 `chipfuzzer-webapi.service` 文件中的路径正确：
- `WorkingDirectory=/root/ChipFuzzer/web-api`
- `ExecStart=/root/ChipFuzzer/web-api/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8088`

#### 3.4 启动后端服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start chipfuzzer-webapi

# 设置开机自启
sudo systemctl enable chipfuzzer-webapi

# 查看服务状态
sudo systemctl status chipfuzzer-webapi

# 查看日志（如果有问题）
sudo journalctl -u chipfuzzer-webapi -f
```

### 第四步：配置 Nginx

#### 4.1 安装 Nginx（如果未安装）

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install nginx

# CentOS/RHEL
sudo yum install nginx
```

#### 4.2 配置 Nginx 站点

创建或编辑 Nginx 配置文件：

```bash
sudo nano /etc/nginx/conf.d/chipfuzzer.conf
```

**配置内容**（根据你的实际情况修改域名和路径）：

```nginx
server {
    listen 80;
    server_name js1.blockelite.cn;  # 修改为你的域名或服务器IP

    # 前端静态文件
    location / {
        root /var/www/chipfuzzer;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:8088/api/;
        proxy_http_version 1.1;

        # SSE 关键配置：不缓存
        proxy_buffering off;
        proxy_cache off;
        add_header Cache-Control "no-cache";

        # 透传请求头
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection '';
    }
}
```

#### 4.3 测试并启动 Nginx

```bash
# 测试配置文件语法
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx

# 设置开机自启
sudo systemctl enable nginx

# 查看状态
sudo systemctl status nginx
```

### 第五步：配置防火墙

确保服务器防火墙允许 HTTP/HTTPS 流量：

```bash
# Ubuntu (UFW)
sudo ufw allow 'Nginx Full'
sudo ufw enable

# CentOS (Firewalld)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 第六步：修改前端配置（如果需要）

如果你的前端 JavaScript 中硬编码了 API 地址，需要修改：

```bash
# 编辑前端文件
sudo nano /var/www/chipfuzzer/assets/main.js
```

确保 API 请求的基础 URL 正确，例如：
```javascript
const API_BASE = '/api';  // 相对路径，推荐
// 或
const API_BASE = 'https://js1.blockelite.cn/api';  // 绝对路径
```

### 第七步：验证部署

1. **验证后端 API**
   ```bash
   curl http://localhost/api/health
   # 应该返回：{"ok":true}
   ```

2. **验证前端页面**
   - 在浏览器访问：`http://你的服务器IP` 或 `http://你的域名`
   - 应该能看到 ChipFuzzer 展示页面

3. **验证完整功能**
   - 在网页上尝试启动任务
   - 查看日志流是否正常

## 🔒 HTTPS 配置（推荐）

为了安全性，建议配置 HTTPS：

### 使用 Let's Encrypt（免费证书）

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 自动配置 HTTPS
sudo certbot --nginx -d 你的域名

# 测试自动续期
sudo certbot renew --dry-run
```

## 📝 环境变量配置

你可以通过环境变量自定义配置，编辑 `/etc/systemd/system/chipfuzzer-webapi.service`：

```ini
[Service]
...
Environment=CHIPFUZZER_BASE=/root/ChipFuzzer
Environment=CHIPFUZZER_RUNS=/root/ChipFuzzer/runs
Environment=CHIPFUZZER_BACKEND_SCRIPT=xiangshan_fuzzing.py
Environment=CHIPFUZZER_PYTHON=python3
```

修改后需要重启服务：
```bash
sudo systemctl daemon-reload
sudo systemctl restart chipfuzzer-webapi
```

## 🔧 常见问题排查

### 1. 后端服务无法启动

```bash
# 查看详细日志
sudo journalctl -u chipfuzzer-webapi -n 50

# 检查端口占用
sudo netstat -tlnp | grep 8088

# 手动测试
cd /root/ChipFuzzer/web-api
source .venv/bin/activate
python -c "import fastapi; print('FastAPI OK')"
```

### 2. Nginx 502 错误

```bash
# 检查后端服务是否运行
sudo systemctl status chipfuzzer-webapi

# 检查 SELinux（CentOS）
sudo setenforce 0  # 临时关闭测试

# 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 3. 前端无法访问

```bash
# 检查文件权限
ls -la /var/www/chipfuzzer/

# 确保 Nginx 用户有读权限
sudo chmod -R 755 /var/www/chipfuzzer/
sudo chown -R www-data:www-data /var/www/chipfuzzer/  # Ubuntu
# 或
sudo chown -R nginx:nginx /var/www/chipfuzzer/  # CentOS
```

### 4. API 请求失败（CORS）

如果使用了不同域名，需要在后端添加 CORS 支持：

```python
# 在 app.py 中添加
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://你的前端域名"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 📊 监控和维护

### 查看服务状态

```bash
# 后端服务状态
sudo systemctl status chipfuzzer-webapi

# 查看实时日志
sudo journalctl -u chipfuzzer-webapi -f

# Nginx 访问日志
sudo tail -f /var/log/nginx/access.log
```

### 重启服务

```bash
# 重启后端
sudo systemctl restart chipfuzzer-webapi

# 重启 Nginx
sudo systemctl restart nginx

# 重启所有
sudo systemctl restart chipfuzzer-webapi nginx
```

### 更新代码

```bash
# 1. 上传新代码
scp server/app.py root@服务器IP:/root/ChipFuzzer/web-api/

# 2. 重启后端服务
sudo systemctl restart chipfuzzer-webapi

# 3. 如果是前端更新
scp -r assets/* root@服务器IP:/var/www/chipfuzzer/assets/
# 前端是静态文件，无需重启服务
```

## 🎯 快速部署脚本

你也可以将上述步骤整合成一个部署脚本 `deploy.sh`：

```bash
#!/bin/bash
set -e

echo "开始部署 ChipFuzzer 项目..."

# 创建目录
mkdir -p /root/ChipFuzzer/web-api
mkdir -p /root/ChipFuzzer/runs
mkdir -p /var/www/chipfuzzer

# 安装 Python 依赖
cd /root/ChipFuzzer/web-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置 systemd
sudo cp chipfuzzer-webapi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chipfuzzer-webapi
sudo systemctl restart chipfuzzer-webapi

# 配置 Nginx
sudo cp nginx-chipfuzzer-api.conf /etc/nginx/conf.d/chipfuzzer.conf
sudo nginx -t
sudo systemctl restart nginx

echo "✅ 部署完成！"
echo "请访问: http://$(hostname -I | awk '{print $1}')"
```

## 📞 支持

如有问题，请检查：
1. 服务日志：`sudo journalctl -u chipfuzzer-webapi -f`
2. Nginx 日志：`/var/log/nginx/error.log`
3. 确保所有路径配置正确
4. 确保防火墙允许 HTTP/HTTPS 流量

---

**部署完成后，你就可以通过浏览器访问你的 ChipFuzzer 展示系统了！** 🎉
