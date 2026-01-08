# HIL-MCP 部署指南

## 服务器概览

| 服务器 | 主机名 | 域名 | 用途 | 代码结构 |
|--------|--------|------|------|----------|
| **dev** | VM-76-10-centos | hitl.woa.com | 开发环境 | 旧目录结构 |
| **devg** | VM-172-68-tencentos | test-hitl.woa.com | 测试环境 | Monorepo |

---

## 一、服务架构

```
┌─────────────────────────────────────────────────────────────┐
│                         Nginx (80)                          │
├─────────────────────────────────────────────────────────────┤
│  /                → hil-server (8081)                       │
│  /ws              → hil-server (8081) [WebSocket]           │
│  /admin, /console → hil-server (8081)                       │
│  /forward/        → forward-service (8083)                  │
└─────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌──────────────────┐              ┌──────────────────┐
│   hil-server     │              │ forward-service  │
│   (端口 8081)    │              │   (端口 8083)    │
│                  │              │                  │
│  - 首页/文档     │ ────────────▶│  - 企微回调      │
│  - 管理控制台    │  代理请求    │  - 转发到 Agent  │
│  - HIL 会话管理  │              │  - Bot 管理      │
│  - MCP Server    │              │  - 会话管理      │
└──────────────────┘              └──────────────────┘
```

---

## 二、DEV 服务器 (hitl.woa.com)

### 目录结构（旧模式）

```
/root/projects/
├── hil-mcp/                    # Forward Service
│   ├── forward_service/
│   ├── data/                   # SQLite 数据库
│   └── .venv/
│
└── hil-mcp-direct/             # HIL Server
    ├── hil_server/
    ├── website/                # 首页静态文件
    ├── data/                   # SQLite 数据库
    └── .venv/
```

### Systemd 服务

#### hil-forward.service
```ini
[Service]
User=root
WorkingDirectory=/root/projects/hil-mcp
Environment="USE_DATABASE=true"
Environment="FORWARD_TIMEOUT=1800"
ExecStart=/root/projects/hil-mcp/.venv/bin/python -m forward_service.app
```

#### hil-server-direct.service
```ini
[Service]
User=root
WorkingDirectory=/root/projects/hil-mcp-direct
Environment="HIL_PORT=8081"
Environment="MODE=direct"
Environment="BOT_KEY=18c6cb5d-611c-4829-ad86-e5b9d46729c0"
Environment="ADMIN_USERNAME=admin"
Environment="ADMIN_PASSWORD=jarvis2026"
Environment="FORWARD_SERVICE_URL=http://localhost:8083"
ExecStart=/root/projects/hil-mcp-direct/.venv/bin/python -m hil_server.app
```

---

## 三、DEVG 服务器 (test-hitl.woa.com)

### 目录结构（Monorepo）

```
/data/projects/hil-mcp/
├── packages/
│   ├── forward-service/        # Forward Service
│   │   ├── forward_service/
│   │   ├── data/               # SQLite 数据库
│   │   ├── pyproject.toml
│   │   └── .venv/
│   │
│   └── hil-server/             # HIL Server
│       ├── hil_server/
│       ├── data/               # SQLite 数据库
│       ├── pyproject.toml
│       └── .venv/
│
├── website/                    # 首页静态文件
└── scripts/
    └── deploy.sh               # 部署脚本
```

### Systemd 服务

#### hil-forward.service
```ini
[Service]
User=kongjie
WorkingDirectory=/data/projects/hil-mcp/packages/forward-service
Environment="USE_DATABASE=true"
Environment="FORWARD_TIMEOUT=1800"
ExecStart=/data/projects/hil-mcp/packages/forward-service/.venv/bin/python -m forward_service.app
```

#### hil-server-direct.service
```ini
[Service]
User=kongjie
WorkingDirectory=/data/projects/hil-mcp/packages/hil-server
Environment="HIL_PORT=8081"
Environment="MODE=direct"
Environment="BOT_KEY=92fa6470-d3d3-4e12-b438-acd4c17520e2"
Environment="ADMIN_USERNAME=admin"
Environment="ADMIN_PASSWORD=jarvis2026"
Environment="FORWARD_SERVICE_URL=http://localhost:8083"
Environment="HIL_USE_DATABASE=true"
ExecStart=/data/projects/hil-mcp/packages/hil-server/.venv/bin/python -m hil_server.app
```

---

## 四、部署操作

### 从本地同步代码到 DEVG（推荐）

```bash
# 1. 同步 forward-service
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  packages/forward-service/ \
  devg:/data/projects/hil-mcp/packages/forward-service/

# 2. 同步 hil-server
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  --exclude='node_modules' --exclude='console/node_modules' --exclude='console/dist' \
  packages/hil-server/ \
  devg:/data/projects/hil-mcp/packages/hil-server/

# 3. 同步 website
rsync -avz --exclude='__pycache__' \
  website/ \
  devg:/data/projects/hil-mcp/website/

# 4. 重启服务
ssh devg "sudo systemctl restart hil-forward hil-server-direct"

# 5. 验证服务状态
ssh devg "sudo systemctl status hil-forward hil-server-direct"
```

### 从本地同步代码到 DEV

```bash
# 1. 同步 forward-service
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  packages/forward-service/forward_service/ \
  dev:/root/projects/hil-mcp/forward_service/

# 2. 同步 hil-server
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' --exclude='data' \
  --exclude='node_modules' --exclude='console/node_modules' --exclude='console/dist' \
  packages/hil-server/hil_server/ \
  dev:/root/projects/hil-mcp-direct/hil_server/

# 3. 同步 website
rsync -avz --exclude='__pycache__' \
  website/ \
  dev:/root/projects/hil-mcp-direct/website/

# 4. 重启服务
ssh dev "sudo systemctl restart hil-forward hil-server-direct"
```

### 服务管理命令

```bash
# 查看服务状态
sudo systemctl status hil-forward hil-server-direct

# 重启服务
sudo systemctl restart hil-forward hil-server-direct

# 查看日志
sudo journalctl -u hil-forward -n 50 --no-pager
sudo journalctl -u hil-server-direct -n 50 --no-pager

# 实时跟踪日志
sudo journalctl -u hil-forward -f
sudo journalctl -u hil-server-direct -f
```

---

## 五、环境变量说明

### Forward Service

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `USE_DATABASE` | 使用数据库模式 | `true` |
| `FORWARD_TIMEOUT` | Agent 请求超时（秒） | `1800` |
| `DATABASE_URL` | 数据库连接 URL | SQLite 文件 |

### HIL Server

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HIL_PORT` | 服务端口 | `8081` |
| `MODE` | 运行模式 (`direct`/`relay`) | `direct` |
| `BOT_KEY` | 企微机器人 Key | 必填 |
| `ADMIN_USERNAME` | 管理台用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理台密码 | 必填 |
| `FORWARD_SERVICE_URL` | Forward Service 地址 | `http://localhost:8083` |
| `HIL_USE_DATABASE` | 会话持久化到数据库 | `false` |

---

## 六、故障排查

### 端口被占用

```bash
# 查看端口占用
sudo netstat -tlnp | grep 8081
sudo netstat -tlnp | grep 8083

# 杀掉占用进程
sudo kill <PID>
```

### 服务启动失败

```bash
# 查看详细错误日志
sudo journalctl -u hil-server-direct -n 100 --no-pager

# 手动启动测试
cd /data/projects/hil-mcp/packages/hil-server
.venv/bin/python -m hil_server.app
```

### 检查 Nginx 配置

```bash
# 测试配置语法
sudo nginx -t

# 重新加载配置
sudo nginx -s reload
```

---

## 七、自动化部署建议

当前部署流程已经相对简化，可以进一步自动化：

### 已实现
- ✅ systemd 服务自动重启
- ✅ rsync 增量同步代码
- ✅ Nginx 反向代理

### 可优化
1. **一键部署脚本**: 已有 `scripts/deploy.sh`，可在服务器上执行
2. **Git Hook 触发**: 可配置 Git post-receive hook 自动拉取代码
3. **CI/CD 流水线**: 可接入 GitHub Actions / GitLab CI
4. **容器化**: 使用 Docker 统一环境，简化依赖管理

### 推荐方案

```bash
# 在服务器上创建部署脚本
#!/bin/bash
cd /data/projects/hil-mcp
git pull origin main
sudo systemctl restart hil-forward hil-server-direct
echo "部署完成!"
```

然后通过 SSH 一键执行：
```bash
ssh devg "bash /data/projects/hil-mcp/scripts/deploy.sh"
```
