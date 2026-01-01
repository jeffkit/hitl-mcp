# Human-in-the-Loop MCP for WeCom (企业微信)

让 AI Agent 能够发送消息到企业微信并等待用户回复的 MCP 服务。

## 功能特性

- 🚀 **发送消息到企微群聊/私聊**
- ⏳ **等待用户回复并返回结果**
- 🎯 **引用回复匹配** - 通过 `[#short_id]` 精确匹配多个并发会话
- 💬 **多会话冲突检测** - 自动提示用户使用引用回复
- ⏰ **20分钟默认超时**
- 📋 **自动回复 chat_id** - 方便用户获取配置信息

## 架构说明

本项目分为两部分：

```
┌─────────────────┐     HTTP      ┌─────────────────┐     飞鸽API    ┌─────────────────┐
│   MCP Server    │ ──────────▶  │ DevCloud Service │ ──────────▶  │   企业微信       │
│   (本地运行)     │              │   (服务器运行)    │ ◀──────────  │   (飞鸽传书)     │
│                 │              │                  │    回调       │                 │
└─────────────────┘              └─────────────────┘              └─────────────────┘
```

- **MCP Server** (`mcp_server/`): 运行在本地，由 Cursor 调用
- **DevCloud Service** (`devcloud_service/`): 运行在服务器上，处理消息发送和回调

## 快速开始

### 1. 准备工作

1. **创建企微机器人**
   - 在企业微信中创建群机器人，获取 Webhook Key
   - 配置回调地址（飞鸽传书）

2. **准备服务器**
   - 需要一台可访问的服务器（用于接收企微回调）
   - Python 3.10+

### 2. 部署 DevCloud Service（服务器端）

```bash
# 克隆代码到服务器
git clone <your-repo-url>
cd hil-mcp

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
vim .env
```

**必填配置：**
```bash
# 机器人的 Webhook Key（必填）
BOT_KEY=your-bot-key-here
```

**启动服务：**
```bash
# 直接启动
python -m devcloud_service.app

# 或后台运行
nohup python -m devcloud_service.app >> devcloud.log 2>&1 &
```

### 3. 配置飞鸽传书回调

在飞鸽传书管理后台配置回调地址：
```
http://your-server:8080/callback
```

### 4. 配置 MCP Server（本地端）

在 Cursor 的 MCP 配置文件中添加（`~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/hil-mcp",
      "env": {
        "DEVCLOUD_SERVICE_URL": "http://your-server:8080",
        "DEFAULT_CHAT_ID": "your-chat-id",
        "DEFAULT_TIMEOUT": "1200",
        "POLL_INTERVAL": "2",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

**配置说明：**
- `DEVCLOUD_SERVICE_URL`: DevCloud 服务的访问地址
- `DEFAULT_CHAT_ID`: 默认发送消息的 Chat ID（群聊或私聊）
- `DEFAULT_TIMEOUT`: 等待回复超时时间（秒），默认 1200（20分钟）
- `http_proxy` 等: 设置为空以禁用代理

### 5. 获取 Chat ID

方法1：直接在企微中 @机器人 发送任意消息，机器人会自动回复 Chat ID

方法2：查看服务器日志，找到 `chatid` 字段

## 使用方法

### AI Agent 调用示例

```python
# 发送消息并等待回复
result = await send_and_wait_reply(
    message="请确认是否继续？",
    project_name="my-project",  # 可选，用于标识消息来源
    timeout=300  # 可选，超时时间（秒）
)

# 仅发送消息，不等待回复
result = await send_message_only(
    message="任务已完成！"
)
```

### 用户回复方式

1. **单会话场景**：直接回复即可
2. **多会话场景**：使用「引用回复」功能精确选择要回复的消息

## 一键部署

修改代码后，使用部署脚本快速同步到服务器：

```bash
./deploy.sh
```

## 环境变量说明

### 服务器端（.env）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEVCLOUD_PORT` | 服务监听端口 | 8080 |
| `BOT_KEY` | 机器人 Webhook Key | 必填 |
| `CALLBACK_AUTH_KEY` | 回调鉴权 Key | 可选 |
| `CALLBACK_AUTH_VALUE` | 回调鉴权 Value | 可选 |
| `DATA_DIR` | 数据存储目录 | ./data |
| `SESSION_EXPIRE_SECONDS` | 会话过期时间 | 3600 |

### 本地端（Cursor MCP 配置）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEVCLOUD_SERVICE_URL` | 服务地址 | 必填 |
| `DEFAULT_CHAT_ID` | 默认 Chat ID | 必填 |
| `DEFAULT_TIMEOUT` | 超时时间（秒） | 1200 |
| `POLL_INTERVAL` | 轮询间隔（秒） | 2 |

## 常见问题

### Q: 出现 502 Bad Gateway 错误
A: 检查是否设置了 HTTP 代理。在 MCP 配置中添加空代理设置：
```json
"http_proxy": "",
"https_proxy": "",
"all_proxy": ""
```

### Q: 如何获取私聊的 Chat ID？
A: 直接私聊机器人发送任意消息，机器人会自动回复 Chat ID。

### Q: 多个项目同时发消息怎么区分？
A: 使用「引用回复」功能。系统会在每条消息前添加 `[#short_id project_name]` 标识，用户引用回复时会自动匹配。

## 开发说明

### 项目结构

```
hil-mcp/
├── devcloud_service/       # 服务端代码
│   ├── app.py              # FastAPI 应用
│   ├── config.py           # 配置管理
│   ├── storage.py          # 会话存储
│   └── handlers/           # 请求处理器
│       ├── callback.py     # 飞鸽回调处理
│       ├── send.py         # 发送消息
│       └── poll.py         # 轮询回复
├── mcp_server/             # MCP 客户端代码
│   ├── server.py           # MCP Server
│   ├── config.py           # 配置管理
│   └── wecom_client.py     # API 客户端
├── deploy.sh               # 一键部署脚本
├── .env.example            # 环境变量示例
└── requirements.txt        # Python 依赖
```

### 依赖

- Python 3.10+
- FastAPI
- fly-pigeon（腾讯内部飞鸽传书 SDK）
- mcp（Model Context Protocol SDK）
- pydantic-settings

## License

MIT
