# HIL-MCP API 文档

## 目录

- [Forward Service API](#forward-service-api)
- [HIL Server API](#hil-server-api)
- [管理命令 (Slash Commands)](#管理命令-slash-commands)

---

## Forward Service API

Forward Service 提供企微消息转发功能，将用户消息转发到 AI Agent。

### 基础端点

#### 健康检查

```
GET /health
```

**响应**
```json
{
  "status": "healthy",
  "config_errors": [],
  "default_bot_key": "xxx...",
  "bots_count": 3,
  "version": "3.0.0"
}
```

#### 回调接口

```
POST /callback
```

接收企微机器人回调消息。

**请求头**
- `x-api-key`: 可选，用于鉴权

**请求体**
```json
{
  "chatid": "群ID或私聊ID",
  "chattype": "group|single",
  "msgtype": "text|image|event",
  "from": {
    "userid": "用户ID",
    "name": "用户名",
    "alias": "用户别名"
  },
  "webhook_url": "企微回调URL",
  "text": {
    "content": "消息内容"
  }
}
```

---

### 管理 API

所有管理 API 都在 `/admin` 路径下。

#### 获取状态

```
GET /admin/status
```

**响应**
```json
{
  "status": "running",
  "bots_count": 3,
  "today_requests": 100,
  "success_rate": 98.5,
  "avg_response_time": 1200
}
```

#### 获取配置

```
GET /admin/config
```

**响应**
```json
{
  "default_bot_key": "xxx",
  "bots": {
    "bot_key": {
      "name": "Bot 名称",
      "target_url": "https://api.example.com/agent",
      "api_key": "xxx",
      "timeout": 60,
      "access_mode": "allow_all",
      "enabled": true
    }
  }
}
```

#### 获取日志

```
GET /admin/logs?limit=20
```

**参数**
- `limit`: 返回日志条数，默认 20

**响应**
```json
{
  "success": true,
  "logs": [
    {
      "id": 1,
      "timestamp": "2026-01-09T10:00:00",
      "bot_name": "jarvis",
      "status": "success",
      "content": "用户消息",
      "response": "Agent 响应",
      "duration_ms": 1200
    }
  ]
}
```

#### 获取统计

```
GET /admin/stats?days=7
```

**参数**
- `days`: 统计天数，默认 7

**响应**
```json
{
  "success": true,
  "stats": {
    "total_requests": 1000,
    "success_count": 980,
    "error_count": 20,
    "success_rate": 98.0,
    "avg_duration_ms": 1200,
    "daily_stats": [...]
  }
}
```

---

### Bot 管理 API

#### 列出所有 Bot

```
GET /admin/bots
```

**响应**
```json
{
  "success": true,
  "bots": [
    {
      "bot_key": "xxx",
      "name": "jarvis",
      "target_url": "https://api.example.com/agent",
      "enabled": true
    }
  ],
  "total": 3
}
```

#### 获取 Bot 详情

```
GET /admin/bots/{bot_key}
```

**响应**
```json
{
  "success": true,
  "bot": {
    "bot_key": "xxx",
    "name": "jarvis",
    "description": "Bot 描述",
    "target_url": "https://api.example.com/agent",
    "api_key": "xxx",
    "timeout": 60,
    "access_mode": "whitelist",
    "enabled": true,
    "whitelist": ["user1", "user2"],
    "blacklist": []
  }
}
```

#### 创建 Bot

```
POST /admin/bots
```

**请求体**
```json
{
  "bot_key": "new-bot-key",
  "name": "新 Bot",
  "target_url": "https://api.example.com/agent",
  "api_key": "optional-key",
  "timeout": 60,
  "access_mode": "allow_all",
  "enabled": true
}
```

#### 更新 Bot

```
PUT /admin/bots/{bot_key}
```

**请求体** (所有字段可选)
```json
{
  "name": "更新后的名称",
  "target_url": "https://new-url.com/agent",
  "enabled": false
}
```

#### 删除 Bot

```
DELETE /admin/bots/{bot_key}
```

---

## HIL Server API

HIL Server 提供 Human-in-the-Loop 功能，让 Agent 能发送消息给用户并等待回复。

### 认证

所有 API 都需要认证，使用 JWT Token。

#### 登录

```
POST /admin/api/login
```

**请求体**
```json
{
  "username": "admin",
  "password": "password"
}
```

**响应**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_at": "2026-01-10T10:00:00"
}
```

#### 验证 Token

```
GET /admin/api/verify
Authorization: Bearer <token>
```

---

### 概览 API

```
GET /admin/api/overview
Authorization: Bearer <token>
```

**响应**
```json
{
  "hil_server": {
    "status": "running",
    "active_sessions": 5,
    "total_sessions": 100
  },
  "forward_service": {
    "status": "running",
    "config": {
      "bots_count": 3
    },
    "stats": {
      "today_requests": 100
    }
  }
}
```

---

### 会话 API

#### 获取 HIL 会话列表

```
GET /admin/api/hil/sessions
Authorization: Bearer <token>
```

**响应**
```json
{
  "total": 10,
  "sessions": [
    {
      "session_id": "xxx",
      "chat_id": "群ID",
      "message": "请确认...",
      "status": "waiting",
      "created_at": "2026-01-09T10:00:00",
      "replied": false
    }
  ]
}
```

---

### Forward 代理 API

HIL Server 可以代理请求到 Forward Service。

```
GET|POST|PUT|DELETE /admin/api/forward/proxy/{path}
Authorization: Bearer <token>
```

将请求转发到 Forward Service 的对应路径。

---

## 管理命令 (Slash Commands)

在企微中发送以下命令可以进行系统管理（需要管理员权限）。

### 系统状态

| 命令 | 说明 |
|------|------|
| `/ping` | 健康检查，返回延迟 |
| `/status` | 详细系统状态 |
| `/help` | 显示帮助信息 |

### Bot 管理

| 命令 | 说明 |
|------|------|
| `/bots` | 列出所有 Bot |
| `/bot <name>` | 查看 Bot 详情（含 URL 和 API Key） |
| `/bot <name> url <新URL>` | 修改 Bot 的目标 URL |
| `/bot <name> key <新Key>` | 修改 Bot 的 API Key |

### 请求监控

| 命令 | 说明 |
|------|------|
| `/pending` | 查看正在处理的请求 |
| `/recent` | 最近 10 条日志 |
| `/errors` | 最近的错误日志 |

### 运维

| 命令 | 说明 |
|------|------|
| `/health` | 检查所有 Agent 的可达性 |

### 会话管理（所有用户可用）

| 命令 | 说明 |
|------|------|
| `/s` 或 `/sess` | 列出最近会话 |
| `/r` 或 `/reset` | 重置当前会话 |
| `/c <id>` 或 `/change <id>` | 切换到指定会话 |
| `/c <id> <消息>` | 切换会话并发送消息 |

---

## 错误处理

所有 API 返回统一的错误格式：

```json
{
  "success": false,
  "error": "错误描述"
}
```

HTTP 状态码：
- `200`: 成功
- `400`: 请求参数错误
- `401`: 未认证
- `403`: 无权限
- `404`: 资源不存在
- `500`: 服务器内部错误
- `503`: 服务不可用
