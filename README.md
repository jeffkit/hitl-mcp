# Human-in-the-Loop MCP for WeCom (企业微信)

让 AI Agent 能够发送消息到企业微信并等待用户回复的 MCP 服务。

## 功能特性

- 🚀 **发送消息到企微群聊/私聊**
- ⏳ **等待用户回复并返回结果**
- 🎯 **引用回复匹配** - 通过 `[#short_id]` 精确匹配多个并发会话
- 💬 **多会话冲突检测** - 自动提示用户使用引用回复
- ⏰ **20分钟默认超时**
- 📋 **自动回复 chat_id** - 方便用户获取配置信息
- ⚙️ **空闲提示配置** - JSON 配置文件 + 热更新 + 管理台可视化配置
- ⚡ **一键安装** - 通过 `uvx` 或 `pipx` 无需预先安装
- 🌐 **双模式支持** - Relay 中转模式（公网）和 Direct 直连模式（内网）
- 🔄 **消息转发服务** - 支持用户主动发消息触发外部服务（Forward Service）

---

## 架构说明

本项目的 Relay Server 支持两种运行模式：

### 模式一：Relay 模式（公网部署）

当 HIL Server 部署在公网时，通过 WebSocket 连接内网的 Worker 来调用飞鸽 API。

```
┌─────────────────┐      HTTPS       ┌─────────────────┐
│   MCP Server    │ ────────────────▶│   HIL Server    │
│ (本地 AI Agent)  │ ◀────────────────│   (公网服务器)   │
└─────────────────┘                  └────────┬────────┘
                                              │ WebSocket
                                              │ (Worker 主动连接)
                                     ┌────────▼────────┐
                                     │ DevCloud Worker │
                                     │  (内网/DevCloud) │
                                     └────────┬────────┘
                                              │ fly-pigeon
                                              ▼
                                     ┌─────────────────┐
                                     │    企业微信      │
                                     └─────────────────┘
```

**适用场景：**
- MCP Server 运行在公网（如个人电脑）
- 飞鸽 API 只能在内网访问
- 需要穿透内网限制

### 模式二：Direct 模式（内网部署）

当 HIL Server 部署在内网时，可以直接调用飞鸽 API，无需 Worker。

```
┌─────────────────┐      HTTP       ┌─────────────────┐     fly-pigeon    ┌─────────────────┐
│   MCP Server    │ ───────────────▶│   HIL Server    │ ─────────────────▶│   企业微信       │
│  (内网 Agent)    │ ◀───────────────│   (内网部署)     │ ◀─────────────────│   (飞鸽传书)     │
└─────────────────┘                 └─────────────────┘      回调          └─────────────────┘
```

**适用场景：**
- MCP Server 和 HIL Server 都在内网
- 可以直接访问飞鸽 API
- 简化部署，无需 Worker

### 模式自动切换

HIL Server 通过配置自动选择模式：

| 条件 | 模式 |
|------|------|
| 配置了 `BOT_KEY` | Direct 模式 |
| 未配置 `BOT_KEY` | Relay 模式 |
| `HIL_MODE=direct` | 强制 Direct 模式 |
| `HIL_MODE=relay` | 强制 Relay 模式 |

---

## 快速开始（MCP 客户端配置）

### 方式一：使用 uvx（推荐）

> `uvx` 是 Python 生态中的 `npx`，无需预先安装包，直接运行。

在 Cursor 的 MCP 配置文件中添加（`~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "uvx",
      "args": [
        "hil-mcp",
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id",
        "--project-name", "my-project"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

### 方式二：使用 pipx

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "pipx",
      "args": [
        "run",
        "hil-mcp",
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

### 方式三：传统方式（pip install）

```bash
pip install hil-mcp
```

然后配置：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "hil-mcp",
      "args": [
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

### 命令行参数说明

| 参数 | 说明 | 是否必填 | 默认值 |
|------|------|----------|--------|
| `--service-url` | HIL Server 地址（如 `http://hitl.woa.com/api`） | ✅ 必填 | `http://localhost:8081` |
| `--chat-id` | 默认 Chat ID（群聊或私聊） | ✅ 必填 | - |
| `--project-name` | 项目名称，用于标识消息来源 | 可选 | - |
| `--timeout` | 等待回复超时时间（秒） | 可选 | `1200` (20 分钟) |

### 获取 Chat ID

**方法1**：直接在企微中 @机器人 发送任意消息，机器人会自动回复 Chat ID

**方法2**：查看服务器日志，找到 `chatid` 字段

---

## 服务端部署

### 前置准备

1. **公网服务器**：一台可从公网访问的服务器（云服务器/VPS）
2. **域名（推荐）**：用于 HTTPS 访问，可使用免费 SSL 证书
3. **内网环境**：可以访问飞鸽 API 的环境（如 DevCloud）
4. **飞鸽机器人**：已创建并获取 `BOT_KEY`

### Relay 模式部署（推荐）

适用于 MCP Server 运行在公网的场景。

#### 第一步：部署 HIL Server（公网服务器）

```bash
# 1. 克隆代码到公网服务器
git clone https://github.com/user/hil-mcp.git
cd hil-mcp

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
export HIL_PORT=8081
export HIL_WORKER_TOKEN=your-secret-token  # 用于 Worker 鉴权，请自定义

# 4. 启动服务（后台运行）
nohup python -m hil_server.app >> hil.log 2>&1 &
```

#### 第二步：配置 Nginx 反向代理（推荐）

为了支持 HTTPS 和 WebSocket，建议使用 Nginx 作为反向代理：

```nginx
# /etc/nginx/sites-available/hil-server
server {
    listen 80;
    server_name your-domain.com;  # 替换为你的域名
    
    # 如果使用 HTTPS，取消以下注释
    # listen 443 ssl;
    # ssl_certificate /path/to/cert.pem;
    # ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        
        # WebSocket 支持（必须）
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 长连接支持
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_connect_timeout 86400s;
        
        # 禁用缓冲
        proxy_buffering off;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/hil-server /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 第三步：部署 DevCloud Worker（内网环境）

```bash
# 1. 克隆代码到内网服务器（如 DevCloud）
git clone https://github.com/user/hil-mcp.git
cd hil-mcp

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export HIL_URL=wss://your-domain.com/ws  # 使用域名，wss 表示 HTTPS
# 或使用 IP（如果没有域名）
# export HIL_URL=ws://your-server-ip:80/ws

export HIL_TOKEN=your-secret-token    # 与 HIL Server 一致
export BOT_KEY=your-wecom-bot-key     # 飞鸽机器人 Key
export CALLBACK_PORT=8082

# 4. 启动服务
nohup python -m devcloud_worker.worker >> worker.log 2>&1 &
```

#### 第四步：配置飞鸽传书回调

在飞鸽传书管理后台配置回调地址：

```
http://your-devcloud-server:8082/callback
```

> ⚠️ 回调地址必须是内网可访问的地址，飞鸽会向这个地址推送用户回复。

#### 第五步：验证部署

```bash
# 检查 HIL Server 状态（应显示 mode: relay, worker_connected: true）
curl https://your-domain.com/health

# 检查 Worker 状态
curl http://localhost:8082/health
```

### Direct 模式部署

适用于 MCP Server 和 HIL Server 都在内网的场景。

```bash
# 1. 克隆代码
git clone https://github.com/user/hil-mcp.git
cd hil-mcp

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
export HIL_PORT=8080
export BOT_KEY=your-wecom-bot-key  # 有 BOT_KEY 自动切换到 direct 模式
# 或强制指定模式
# export HIL_MODE=direct

# 4. 启动服务
nohup python -m hil_server.app >> hil.log 2>&1 &
```

配置飞鸽传书回调地址：

```
http://your-server:8080/api/callback
```

验证：

```bash
# 应显示 mode: direct
curl http://localhost:8080/health
```

---

## 部署清单

### Relay 模式

| 组件 | 部署位置 | 端口 | 说明 |
|------|----------|------|------|
| HIL Server | 公网服务器 | 8081 (Nginx 80/443) | 接收 MCP 请求，管理 Worker 连接 |
| DevCloud Worker | 内网/DevCloud | 8082 | 连接 HIL Server，调用飞鸽 API |

### Direct 模式

| 组件 | 部署位置 | 端口 | 说明 |
|------|----------|------|------|
| HIL Server | 内网服务器 | 8080 | 直接调用飞鸽 API |

---

## 环境变量说明

### HIL Server

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HIL_PORT` | 服务监听端口 | 8081 |
| `HIL_MODE` | 运行模式：`auto`/`relay`/`direct` | auto |
| `BOT_KEY` | 飞鸽机器人 Key（direct 模式必填） | - |
| `HIL_WORKER_TOKEN` | Worker 连接鉴权 Token | 可选 |
| `HEARTBEAT_INTERVAL` | 心跳间隔（秒） | 30 |
| `HEARTBEAT_TIMEOUT` | 心跳超时（秒） | 90 |
| `IDLE_HINT_MESSAGE_TEMPLATE` | 空闲状态提示消息模板（支持变量） | 见下方说明 |
| `ADMIN_USERNAME` | 管理台登录用户名 | admin |
| `ADMIN_PASSWORD` | 管理台登录密码 | jarvis2026 |
| `ADMIN_TOKEN_SECRET` | JWT Token 密钥 | hil-mcp-secret-key-2026 |

### DevCloud Worker

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HIL_URL` | HIL Server 的 WebSocket 地址（Worker 模式） | `ws://localhost:8081/ws` |
| `HIL_TOKEN` | 连接 HIL Server 的鉴权 Token | 可选 |
| `BOT_KEY` | 飞鸽机器人 Webhook Key | 必填 |
| `CALLBACK_PORT` | 回调服务监听端口 | 8082 |
| `CALLBACK_AUTH_KEY` | 回调鉴权 Header 名称 | 可选 |
| `CALLBACK_AUTH_VALUE` | 回调鉴权 Header 值 | 可选 |

### MCP Server (MCP 客户端)

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SERVICE_URL` | HIL Server 地址（如 `http://hitl.woa.com/api`） | `http://localhost:8081` |
| `DEFAULT_CHAT_ID` | 默认 Chat ID | 必填 |
| `DEFAULT_PROJECT_NAME` | 默认项目名称 | 可选 |
| `DEFAULT_TIMEOUT` | 超时时间（秒） | `1200` (20 分钟) |

### 空闲状态提示消息配置

`IDLE_HINT_MESSAGE_TEMPLATE` 用于自定义当用户发送消息但机器人并非处于等待回复状态时的自动回复内容。

**支持的变量：**
- `{user_name}` - 发送消息的用户名称
- `{chat_id}` - 当前会话的 Chat ID
- `{chat_type}` - 会话类型（"私聊" 或 "群聊"）
- `{timestamp}` - 当前时间戳（格式：HH:MM:SS）

**默认模板：**
```
👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{chat_type}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {chat_type}
🕐 **时间**: {timestamp}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```
```

**自定义示例：**
```bash
# 简洁版本
export IDLE_HINT_MESSAGE_TEMPLATE="Hi {user_name}，当前无等待中的消息。Chat ID: {chat_id}"

# Markdown 格式版本
export IDLE_HINT_MESSAGE_TEMPLATE="👋 {user_name}，当前无等待消息\n\n📋 **Chat ID**: \`{chat_id}\`\n🕐 {timestamp}"

# 自定义指引版本
export IDLE_HINT_MESSAGE_TEMPLATE="嗨 {user_name}！\n\n当前没有需要处理的消息哦～\n\n💡 如需配置机器人，请联系管理员并提供：\n- Chat ID: \`{chat_id}\`\n- 类型: {chat_type}"
```

**注意事项：**
- 如果不配置此变量，将使用默认模板
- 消息支持 Markdown 格式（使用飞鸽传书的 `markdown` 接口）
- 变量使用 Python 的 `str.format()` 语法，确保所有 `{变量名}` 正确闭合
- 建议在消息中包含 `{chat_id}`，方便用户获取配置信息

---

## 使用方法

### AI Agent 调用示例

```python
# 发送消息并等待回复
result = await send_and_wait_reply(
    message="请确认是否继续？",
    project_name="my-project",  # 可选，用于标识消息来源
)

# 仅发送消息，不等待回复
result = await send_message_only(
    message="任务已完成！"
)
```

### 用户回复方式

1. **单会话场景**：直接回复即可
2. **多会话场景**：使用「引用回复」功能精确选择要回复的消息

---

## 空闲提示消息配置

当用户在配置的 Chat ID 中发送消息，但机器人并非处于等待回复状态时，会自动回复一条提示消息，显示当前的 Chat ID 等信息。

### 核心特性

- ✅ **JSON 配置文件存储** - `data/idle_hint_config.json`
- ✅ **热更新** - 修改后立即生效，无需重启服务
- ✅ **全局默认 + Chat ID 特定配置** - 支持为不同群组配置不同消息
- ✅ **管理台可视化配置** - 无需手动编辑文件
- ✅ **支持变量替换** - `{user_name}`, `{chat_id}`, `{chat_type}`, `{timestamp}`

### 快速开始

**通过管理台配置（推荐）：**

1. 访问管理台：`http://your-server:8081/admin`
2. 登录后点击"空闲提示配置"标签页
3. 编辑全局默认配置或添加 Chat ID 特定配置
4. 保存后立即生效 ✨

**消息模板示例：**

```
👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{chat_type}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {chat_type}
🕐 **时间**: {timestamp}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```
```

详细文档：[空闲提示消息配置指南](docs/idle-hint-config-guide.md)

---

## Forward Service（消息转发服务）

Forward Service 是一个独立的服务，用于处理「用户主动发消息 → 目标URL → 返回结果」的反向流程。

### 架构

```
┌─────────────────┐                    ┌─────────────────┐
│   企微机器人 B   │  ←────回调────────   │    企业微信      │
│ (Forward 专用)  │                    │                 │
└────────┬────────┘                    └────────┬────────┘
         │                                      ↑
         │ HTTP                                 │ fly-pigeon
         ▼                                      │
┌─────────────────┐      HTTP        ┌─────────────────┐
│ Forward Service │ ───────────────▶ │    目标 URL     │
│  (内网/DevCloud) │ ◀─────────────── │   (公网服务)    │
└─────────────────┘      响应        └─────────────────┘
```

**与 HIL 链路物理隔离**：使用不同的企微机器人，互不干扰。

### 部署

```bash
# 1. 配置环境变量
export FORWARD_BOT_KEY=your-bot-key      # 新机器人的 Webhook Key
export FORWARD_URL=https://your-api.com/handle  # 目标 URL
export FORWARD_PORT=8083                 # 服务端口（默认 8083）

# 2. 启动服务
nohup python -m forward_service.app >> forward.log 2>&1 &
```

### 配置飞鸽回调

在飞鸽传书后台为**新机器人**配置回调地址：

```
http://your-devcloud-server:8083/callback
```

### 目标 URL 接口规范

Forward Service 会将用户消息转发到目标 URL，目标 URL 需要实现以下接口：

**请求**：
```json
POST /handle
{
    "chat_id": "wokSFfCgAAxxxxxx",
    "chat_type": "group",
    "from_user": {
        "userid": "zhangsan",
        "name": "张三",
        "alias": "zhangsan"
    },
    "msg_type": "text",
    "content": "用户发送的消息内容",
    "image_url": null,
    "raw_data": { ... }
}
```

**响应**：
```json
{
    "reply": "处理结果消息",
    "msg_type": "text"
}
```

| 响应字段 | 类型 | 说明 |
|---------|------|------|
| `reply` | string | 要回复给用户的消息 |
| `msg_type` | string | 消息类型：`text` 或 `markdown` |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FORWARD_BOT_KEY` | 企微机器人 Webhook Key | 必填 |
| `FORWARD_URL` | 默认转发目标 URL | 必填（或配置 FORWARD_RULES） |
| `FORWARD_RULES` | chat_id → URL 映射（JSON） | 可选 |
| `FORWARD_PORT` | 服务端口 | 8083 |
| `FORWARD_TIMEOUT` | 转发请求超时时间（秒） | 30 |

### 高级配置：多目标 URL

如果不同群/私聊需要转发到不同的目标 URL，可以配置 `FORWARD_RULES`：

```bash
export FORWARD_RULES='{"chat_id_1": "https://api1.com/handle", "chat_id_2": "https://api2.com/handle"}'
export FORWARD_URL="https://default-api.com/handle"  # 默认 URL
```

匹配优先级：
1. `FORWARD_RULES` 中的精确匹配
2. `FORWARD_URL` 默认 URL

---

## 项目结构

```
hil-mcp/
├── hil_server/             # HIL Server（公网/内网均可）
│   ├── app.py              # FastAPI 应用
│   ├── config.py           # 配置管理（支持双模式）
│   ├── storage.py          # 会话存储与回调处理
│   ├── sender.py           # Direct 模式：消息发送
│   ├── ws_manager.py       # Relay 模式：WebSocket 管理
│   └── handlers/           # 请求处理器
│       ├── api.py          # HTTP API
│       └── websocket.py    # WebSocket 处理
│
├── devcloud_worker/        # DevCloud Worker（仅 Relay 模式需要）
│   ├── worker.py           # 主程序
│   ├── config.py           # 配置管理
│   ├── sender.py           # 消息发送（调用 fly-pigeon）
│   └── callback_handler.py # 回调转发
│
├── mcp_server/             # MCP 客户端
│   ├── server.py           # MCP Server
│   ├── config.py           # 配置管理
│   └── wecom_client.py     # API 客户端
│
├── forward_service/        # Forward Service（消息转发服务）
│   ├── app.py              # FastAPI 应用
│   ├── config.py           # 配置管理
│   └── sender.py           # 消息发送
│
├── deploy_hil.sh           # HIL Server 部署脚本（示例）
├── deploy_worker.sh        # DevCloud Worker 部署脚本（示例）
├── deploy_forward.sh       # Forward Service 部署脚本（示例）
└── requirements.txt        # Python 依赖
```

---

## 常见问题

### Q: 出现 502 Bad Gateway 错误

**原因**：通常是 Nginx 无法连接到后端服务，或设置了 HTTP 代理。

**解决方案**：
1. 确保 HIL Server 正在运行：`curl http://127.0.0.1:8081/health`
2. 在 MCP 配置中禁用代理：
```json
"env": {
  "http_proxy": "",
  "https_proxy": "",
  "all_proxy": ""
}
```

### Q: Worker 无法连接 HIL Server

**可能原因**：
1. 防火墙阻止了出站连接
2. Nginx 未正确配置 WebSocket 支持
3. Token 不匹配

**排查步骤**：
```bash
# 在 Worker 所在机器测试连接
curl https://your-domain.com/health

# 检查 Worker 日志
tail -f worker.log
```

### Q: 如何获取私聊的 Chat ID？

直接私聊机器人发送任意消息，机器人会自动回复 Chat ID。

### Q: 多个项目同时发消息怎么区分？

使用「引用回复」功能。系统会在每条消息前添加 `[#short_id project_name]` 标识，用户引用回复时会自动匹配。

### Q: Relay 模式下 Worker 断线怎么办？

Worker 会自动重连（指数退避），通常几秒内就能恢复连接。

### Q: 如何检查服务状态？

```bash
# HIL Server（显示运行模式和 Worker 连接状态）
curl https://your-domain.com/health
# 返回示例：
# {"status":"healthy","mode":"relay","worker_connected":true,"worker_count":1}
# {"status":"healthy","mode":"direct"}

# DevCloud Worker
curl http://localhost:8082/health
# 返回示例：
# {"status":"healthy","ws_connected":true}
```

### Q: 没有域名可以使用吗？

可以，但有限制：
1. 使用 IP 访问时，MCP Server 配置需要指定端口：`http://1.2.3.4:80`
2. 如果云服务器安全组仅开放 80/443 端口，需要用 Nginx 反向代理
3. WebSocket 地址需要使用 `ws://`（而非 `wss://`）

推荐使用免费域名 + Let's Encrypt 免费 SSL 证书。

---

## License

MIT
