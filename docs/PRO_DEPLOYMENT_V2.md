# PRO 服务器部署文档 V2

> 更新日期：2026-01-23
> 
> 本文档适用于项目架构调整后的部署方式

## 一、架构调整说明

### 1.1 项目拆分

原 HIL-MCP 项目已拆分为两个独立项目：

| 项目 | 仓库 | 职责 |
|------|------|------|
| **HIL-MCP** | git.woa.com/kongjie/tmp | Human-in-the-Loop 核心功能 |
| **AS-Dispatch** | github.com/jeffkit/as-dispatch | 消息转发 + WebSocket 隧道 |

### 1.2 服务组成

```
┌─────────────────────────────────────────────┐
│           Nginx (80/443)                     │
│         hitl.woa.com                         │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴────────┐
       │                │
       ▼                ▼
┌─────────────┐  ┌──────────────┐
│ HIL Server  │  │ AS-Dispatch  │
│   (8081)    │  │   (8083)     │
│             │  │              │
│ HIL-MCP项目 │  │ 独立项目     │
└─────────────┘  └──────┬───────┘
       │                │
       └────────┬───────┘
                ▼
       ┌─────────────────┐
       │  MySQL DB       │
       │  (9.135.244.245)│
       └─────────────────┘
```

---

## 二、服务器目录结构

### 2.1 推荐目录布局

```
/data/projects/
├── hil-mcp/                    # HIL-MCP 项目
│   ├── .git/                   # Git 仓库
│   ├── .env                    # 环境变量
│   ├── packages/
│   │   ├── hil-server/         # HIL 服务
│   │   ├── devcloud-worker/    # Worker (可选)
│   │   ├── mcp-server-py/      # MCP 客户端 (仅开发)
│   │   └── mcp-server-ts/      # MCP 客户端 (仅开发)
│   └── docs/
│
└── as-dispatch/                # AS-Dispatch 项目
    ├── .git/                   # Git 仓库
    ├── .env                    # 环境变量
    ├── .gitmodules             # Submodule 配置
    ├── forward_service/        # 转发服务
    ├── tunely/                 # Tunely submodule
    ├── tests/
    └── alembic/
```

### 2.2 环境变量文件

**HIL-MCP (.env)**:
```bash
# /data/projects/hil-mcp/.env

# HIL Server
HIL_PORT=8081
HIL_MODE=direct
BOT_KEY=your-bot-key

# Database
HIL_DATABASE_URL=mysql+pymysql://user:pass@9.135.244.245:3306/agentstudio?charset=utf8mb4

# Forward Service (可选集成)
FORWARD_SERVICE_URL=http://localhost:8083

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-password
ADMIN_TOKEN_SECRET=your-secret-key
```

**AS-Dispatch (.env)**:
```bash
# /data/projects/as-dispatch/.env

# Forward Service
FORWARD_PORT=8083
USE_DATABASE=true
DATABASE_URL=mysql+pymysql://user:pass@9.135.244.245:3306/agentstudio?charset=utf8mb4

# Bot
DEFAULT_BOT_KEY=your-bot-key

# Tunnel (可选)
TUNNEL_ENABLED=true
```

---

## 三、Systemd 服务配置

### 3.1 HIL Service

```ini
# /etc/systemd/system/hil-service.service

[Unit]
Description=HIL Server - Human-in-the-Loop Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/data/projects/hil-mcp/packages/hil-server
EnvironmentFile=/data/projects/hil-mcp/.env
ExecStart=/root/.local/bin/uv run python -m hil_server.app
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 3.2 AS-Dispatch Service

```ini
# /etc/systemd/system/as-dispatch.service

[Unit]
Description=AgentStudio Dispatch - Message Forwarding Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/data/projects/as-dispatch
EnvironmentFile=/data/projects/as-dispatch/.env
ExecStart=/root/.local/bin/uv run python -m forward_service.app
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## 四、部署流程

### 4.1 初次部署

#### Step 1: 部署 HIL-MCP

```bash
# 1. 克隆项目
cd /data/projects
git clone git@git.woa.com:kongjie/tmp.git hil-mcp
cd hil-mcp

# 2. 配置环境变量
cp .env.example .env
vim .env  # 编辑配置

# 3. 安装依赖
cd packages/hil-server
uv sync

# 4. 运行数据库迁移
alembic upgrade head

# 5. 创建 systemd 服务
sudo cp /path/to/hil-service.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hil-service
sudo systemctl start hil-service

# 6. 检查状态
sudo systemctl status hil-service
sudo journalctl -u hil-service -f
```

#### Step 2: 部署 AS-Dispatch

```bash
# 1. 克隆项目（包含 submodule）
cd /data/projects
git clone --recursive git@github.com:jeffkit/as-dispatch.git
cd as-dispatch

# 如果忘记 --recursive，手动初始化 submodule
git submodule update --init --recursive

# 2. 配置环境变量
cp .env.example .env
vim .env  # 编辑配置

# 3. 安装依赖
uv sync

# 4. 运行数据库迁移
alembic upgrade head

# 5. 创建 systemd 服务
sudo cp /path/to/as-dispatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable as-dispatch
sudo systemctl start as-dispatch

# 6. 检查状态
sudo systemctl status as-dispatch
sudo journalctl -u as-dispatch -f
```

---

### 4.2 日常更新

#### 更新 HIL-MCP

```bash
cd /data/projects/hil-mcp

# 1. 拉取最新代码
git pull origin main

# 2. 更新依赖（如有变化）
cd packages/hil-server
uv sync

# 3. 运行数据库迁移（如有）
alembic upgrade head

# 4. 重启服务
sudo systemctl restart hil-service

# 5. 检查日志
sudo journalctl -u hil-service -f
```

#### 更新 AS-Dispatch

```bash
cd /data/projects/as-dispatch

# 1. 拉取最新代码
git pull origin main

# 2. 更新 submodule（如有变化）
git submodule update --remote

# 3. 更新依赖
uv sync

# 4. 运行数据库迁移（如有）
alembic upgrade head

# 5. 重启服务
sudo systemctl restart as-dispatch

# 6. 检查日志
sudo journalctl -u as-dispatch -f
```

---

### 4.3 快捷部署脚本

创建 `/data/projects/deploy.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 开始部署更新..."

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 更新 HIL-MCP
echo -e "\n${YELLOW}[1/2] 更新 HIL-MCP...${NC}"
cd /data/projects/hil-mcp
git pull origin main
cd packages/hil-server
uv sync
alembic upgrade head
sudo systemctl restart hil-service
echo -e "${GREEN}✅ HIL-MCP 更新完成${NC}"

# 更新 AS-Dispatch
echo -e "\n${YELLOW}[2/2] 更新 AS-Dispatch...${NC}"
cd /data/projects/as-dispatch
git pull origin main
git submodule update --remote
uv sync
alembic upgrade head
sudo systemctl restart as-dispatch
echo -e "${GREEN}✅ AS-Dispatch 更新完成${NC}"

# 检查服务状态
echo -e "\n${YELLOW}检查服务状态...${NC}"
sudo systemctl status hil-service --no-pager
sudo systemctl status as-dispatch --no-pager

echo -e "\n${GREEN}🎉 部署完成！${NC}"
```

使用：
```bash
chmod +x /data/projects/deploy.sh
/data/projects/deploy.sh
```

---

## 五、Nginx 配置

### 5.1 完整配置示例

```nginx
# /etc/nginx/conf.d/hitl.conf

server {
    listen 80;
    server_name hitl.woa.com;

    # 日志
    access_log /var/log/nginx/hitl-access.log;
    error_log /var/log/nginx/hitl-error.log;

    # HIL Server (首页、管理台、API)
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # AS-Dispatch (转发服务、隧道)
    location /dispatch {
        rewrite ^/dispatch(/.*)$ $1 break;
        proxy_pass http://127.0.0.1:8083;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # WebSocket 隧道支持
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # AS-Dispatch 回调（企微）
    location /callback {
        proxy_pass http://127.0.0.1:8083;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 5.2 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| HIL 首页 | http://hitl.woa.com/ | HIL 服务首页 |
| HIL 管理台 | http://hitl.woa.com/console | HIL 管理控制台 |
| HIL API | http://hitl.woa.com/api/* | MCP 客户端调用 |
| AS-Dispatch 管理 | http://hitl.woa.com/dispatch/admin | 转发/隧道管理 |
| 企微回调 | http://hitl.woa.com/callback/{bot_key} | 企微消息回调 |

---

## 六、数据库管理

### 6.1 数据库结构

两个项目共享同一个 MySQL 数据库 `agentstudio`，但使用不同的表：

**HIL-MCP 表**:
- `hil_sessions` - HIL 会话
- `hil_replies` - 会话回复

**AS-Dispatch 表**:
- `chatbots` - Bot 配置
- `chat_access_rules` - 访问规则
- `user_sessions` - 用户会话
- `forward_logs` - 转发日志
- `processing_sessions` - 处理中会话
- `system_config` - 系统配置
- `tunnels` - 隧道配置
- `tunnel_request_logs` - 隧道请求日志

### 6.2 数据库连接

```bash
# 连接数据库
mysql -h 9.135.244.245 -u your_user -p agentstudio

# 查看表
SHOW TABLES;

# 查看 HIL 会话
SELECT * FROM hil_sessions ORDER BY created_at DESC LIMIT 10;

# 查看转发日志
SELECT * FROM forward_logs ORDER BY timestamp DESC LIMIT 10;

# 查看隧道
SELECT * FROM tunnels;
```

---

## 七、监控和维护

### 7.1 服务管理命令

```bash
# 查看状态
sudo systemctl status hil-service as-dispatch

# 重启服务
sudo systemctl restart hil-service
sudo systemctl restart as-dispatch

# 查看日志
sudo journalctl -u hil-service -f
sudo journalctl -u as-dispatch -f

# 查看最近 100 行日志
sudo journalctl -u hil-service -n 100
sudo journalctl -u as-dispatch -n 100
```

### 7.2 常见问题排查

**问题1：服务启动失败**
```bash
# 检查日志
sudo journalctl -u hil-service -n 50
sudo journalctl -u as-dispatch -n 50

# 检查配置文件
cat /data/projects/hil-mcp/.env
cat /data/projects/as-dispatch/.env

# 手动启动测试
cd /data/projects/hil-mcp/packages/hil-server
source .venv/bin/activate
python -m hil_server.app
```

**问题2：数据库连接失败**
```bash
# 测试数据库连接
mysql -h 9.135.244.245 -u your_user -p agentstudio

# 检查网络
ping 9.135.244.245
telnet 9.135.244.245 3306
```

**问题3：Submodule 未初始化**
```bash
cd /data/projects/as-dispatch
git submodule status
git submodule update --init --recursive
```

---

## 八、迁移指南

### 8.1 从旧架构迁移

如果你的服务器上还是旧的 HIL-MCP 单仓库架构：

```bash
# 1. 备份现有数据
sudo systemctl stop hil-service forward-service
cp -r /data/projects/hitl /data/projects/hitl.backup

# 2. 部署新架构
# 按照「四、部署流程」执行

# 3. 数据迁移（如需要）
# AS-Dispatch 的数据可能需要从旧的 forward-service 迁移

# 4. 测试验证
# 确认两个服务都正常运行

# 5. 清理旧目录（确认无误后）
# rm -rf /data/projects/hitl.backup
```

---

## 九、总结

### 优势

1. **职责清晰**：HIL-MCP 专注 Human-in-the-Loop，AS-Dispatch 专注消息转发
2. **独立升级**：两个项目可以独立更新，互不影响
3. **代码管理**：AS-Dispatch 在 GitHub 公开，HIL-MCP 在内网
4. **灵活部署**：可以只部署其中一个服务

### 注意事项

1. AS-Dispatch 使用 Git submodule（tunely），更新时记得 `git submodule update`
2. 两个项目共享数据库，升级时注意数据库迁移顺序
3. HIL Server 的 `FORWARD_SERVICE_URL` 配置是可选的，不影响核心功能
