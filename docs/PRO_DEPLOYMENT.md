# PRO 服务器部署文档

> 本文档记录 Pro 服务器 (21.6.243.90) 上 HITL 服务的部署配置

## 一、服务器信息

| 项目 | 值 |
|------|-----|
| **主机名** | VM-243-90-tencentos |
| **IP 地址** | 21.6.243.90 |
| **域名** | hitl.woa.com |
| **操作系统** | TencentOS |
| **SSH 别名** | pro |

## 二、目录结构

```
/data/projects/hitl/
├── .env                        # 环境变量配置
├── .env.example                # 配置模板
├── deploy.sh                   # 部署脚本
├── packages/
│   ├── forward-service/        # 消息转发服务
│   │   ├── forward_service/    # 源代码
│   │   ├── .venv/              # Python 虚拟环境
│   │   └── data/               # 数据目录
│   │
│   ├── hil-server/             # HIL 服务
│   │   ├── hil_server/         # 源代码
│   │   ├── .venv/              # Python 虚拟环境
│   │   └── data/               # 数据目录
│   │
│   ├── mcp-server-py/          # MCP Server (Python)
│   └── mcp-server-ts/          # MCP Server (TypeScript)
│
├── scripts/                    # 部署脚本
├── website/                    # 静态网站
└── docs/                       # 文档
```

## 三、服务架构

```
                    ┌─────────────────────────────────────┐
                    │         Nginx (80)                  │
                    │       hitl.woa.com                  │
                    └──────────────┬──────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │       HIL Server (8081)             │
                    │                                     │
                    │  - 首页 (/)                         │
                    │  - 管理控制台 (/console)            │
                    │  - HIL API (/api/*)                │
                    │  - WebSocket (/ws)                 │
                    └──────────────┬──────────────────────┘
                                   │
                                   │ 代理
                                   ▼
                    ┌─────────────────────────────────────┐
                    │    Forward Service (8083)           │
                    │                                     │
                    │  - 企微回调处理                     │
                    │  - 消息转发到 Agent                 │
                    │  - Bot 管理                        │
                    └─────────────────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────────┐
                    │         MySQL (9.135.244.245)       │
                    │         数据库: agentstudio         │
                    └─────────────────────────────────────┘
```

## 四、Systemd 服务

### 4.1 HIL Service

```bash
# 服务文件: /etc/systemd/system/hil-service.service
[Unit]
Description=HIL Server - Human-in-the-Loop Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/data/projects/hitl/packages/hil-server
EnvironmentFile=/data/projects/hitl/.env
ExecStart=/root/.local/bin/uv run python -m hil_server.app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4.2 Forward Service

```bash
# 服务文件: /etc/systemd/system/forward-service.service
[Unit]
Description=Forward Service - WeChat Bot Message Forwarding
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/data/projects/hitl/packages/forward-service
EnvironmentFile=/data/projects/hitl/.env
ExecStart=/root/.local/bin/uv run python -m forward_service.app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4.3 服务管理命令

```bash
# 查看服务状态
sudo systemctl status hil-service forward-service

# 重启服务
sudo systemctl restart hil-service forward-service

# 停止服务
sudo systemctl stop hil-service forward-service

# 启动服务
sudo systemctl start hil-service forward-service

# 查看日志
sudo journalctl -u hil-service -f
sudo journalctl -u forward-service -f
```

## 五、配置文件

### 5.1 环境变量 (.env)

```bash
# HIL Server 配置
HIL_PORT=8081
HIL_MODE=direct                  # direct 模式直接调用 fly-pigeon
HIL_USE_DATABASE=true            # 启用数据库持久化
HIL_DATABASE_URL=mysql+aiomysql://agentstudio:PASSWORD@9.135.244.245:3306/agentstudio?charset=utf8mb4

# Forward Service 配置
FORWARD_PORT=8083
DATABASE_URL=mysql+aiomysql://agentstudio:PASSWORD@9.135.244.245:3306/agentstudio?charset=utf8mb4

# Bot Key (飞鸽传书机器人)
BOT_KEY=92fa6470-d3d3-4e12-b438-acd4c17520e2

# Forward Service 代理地址
FORWARD_SERVICE_URL=http://localhost:8083

# 管理台认证
ADMIN_USERNAME=admin
ADMIN_PASSWORD=jarvis2026
```

### 5.2 Nginx 配置

```nginx
# /etc/nginx/conf.d/hitl.conf
server {
    listen 80;
    server_name hitl.woa.com;

    access_log /var/log/nginx/hitl_access.log;
    error_log /var/log/nginx/hitl_error.log;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 300s;
    }
}
```

## 六、数据库

### 6.1 连接信息

| 项目 | 值 |
|------|-----|
| **主机** | 9.135.244.245 |
| **端口** | 3306 |
| **数据库** | agentstudio |
| **用户** | agentstudio |
| **字符集** | utf8mb4 |

### 6.2 数据库表

**HIL Server 表：**
- `hil_sessions` - HIL 会话记录
- `hil_replies` - 会话回复记录

**Forward Service 表：**
- `chatbots` - 机器人配置
- `chat_access_rules` - 访问规则
- `user_sessions` - 用户会话
- `forward_logs` - 转发日志
- `processing_sessions` - 处理中的会话
- `system_config` - 系统配置

### 6.3 数据库操作

```bash
# 连接数据库
mysql -h 9.135.244.245 -u agentstudio -p agentstudio

# 查看表
SHOW TABLES;

# 查看最近的 HIL 会话
SELECT * FROM hil_sessions ORDER BY created_at DESC LIMIT 10;

# 查看转发日志
SELECT * FROM forward_logs ORDER BY timestamp DESC LIMIT 10;
```

## 七、依赖管理

### 7.1 Python 依赖

使用 `uv` 管理 Python 虚拟环境和依赖：

```bash
# uv 路径
/root/.local/bin/uv

# HIL Server 虚拟环境
/data/projects/hitl/packages/hil-server/.venv/

# Forward Service 虚拟环境
/data/projects/hitl/packages/forward-service/.venv/
```

### 7.2 关键依赖

**HIL Server：**
- fastapi
- uvicorn
- sqlalchemy
- aiomysql
- fly-pigeon (飞鸽传书 SDK)

**Forward Service：**
- fastapi
- uvicorn
- sqlalchemy
- aiomysql
- httpx

### 7.3 安装依赖

```bash
# 进入服务目录
cd /data/projects/hitl/packages/hil-server

# 使用 uv 安装依赖
/root/.local/bin/uv pip install -r requirements.txt

# 安装飞鸽传书 SDK (内部 PyPI)
/root/.local/bin/uv pip install fly-pigeon \
  --extra-index-url http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple
```

## 八、部署流程

### 8.1 从本地同步代码

```bash
# 同步 hil-server
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  --exclude='node_modules' --exclude='dist' \
  packages/hil-server/ \
  pro:/data/projects/hitl/packages/hil-server/

# 同步 forward-service  
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  packages/forward-service/ \
  pro:/data/projects/hitl/packages/forward-service/

# 重启服务
ssh pro "sudo systemctl restart hil-service forward-service"
```

### 8.2 在服务器上拉取代码

```bash
ssh pro
cd /data/projects/hitl
git pull origin main
sudo systemctl restart hil-service forward-service
```

## 九、故障排查

### 9.1 服务无法启动

```bash
# 查看详细日志
sudo journalctl -u hil-service -n 100 --no-pager

# 手动运行测试
cd /data/projects/hitl/packages/hil-server
/root/.local/bin/uv run python -m hil_server.app
```

### 9.2 数据库连接失败

```bash
# 测试数据库连接
mysql -h 9.135.244.245 -u agentstudio -p

# 检查密码编码（密码中的特殊字符需要 URL 编码）
python3 -c "import urllib.parse; print(urllib.parse.quote('YOUR_PASSWORD', safe=''))"
```

### 9.3 Nginx 配置问题

```bash
# 测试配置
sudo nginx -t

# 重新加载
sudo nginx -s reload

# 查看日志
tail -f /var/log/nginx/hitl_error.log
```

### 9.4 端口占用

```bash
# 查看端口占用
sudo netstat -tlnp | grep -E '8081|8083'

# 查看进程
ps aux | grep -E 'hil|forward'
```

## 十、访问地址

| 服务 | 地址 |
|------|------|
| **首页** | http://hitl.woa.com/ |
| **管理控制台** | http://hitl.woa.com/console |
| **API 文档** | http://hitl.woa.com/docs |
| **健康检查** | http://hitl.woa.com/health |

## 十一、更新日志

| 日期 | 变更 |
|------|------|
| 2026-01-12 | 初始部署，域名 hitl.woa.com |
| 2026-01-12 | 启用数据库模式 (HIL_USE_DATABASE=true) |
| 2026-01-12 | 修复 fly-pigeon 模块安装到 venv |
| 2026-01-12 | 修复数据库字符集为 utf8mb4 |
