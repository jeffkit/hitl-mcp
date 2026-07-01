# hitl-mcp API 文档

## 目录

- [公共 API（/api）](#公共-apiapi)
- [管理 API（/admin/api）](#管理-apiadminapi)

---

## 公共 API（/api）

供 MCP 客户端调用，无需认证。

### 健康检查

```
GET /api/health
```

```json
{ "status": "healthy" }
```

### 发送消息

```
POST /api/send
```

**请求体**
```json
{
  "message": "请确认是否执行",
  "chat_id": "群ID或用户ID",
  "chat_type": "group",
  "images": ["data:image/png;base64,..."],
  "project_name": "my-project",
  "timeout": 1200,
  "wait_reply": true,
  "bot_key": "ilink-bot-1",
  "upstream": "ilink"
}
```

- `upstream`：`ilink` | `wecom-aibot`（冗余校验，与 `bot_key` 配合路由到内置引擎）
- `wait_reply=false` 时只发不创建会话
- 未命中已启动的内置引擎时返回 `engine_not_started`

**响应**
```json
{ "success": true, "session_id": "xxx", "message": "消息发送成功" }
```

### 轮询回复

```
GET /api/poll/{session_id}
```

```json
{
  "session_id": "xxx",
  "status": "waiting",
  "has_reply": false,
  "replies": [],
  "message": "会话状态: waiting"
}
```

`status`：`waiting` | `replied` | `timeout` | `error` | `not_found`

### 标记会话超时

```
POST /api/session/{session_id}/timeout
```

### 上传图片

```
POST /api/upload-image
Content-Type: multipart/form-data
```

返回 data URL，可直接放入 `/api/send` 的 `images` 字段。

```json
{ "success": true, "image_url": "data:image/png;base64,..." }
```

### iLink 登录

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/ilink/qr?bot_key=ilink-bot-1` | 获取扫码二维码 |
| GET | `/api/ilink/login_status?bot_key=ilink-bot-1` | 查询登录状态 |
| GET | `/api/ilink/activated_users?bot_key=ilink-bot-1` | 列出已激活用户 |

引擎未启动时返回 `{"status":"error","error":"iLink 引擎未启动..."}`。

### 动态启动企微 AI Bot 引擎

```
POST /api/engines/wecom-aibot/start
```

```json
{ "bot_id": "...", "bot_secret": "...", "bot_key": "wecom-aibot-1" }
```

幂等：同 `bot_key` 同凭证已运行则 no-op；凭证变化则停旧起新。

---

## 管理 API（/admin/api）

管理台使用，需 JWT 认证（`Authorization: Bearer <token>`）。

### 认证

```
POST /admin/api/login     # { "username": "admin", "password": "..." } → { "token", "expires_at" }
GET  /admin/api/verify    # 验证 token
```

### 引擎管理

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/admin/api/engines` | 列出所有内置引擎及状态 |
| POST | `/admin/api/engines/ilink/start` | 启动 iLink 引擎 |
| GET | `/admin/api/engines/ilink/qr` | 获取 iLink 二维码 |
| GET | `/admin/api/engines/ilink/status` | 查询 iLink 状态 |
| POST | `/admin/api/engines/wecom-aibot/start` | 启动企微 AI Bot 引擎 |
| POST | `/admin/api/engines/wecom-aibot/stop` | 停止企微 AI Bot 引擎 |

### 会话管理

```
GET /admin/api/hil/sessions
```

返回最近会话列表。

---

## 错误处理

```json
{ "success": false, "error": "错误描述" }
```

HTTP 状态码：`200` 成功 · `400` 参数错误 · `401` 未认证 · `403` 无权限 · `404` 不存在 · `500` 服务器错误 · `503` 服务不可用
