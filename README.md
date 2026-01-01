# Human-in-the-Loop MCP (WeCom)

企业微信 Human-in-the-Loop MCP 服务，让 AI 能够通过企业微信与用户进行实时交互。

## 功能特性

- 🚀 **发送消息**: AI 可以发送文本和图片消息到企微群或私聊
- ⏳ **等待回复**: 发送消息后可以等待用户回复
- 📷 **图片支持**: 支持发送本地图片文件
- 🔄 **飞鸽集成**: 通过飞鸽传书服务与企业微信交互

## 架构

```
┌─────────────────┐     HTTP      ┌─────────────────┐     飞鸽回调
│   MCP Server    │ ───────────▶ │ DevCloud Service │ ◀─────────────
│   (本地运行)     │              │  (DevCloud 部署) │
└─────────────────┘              └─────────────────┘
        │                                │
        │                                │ 调用飞鸽 API
        ▼                                ▼
   AI Agent                         企业微信
```

## 快速开始

### 1. 安装依赖

```bash
cd hil-mcp

# 使用 pip
pip install -e .

# 或使用 pnpm（如果有 Node.js 环境）
# pnpm install  # 仅用于开发工具
```

### 2. 配置环境变量

```bash
# 复制配置文件
cp .env.example .env

# 编辑配置
vim .env
```

主要配置项：

| 配置项 | 说明 |
|--------|------|
| `DEVCLOUD_SERVICE_URL` | DevCloud 服务地址 |
| `BOT_KEY` | 企微机器人的 Webhook Key |
| `DEFAULT_CHAT_ID` | 默认发送消息的群 ID |
| `CALLBACK_TOKEN` | 飞鸽回调 Token |
| `CALLBACK_AES_KEY` | 飞鸽回调 AES Key |

### 3. 部署 DevCloud 服务

在 DevCloud 上运行：

```bash
cd hil-mcp
python -m devcloud_service.app
```

服务将在 `8080` 端口启动。

### 4. 配置飞鸽传书回调

使用 [飞鸽配置工具](https://nops.woa.com/pigeon/v1/tools/webui#bot) 生成回调配置：

- **URL**: `http://your-devcloud-service/callback`
- **env**: `devcloud`
- **robot_callback_format**: `json`

### 5. 运行 MCP Server

```bash
python -m mcp_server.server
```

### 6. 配置 Cursor/Claude

在 MCP 配置中添加：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/hil-mcp",
      "env": {
        "DEVCLOUD_SERVICE_URL": "http://your-devcloud-service"
      }
    }
  }
}
```

## MCP Tools

### send_and_wait_reply

发送消息并等待用户回复。

**参数**:
- `message` (str): 要发送的消息内容
- `chat_id` (str, 可选): 目标群 ID 或个人会话 ID
- `image_paths` (list[str], 可选): 本地图片文件路径列表
- `timeout` (int, 可选): 等待超时时间，默认 300 秒

**返回**:
```json
{
  "status": "success",
  "replies": [
    {
      "msg_type": "text",
      "content": "用户回复内容",
      "from_user": {"name": "张三", "alias": "zhangsan"},
      "timestamp": "2024-01-01T10:30:00"
    }
  ],
  "message": "收到 1 条回复"
}
```

### send_message_only

仅发送消息，不等待回复。

**参数**:
- `message` (str): 要发送的消息内容
- `chat_id` (str, 可选): 目标群 ID 或个人会话 ID
- `image_paths` (list[str], 可选): 本地图片文件路径列表

## API 接口

### DevCloud 服务

| 接口 | 方法 | 说明 |
|------|------|------|
| `/send` | POST | 发送消息并创建会话 |
| `/callback` | POST | 接收飞鸽回调 |
| `/poll/{session_id}` | GET | 轮询获取回复 |
| `/upload-image` | POST | 上传图片 |
| `/health` | GET | 健康检查 |

## 使用示例

### AI 发送消息并等待确认

```
AI: 我将调用 send_and_wait_reply 工具向您发送确认请求...

[发送消息] "请确认以下方案是否可行：
1. 使用 Redis 作为缓存
2. 部署在 DevCloud 上
3. 使用飞鸽传书作为消息通道

请回复「同意」或「修改」"

[等待用户回复...]

用户回复: "同意，请继续"

AI: 好的，我收到了您的确认，将继续执行...
```

### AI 发送图片

```
AI: 我已生成了架构图，正在发送给您查看...

[调用 send_and_wait_reply]
- message: "这是系统架构图，请审阅："
- image_paths: ["/tmp/architecture.png"]
- timeout: 300

[等待回复...]
```

## 目录结构

```
hil-mcp/
├── mcp_server/                 # MCP Server（本地运行）
│   ├── __init__.py
│   ├── server.py              # FastMCP 主程序
│   ├── wecom_client.py        # DevCloud 服务客户端
│   └── config.py              # 配置
│
├── devcloud_service/           # DevCloud 服务
│   ├── __init__.py
│   ├── app.py                 # FastAPI 主程序
│   ├── storage.py             # 会话存储（JSONL）
│   ├── config.py              # 配置
│   └── handlers/
│       ├── callback.py        # 飞鸽回调处理
│       ├── send.py            # 发送消息
│       └── poll.py            # 轮询接口
│
├── data/                       # 数据目录（运行时创建）
│   └── sessions.jsonl         # 会话存储
│
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## 常见问题

### 1. 用户回复后没有收到？

- 确认用户在企微中 @机器人 回复
- 检查飞鸽回调配置是否正确
- 查看 DevCloud 服务日志

### 2. 图片发送失败？

- 确认图片文件存在且可读
- 检查图片格式（支持 jpg/png/gif/webp）
- 查看上传接口返回的错误信息

### 3. 会话超时？

- 默认超时 300 秒（5分钟）
- 可通过 `timeout` 参数调整
- 超时后需要重新发送消息

## 参考文档

- [飞鸽传书文档](https://iwiki.woa.com/p/541885776)
- [机器人回调文档](https://iwiki.woa.com/p/4012683444)
- [企业微信机器人](https://developer.work.weixin.qq.com/document/path/91770)
- [MCP 规范](https://modelcontextprotocol.io/)

## License

MIT
