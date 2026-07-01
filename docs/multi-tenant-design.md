# HIL-MCP 多租户设计文档

> 📅 创建日期: 2026-01-04
> 📌 状态: 设计阶段

## 1. 需求背景

当前 HIL-MCP 部署一套服务只能支持单个用户使用。为了让团队成员能够共享同一套部署好的服务，需要支持多租户功能。

### 1.1 核心需求

1. **多用户接入**: 一套 HIL Server 部署，支持多个用户同时使用
2. **租户隔离**: 不同用户的消息和会话完全隔离，不会互相串扰
3. **独立配置**: 每个用户可以配置自己的 chat_id、project_name 等
4. **向后兼容**: 现有用户无需修改配置即可继续使用

### 1.2 使用场景

| 场景 | 描述 |
|------|------|
| 团队共享 | 团队内多人共用一套服务，各自使用独立的企微群/私聊 |
| 多项目 | 同一用户在不同项目中使用不同的租户配置 |
| 多 Agent | 同一租户下多个 Agent 并发使用（已支持） |

---

## 2. 方案设计

### 2.1 方案选择

经讨论，采用 **隐式标识** 方案：

- **租户 ID 不在消息中显示**，保持消息简洁
- 服务端通过存储结构管理租户隔离
- 回调匹配通过 short_id（全局唯一）进行

### 2.2 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          MCP Servers                             │
│                                                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │ User: Alice   │  │ User: Bob     │  │ User: Alice   │        │
│  │ tenant=alice  │  │ tenant=bob    │  │ tenant=alice  │        │
│  │ chat_id=群A   │  │ chat_id=群B   │  │ chat_id=群C   │        │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘        │
│          │                  │                  │                 │
│          └──────────────────┼──────────────────┘                 │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    HIL Server (公网)                       │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │ MultiTenantStorage                                    │ │  │
│  │  │                                                       │ │  │
│  │  │ sessions: { session_id -> Session(tenant_id, ...) }  │ │  │
│  │  │ short_id_map: { short_id -> session_id }             │ │  │
│  │  │ chat_sessions: { chat_id -> [session_id] }           │ │  │
│  │  │ tenant_sessions: { tenant_id -> {session_id} }       │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  │                                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                             │                                    │
│                             ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │               内置引擎（ilink / wecom-aibot）              │  │
│  │  维持微信/企微长连接，进程内收发消息                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据结构设计

### 3.1 Session 结构

```python
@dataclass
class Session:
    session_id: str       # 唯一标识
    short_id: str         # 前 8 位 UUID，用于消息标识
    tenant_id: str        # 租户标识（新增）
    chat_id: str          # 群/私聊 ID
    chat_type: str        # group / single
    message: str          # 原始消息内容
    project_name: str     # 项目名称
    status: str           # waiting / replied / timeout
    replies: list[dict]   # 用户回复列表
    created_at: datetime
    expire_at: datetime
```

### 3.2 存储索引结构

```python
class MultiTenantStorage:
    # 主存储：所有会话（全局）
    _sessions: dict[str, Session] = {}  # session_id -> Session
    
    # 全局索引：short_id 全局唯一
    _short_id_map: dict[str, str] = {}  # short_id -> session_id
    
    # chat_id 索引（跨租户）
    _chat_sessions: dict[str, list[str]] = {}  # chat_id -> [session_id]
    
    # 租户索引（用于租户级别的查询和清理）
    _tenant_sessions: dict[str, set[str]] = {}  # tenant_id -> {session_id}
```

---

## 4. API 变更

### 4.1 发送消息接口

**POST /api/send**

```json
{
    "message": "请确认这个修改...",
    "chat_id": "wokSFfCgAAxxxxxx",
    "tenant_id": "alice",           // 新增：租户标识
    "project_name": "my-project",
    "timeout": 300
}
```

### 4.2 MCP 配置

```json
{
    "mcpServers": {
        "wecom-hil": {
            "command": "python",
            "args": [
                "-m", "mcp_server.server",
                "--service-url", "https://hil.example.com",
                "--tenant-id", "alice",       // 新增
                "--chat-id", "wokSFfCgAAxxxxxx",
                "--project-name", "my-project"
            ]
        }
    }
}
```

---

## 5. 回调匹配逻辑

### 5.1 匹配流程

```python
async def handle_callback(data: dict) -> dict:
    chat_id = data.get("chatid")
    reply, short_id = extract_reply_from_callback(data)
    
    # 步骤1: 优先用 short_id 匹配（全局唯一，跨租户）
    if short_id:
        session = await get_session_by_short_id(short_id)
        if session:
            # 找到了，tenant_id 自动确定
            return add_reply(session, reply)
    
    # 步骤2: 回退到 chat_id 匹配
    waiting_sessions = await get_waiting_sessions_by_chat_id(chat_id)
    
    if len(waiting_sessions) == 0:
        # 没有等待中的会话
        return send_chat_id_hint(chat_id)
    
    elif len(waiting_sessions) == 1:
        # 只有一个等待中的会话，直接匹配
        return add_reply(waiting_sessions[0], reply)
    
    else:
        # 多个会话等待中（可能来自不同租户）
        # 提示用户使用引用回复
        return send_multiple_sessions_hint(chat_id, waiting_sessions)
```

### 5.2 场景处理

| 场景 | 处理方式 |
|------|----------|
| 不同租户 + 不同 chat_id | 完全隔离，各自匹配 ✅ |
| 不同租户 + 相同 chat_id | 通过引用回复区分 |
| 同一租户 + 相同 chat_id | 通过引用回复区分（现有逻辑） |
| 无租户 ID 配置 | 使用默认租户 `_default` |

---

## 6. 向后兼容

### 6.1 默认租户

- 不传 `tenant_id` 时，使用默认租户 `_default`
- 现有用户无需修改配置

### 6.2 消息格式不变

```
[#abc12345 my-project]
请确认这个修改...
```

租户 ID **不显示** 在消息中。

---

## 7. 实现计划

### 7.1 Phase 1: 基础多租户支持

- [ ] 修改 Session 数据结构，添加 tenant_id 字段
- [ ] 修改 Storage 类，支持多租户索引
- [ ] 修改 /api/send 接口，接收 tenant_id 参数
- [ ] 修改 MCP Server，添加 --tenant-id 参数

### 7.2 Phase 2: 增强功能

- [ ] 租户级别的统计和监控
- [ ] 租户级别的超时配置
- [ ] 租户白名单/黑名单

### 7.3 Phase 3: 管理功能（可选）

- [ ] 租户管理 API
- [ ] 租户使用量统计
- [ ] 租户隔离的消息历史

---

## 8. 风险和考虑

### 8.1 技术风险

| 风险 | 缓解措施 |
|------|----------|
| 同一 chat 多租户混淆 | 提示用户使用引用回复 |
| 租户 ID 泄露 | 租户 ID 不在消息中显示 |
| 性能问题 | 使用索引优化查询 |

### 8.2 用户体验

- 保持消息简洁，不增加视觉负担
- 多会话冲突时给出清晰提示
- 提供引用回复的操作指引

---

## 9. 附录

### 9.1 环境变量配置

```bash
# MCP Server 环境变量
HIL_SERVICE_URL=https://hil.example.com
HIL_TENANT_ID=alice
HIL_CHAT_ID=wokSFfCgAAxxxxxx
HIL_PROJECT_NAME=my-project
```

### 9.2 完整 MCP 配置示例

```json
{
    "mcpServers": {
        "wecom-hil-alice": {
            "command": "python",
            "args": [
                "-m", "mcp_server.server",
                "--service-url", "https://hil.example.com",
                "--tenant-id", "alice",
                "--chat-id", "wokSFfCgAAxxxxxx",
                "--project-name", "alice-project"
            ]
        },
        "wecom-hil-bob": {
            "command": "python",
            "args": [
                "-m", "mcp_server.server",
                "--service-url", "https://hil.example.com",
                "--tenant-id", "bob",
                "--chat-id", "wokSFfCgAAyyyyyy",
                "--project-name", "bob-project"
            ]
        }
    }
}
```
