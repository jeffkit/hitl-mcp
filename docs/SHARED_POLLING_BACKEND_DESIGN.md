# 共享轮询后端设计（iLink / WeCom AI Bot 接入 HIL Server）

**最后更新：2026-06-30**

## 0. 架构演进（2026-06-30）：内置引擎单进程

本文档最初设计的是"独立 Worker 进程 + WS 注册"的共享轮询后端。**已落地后随即演进为"内置引擎单进程"**，部署更轻。原设计内容（§1–§10）**仅作历史背景保留**——其中描述的 Worker / WS relay / fly-pigeon / devcloud-worker 路径已全部移除，不再可用。当前唯一架构是 HITL Server 内置 ilink + wecom-aibot 引擎。

### 0.1 演进动机

独立 Worker 架构虽解决了多实例冲突，但本机部署要起 **2 个进程**（HIL Server + ilink-worker）、2 份 venv、2 个 launchd 服务、4 个环境变量，门槛偏高。而 Worker 本就是单例常驻——和同样单例常驻的 HIL Server 是同类资源，没有理由分两个进程。

### 0.2 新架构：内置引擎（in-process）

把 iLink / wecom-aibot 的长连接逻辑作为 HIL Server 的**内置引擎**直接跑在 HIL Server 进程内：

- 新增 `hil_server/engines/`（`base.py` 抽象 + `manager.py` 单例 + `ilink.py` 引擎）
- 引擎收到上游消息 → 进程内直接调 `storage.handle_callback`（**不走 WS**）
- `/api/send` 命中内置引擎 → 进程内直接调 `engine.send_message`（**不走 WS**）
- `/api/ilink/*` → 直接调内置 ilink 引擎
- `app.py` lifespan 按配置（`ENABLE_ILINK_ENGINE` 等）启动启用引擎

```
Cursor/Agent ─stdio─▶ mcp-server-ts ─HTTP─▶ HIL Server（单进程，内置 ilink engine + 未来 wecom-aibot engine）
```

### 0.3 兼容性保留

- **WS 外部 Worker 接口已全部移除（2026-06-30）**：`ws_manager`、`handlers/websocket.py`、`sender.py`、`handlers/forward_client.py`、`slash_commands.py`、`idle_hint_config.py` 均已删除；`packages/devcloud-worker` / `packages/forward-service` / `packages/ws-tunnel` 三个包已删除；MCP 端 `hil` 引擎已删除。relay / direct（fly-pigeon）模式不再存在。`/api/send` 仅命中内置引擎，未命中则返回 `engine_not_started`。
- **`packages/ilink-worker` 已移除（2026-06-30）**：内置 ilink 引擎落地后，独立 ilink-worker 进程不再需要，原本"远程部署可选方案"的降级路径一并废弃。iLink 长轮询统一由 HITL Server 进程内维持。原 §1–§10 中涉及 ilink-worker / wecom-aibot-worker 的设计仅作历史背景保留。

### 0.4 部署变化

- **改之前**：launchd 管 2 个 plist（HIL Server + ilink-worker）
- **改之后**：launchd 管 1 个 plist（HIL Server，环境变量 `ENABLE_ILINK_ENGINE=true`）
- `hitl-mcp ilink-setup` 一键完成：建 venv → 写单个 plist → load → 扫码 → 打印 Cursor 配置

### 0.5 wecom-aibot 已落地

`hil_server/engines/wecom_aibot.py` 已按同样模式落地，配置 `ENABLE_WECOM_AIBOT_ENGINE`，亦支持管理台运行时启动（`/api/engines/wecom-aibot/start`），无需独立 worker 包。

---

## 1. 背景与问题

### 1.1 现状

`mcp-server-ts` 当前支持三种引擎：

| 引擎 | 上游协议 | 长连接持有位置 |
|---|---|---|
| `hil` | HTTP（调 HIL Server） | 无（瘦客户端） |
| `wecom-aibot` | 企微 AI Bot WebSocket | **MCP 进程内** |
| `ilink` | iLink HTTP 长轮询 | **MCP 进程内** |

### 1.2 结构性矛盾

MCP server 走 stdio 协议，**每个 MCP 客户端（每个 Cursor 窗口 / 每个 Agent）各 spawn 一个进程**。而 iLink 长轮询与 wecom-aibot WebSocket 都是"每个凭证只能维持一个"的单例资源，却被部署在"天然多实例"的 MCP 进程里。于是多实例并发时：

- **iLink**：服务端对单个 `vtoken` 只允许 1 个并发长轮询，多进程互斥，返回
  `HTTP 429 {"ret":429,"errmsg":"too many concurrent polls for this vtoken"}`，
  **所有实例都拉不到消息 → 收不到用户回复**。
- **wecom-aibot**：协议有 `disconnected_event`，新连接上线会把旧连接踢掉，多进程**反复互踢、连接抖动**。

清理僵尸进程只是治标。多窗口 / 多 Agent 必然复发。

### 1.3 目标

把 iLink 与 wecom-aibot 的长连接从 MCP 进程内**收敛到一个常驻后端**，MCP 端做成瘦 HTTP 客户端。复用现有 HIL Server 形态，扩展其 Worker 类型。

### 1.4 范围与决策

- **部署形态**：纯个人单机（本机常驻 daemon）。HIL Server 既可本机跑也可服务器跑，本次不做多租户，但保留 `BOT_KEY` + 访问规则字段以便未来演进。
- **直连模式**：**废弃**。`mcp-server-ts` 的 `ilink` / `wecom-aibot` 引擎改为 HTTP 客户端，删除进程内长轮询 / WS / token-store / 扫码状态机。
- **登录方案**：**方案 B**——HIL Server 暴露二维码与登录状态接口，MCP 端保留现有 `login_required` + `wait_for_login` 的 Agent 交互体验；admin console 作为二维码展示兜底。

---

## 2. 目标架构

```
Cursor 窗口1 ─┐
Cursor 窗口2 ─┼─stdio─▶ hitl-mcp（瘦 HTTP 客户端）─▶ 本机 HIL Server（常驻，:8081）
Cursor 窗口3 ─┘                                              │
                                                              │  Worker ←WS→ Server（现有 relay 通道）
                                                              ├─ devcloud-worker      （fly-pigeon，现有）
                                                              ├─ ilink-worker         （iLink 长轮询，新增）
                                                              └─ wecom-aibot-worker   （企微 AI Bot WS，新增）
```

### 2.1 职责划分

- **MCP 端（`mcp-server-ts`）**：纯 HTTP 客户端。调 HIL Server 的 `/api/send`、`/api/poll/{session_id}`，以及 iLink 登录相关的 `/api/ilink/qr`、`/api/ilink/login_status`。不持有任何长连接、不存 token、不做会话匹配。
- **HIL Server（`hil-server`）**：常驻。统一会话管理（`hil_sessions`、`[#short_id]` 匹配、超时清理）、Worker 注册与请求路由、对外 HTTP API。
- **Worker**：每种上游一个 Worker 进程，持凭证、维持单例长连接，通过现有 WS 通道向 Server 注册并上报收到的用户消息、响应 Server 下行的发送请求。

### 2.2 会话匹配统一在 Server 端

三种引擎的会话匹配语义统一由 HIL Server 的 `storage.handle_callback` 承担（`[#short_id]` 精确匹配 / 正文匹配 / FIFO 兜底）。Worker 只做"收消息→上报、发消息→送上游"，不自行匹配。

---

## 3. Worker 协议扩展

现有 Worker→Server 已有协议：`register` / `request`(`action`+`payload`) / `response` / `callback` / `ping`/`pong`。本次扩展。

### 3.1 注册信息增加 `worker_type`

```jsonc
// Worker → Server
{
  "type": "register",
  "worker_info": {
    "worker_id": "ilink-1",
    "worker_type": "ilink",        // 新增：fly-pigeon | ilink | wecom-aibot
    "bot_key": "ilink-bot-1",      // 凭证标识，用于 Server 路由发送请求
    "ip_address": "...",
    "hostname": "..."
  }
}
```

`ws_manager` 按 `worker_type` + `bot_key` 索引，发送时按目标 bot 路由到对应 Worker。

### 3.2 上行：用户消息上报（统一 callback 形态）

Worker 收到上游用户消息后，统一转成 HIL Server 已有的回调数据结构上报，复用 `storage.handle_callback`：

```jsonc
// Worker → Server
{
  "type": "callback",
  "event": "user_message",
  "worker_type": "ilink",
  "bot_key": "ilink-bot-1",
  "data": {
    "chatid": "o9cq80_xxx@im.wechat",   // 统一字段名，ilink 用 from_user_id
    "chattype": "single",                // ilink/wecom-aibot 单聊为主
    "msgtype": "text",
    "text": { "content": "OK了" },
    "from": { "userid": "o9cq80_xxx@im.wechat", "name": "" },
    "quotes": ["[#abc123] ..."]          // 可选：引用文本，供 short_id 精确匹配
  }
}
```

Server 端新增一个内部入口（与现有 `/api/callback` 共用 `storage.handle_callback`），从 WS `callback` 消息路由进来，避免给每种 Worker 各开一个 HTTP 回调端点。

### 3.3 下行：发送消息（Server → Worker）

Server 收到 `/api/send` 后，按 `bot_key` 路由 `send_message` 请求给对应 Worker：

```jsonc
// Server → Worker
{
  "type": "request",
  "id": "<req_id>",
  "action": "send_message",
  "payload": {
    "short_id": "abc123",
    "message": "[#abc123] [proj]\n你好\n\n> 请引用回复此消息",
    "chat_id": "o9cq80_xxx@im.wechat",
    "chat_type": "single",
    "project_name": "proj",
    "wait_reply": true
  }
}
```

Worker 内部把 `chat_id` 映射为各自上游所需的收件人字段：

- `ilink-worker`：`chat_id` → `to_user_id`，从本地 token-store 取对应 `context_token`，调 `/ilink/bot/sendmessage`。
- `wecom-aibot-worker`：`chat_id` → `chatid`，走 `aibot_send_msg`。

消息头 `[#short_id]` 由 **Server 端统一拼接**（与现有 hil 行为一致），Worker 透传原文，不再各自格式化。

### 3.4 登录（仅 iLink）

iLink 的扫码登录是 worker 的事，但二维码要展示给 MCP 端的 Agent。详见 §5。

---

## 4. HIL Server 改动

### 4.1 `ws_manager`：按 worker_type + bot_key 路由

- 注册时记录 `worker_type`、`bot_key`。
- `send_request` 增加 `bot_key` 参数，路由到对应 Worker；现有无 `bot_key` 的请求保持默认 Worker（向后兼容 devcloud-worker）。

### 4.2 `/api/send`：支持按 bot_key 路由 + 多上游

`SendMessageRequest` 增加可选字段：

```python
class SendMessageRequest(BaseModel):
    message: str
    chat_id: str | None = None
    chat_type: str = "group"
    project_name: str | None = None
    timeout: int | None = None
    wait_reply: bool = True
    bot_key: str | None = None        # 新增：指定走哪个 bot/worker
    upstream: str | None = None       # 新增：fly-pigeon | ilink | wecom-aibot（冗余，便于校验）
```

发送逻辑：

- `upstream=ilink` 或 `bot_key` 命中 ilink-worker → 走 WS `send_message` 给该 Worker。
- `upstream=wecom-aibot` 同理。
- 现有 fly-pigeon 行为不变。

会话创建、`short_id` 生成、`[#short_id]` 头拼接、超时管理全部复用现有 `storage` 逻辑。

### 4.3 用户消息入口：WS callback → storage.handle_callback

新增内部处理：收到 WS `type=callback, event=user_message` 时，转换为 `storage.handle_callback` 所需的 dict 并调用，与 `/api/callback` 走同一匹配路径。匹配结果（`session_id`、`match_method`）日志与现有一致。

### 4.4 iLink 登录接口（方案 B）

新增两个 HTTP 接口，转发给 ilink-worker：

```
GET  /api/ilink/qr?bot_key=ilink-bot-1
     → { status, qr_url, qr_base64, qrcode_key }
     worker 内部：若无 pending QR 则申请新二维码，启动后台轮询；若已有则复用。

GET  /api/ilink/login_status?bot_key=ilink-bot-1
     → { status: "pending" | "success" | "expired" | "not_started" }
```

实现：Server 通过 WS 向 ilink-worker 发 `request`（`action=get_qr` / `get_login_status`），worker 返回结果。登录状态由 worker 持有（就是现有 `pendingQR` 状态机搬过来）。

### 4.5 admin console 兜底

ilink-worker 申请到二维码时，Server 同时在 admin console 推送一条通知并展示同一二维码。Agent 没展示好时，用户本人可在 `localhost:8081/admin` 看到。

---

## 5. iLink 登录流程时序（方案 B）

```
Agent                MCP(ilink HTTP 客户端)        HIL Server              ilink-worker           iLink API
 │  send_and_wait_reply │                            │                         │                      │
 ├─────────────────────▶│ POST /api/send             │                         │                      │
 │                      ├───────────────────────────▶│ WS request send_message │                      │
 │                      │                            ├────────────────────────▶│ 检查 bot_token       │
 │                      │                            │                         │ 无 token → 返回      │
 │                      │                            │◀────────────────────────│ {success:false,      │
 │                      │                            │  Server 判定 login_required                    │
 │                      │◀───────────────────────────│  返回 {status:login_required}                  │
 │                      │  (MCP 内部再调 /api/ilink/qr 取二维码，组装结果)                            │
 │ login_required+qrUrl │                            │                         │                      │
 │◀─────────────────────│                            │                         │                      │
 │  wait_for_login      │                            │                         │                      │
 ├─────────────────────▶│ 轮询 /api/ilink/login_status                        │                      │
 │                      ├───────────────────────────▶│ WS request             │                      │
 │                      │                            ├────────────────────────▶│ 后台轮询             │
 │                      │                            │                         │  get_qrcode_status  │
 │                      │                            │                         ├─────────────────────▶│
 │                      │                            │                         │◀──── confirmed ──────│
 │                      │                            │                         │ setBotToken          │
 │                      │                            │◀────────────────────────│ status: success      │
 │                      │◀───────────────────────────│ status: success         │                      │
 │ success              │                            │                         │                      │
 │◀─────────────────────│  Agent 重试 send_and_wait_reply（此时已登录，正常发送）│                      │
```

MCP 端 `wait_for_login` 工具保留，内部实现从"await pendingQR.promise"改为"轮询 `/api/ilink/login_status` 直到 success/expired"，语义等价。

---

## 6. MCP 端瘦身（`mcp-server-ts`）

### 6.1 `ilink` 引擎改为 HTTP 客户端

删除：`_pollLoop` / `_processUpdate` / `_ensureLoggedIn` / `_pollLoginInBackground` / `pendingQR` 状态机 / `TokenStore` 依赖 / `ilinkHeaders` / `_sendMessage` 等所有直连逻辑。

保留并改造：

- `sendAndWait`：调 `POST /api/send`（带 `upstream=ilink`、`bot_key`），拿 `session_id`，轮询 `/api/poll/{session_id}`（与 `hil` 引擎一致）。
- `sendOnly`：调 `POST /api/send`（`wait_reply=false`）。
- `waitForLogin`：轮询 `/api/ilink/login_status`。
- `listActivatedUsers`：改为调 Server（Server 向 worker 询问已知用户列表），或直接由 Server 维护一份"已激活用户"缓存（从收到的 `user_message` 中记录 `chat_id`）。推荐后者，避免多一次 WS 往返。

### 6.2 `wecom-aibot` 引擎改为 HTTP 客户端

删除：WS 连接 / `_connect` / `_handleMessage` / 心跳 / 重连 / `_sendRaw` / `_pending` 等。

保留并改造：

- `sendAndWait` / `sendOnly`：调 `POST /api/send`（`upstream=wecom-aibot`、`bot_key`），轮询 `/api/poll/{session_id}`。

### 6.3 配置

`mcp-server-ts` 的 ilink/wecom-aibot 选项收敛为指向 HIL Server：

```
hitl-mcp --engine ilink --service-url http://localhost:8081 --bot-key ilink-bot-1
hitl-mcp --engine wecom-aibot --service-url http://localhost:8081 --bot-key wecom-bot-1
```

移除 `--base-url`、`--token-store`、`--bot-id`、`--bot-secret`（这些凭证移到 worker 配置）。

### 6.4 shortId

MCP 端不再生成 shortId，也不再自行格式化消息头——与现有 `hil` 引擎一致，由 HIL Server 端统一生成 `short_id` 并拼接 `[#short_id]` 头。本次会话中已给 ilink/wecom-aibot 加的 TS 端 shortId 逻辑在迁移完成后删除。

---

## 7. Worker 实现迁移

### 7.1 `ilink-worker`（新增 `packages/ilink-worker`）

直接搬迁现有 `mcp-server-ts/src/engines/ilink.ts` 的上游交互代码到 Python（与 devcloud-worker 同栈，便于复用 WS 客户端骨架）：

- 长轮询 `_pollLoop` → 收到 `msgs` 后转成 §3.2 的统一 callback 上报 Server。
- `sendmessage` → 处理 Server 下行的 `send_message` 请求。
- 扫码登录：`get_bot_qrcode` / `get_qrcode_status` / `bot_token` 持久化（复用现有 token-store 文件结构）。
- 凭证 `bot_token`、`get_updates_buf`、`context_tokens` 由 worker 本地文件持久化。

### 7.2 `wecom-aibot-worker`（新增 `packages/wecom-aibot-worker`）

搬迁现有 `mcp-server-ts/src/engines/wecom-aibot.ts` 的 WS 逻辑：

- `aibot_subscribe` 鉴权 + 心跳 + 重连。
- `aibot_msg_callback` → 转成 §3.2 callback 上报（含 quotes 提取）。
- `aibot_send_msg` → 处理 Server 下行 `send_message`。
- 凭证 `bot_id`/`bot_secret` 由 worker 持有。

### 7.3 复用 devcloud-worker 的 WS 客户端骨架

三个 worker 共享一套 WS 连接 / 注册 / 心跳 / 请求响应 / 重连代码。建议抽出 `packages/worker-common`（或 devcloud-worker 内部模块化），避免三份重复。

---

## 8. 迁移步骤（建议顺序）

1. **HIL Server：扩展 ws_manager 按 worker_type+bot_key 路由**，`/api/send` 增加 `bot_key`/`upstream` 字段，保持现有 fly-pigeon 行为不变。加 WS callback → `storage.handle_callback` 入口。
2. **ilink-worker**：搬迁上游交互代码，接上 WS，本地验证"收消息→上报→Server 匹配→/api/poll 返回"。
3. **MCP 端 ilink 引擎改 HTTP 客户端**，端到端验证（含扫码登录方案 B）。
4. **wecom-aibot-worker + MCP 端 wecom-aibot 引擎改造**，同上验证。
5. **删除 MCP 端直连代码**（`token-store`、进程内轮询/WS、`--base-url`/`--token-store`/`--bot-id`/`--bot-secret` 选项、TS 端 shortId 逻辑）。
6. **本机部署 daemon**：HIL Server + 三个 worker 用 launchd / systemd user service 常驻，文档化启动方式。
7. **回归 hil 引擎**，确认未受影响。

每一步都可独立验证、可独立回滚。

---

## 9. 风险与注意点

- **多了一跳延迟与故障域**：MCP → Server → worker → 上游。个人单机场景可接受；需注意 Server / worker 挂了要有清晰报错。
- **凭证归属**：bot_token / bot_secret 移到 worker 配置文件，注意权限（`chmod 600`），不要进 git。
- **本机 daemon 运维**：需要文档化"怎么启动、怎么看日志、怎么重启"，否则会重蹈僵尸进程覆辙（虽然不再互斥 429，但残留进程仍浪费资源）。
- **wecom-aibot 多实例兜底**：即便收敛到单 worker，仍要保证只起一个 worker 进程（同凭证）。可在 worker 启动时写 PID lock 文件，重复启动直接退出并提示。
- **ilink `get_updates_buf` 丢失**：游标为空可能导致历史消息洪流。worker 启动时若 buf 为空，应跳过或限速处理首批消息，避免冲击 Server 匹配逻辑。
- **向后兼容**：现有 Pro 部署的 hil + devcloud-worker 不受影响，所有改动对 fly-pigeon 路径透明。

---

## 10. 后续演进（非本期）

- **多人共用**：把本机 daemon 升级为服务器部署，启用 `BOT_KEY` + 访问规则（黑白名单）做多租户隔离。架构不变。
- **SSE 替代短轮询**：`/api/ilink/login_status` 与 `/api/poll` 可演进为 SSE，降低轮询开销。本期不做。
- **统一 admin console**：在 admin console 里展示 worker 列表、连接状态、ilink 登录二维码、已激活用户，作为运维可视化入口。
