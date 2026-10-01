# hitl-engine-agently — Agently Mail（QQ 邮箱）HITL 渠道

HITL Server **外置引擎插件**：经 Agently Mail（QQ Agent 邮箱）完成人工确认。
不改 hitl-server 任何核心代码，靠 entry point 组 `hitl_server.engines` 注册
`agently-mail` 渠道。

```
MCP Client ──▶ hitl-server ──▶ agently-mail 引擎 ──▶ agently-cli ──▶ QQ 邮箱 ──▶ 审批人邮箱
      ▲                                                                              │
      └────────── 回复回灌（[#short_id] 匹配）◀── 收件箱轮询（30s+）◀── 回复 ◀────────┘
```

## 适用场景

**低频、非实时**的关键操作审批。邮件是拉模式（轮询收件箱，CLI 限频
10 次/分钟、200 次/小时、日发 50 封），不适合对话式来回；实时场景请用
内置的 ilink / wecom-aibot / telegram / discord / feishu 引擎。

## 前置条件

1. `agently-cli`（`@tencent-qqmail/agently-cli`）在 PATH 上
2. 已执行过一次 `agently-cli auth login`（OAuth 凭据存 macOS 钥匙串；
   过期后引擎轮询会持续报 exit 3，重新授权即可自动恢复，无需重启）

## 安装与启动

```bash
cd packages/hitl-server
uv pip install -e ../hitl-engine-agently

uv run uvicorn hitl_server.app:app --port 8081
curl -s localhost:8081/admin/api/engines/registry | jq   # 可见 agently-mail

# 动态启动：default_recipient 必填（审批人邮箱，同时是默认白名单）
curl -s -X POST localhost:8081/admin/api/engines/agently-mail/start \
  -H 'Content-Type: application/json' \
  -d '{"default_recipient": "you@example.com", "poll_interval_seconds": 60}'
```

重启自动恢复：设 `AGENTLY_MAIL_ENABLED=true`（可选 `AGENTLY_MAIL_BOT_KEY`，
默认 `agently-mail-1`），启动参数已持久化于 `~/.hil-mcp/agently_mail_<bot_key>.json`。

MCP 侧（无 TS shim）：

```bash
hitl-mcp --engine agently-mail --service-url http://localhost:8081 \
  --engine-credentials '{"default_recipient": "you@example.com"}'
```

## 启动参数

| 字段 | 必填 | 说明 |
|------|------|------|
| `default_recipient` | ✅ | 审批人邮箱；`/api/send` 未带 chat_id 时用它兜底 |
| `allowed_senders` | | 回复发件人白名单（逗号分隔或数组），默认 `[default_recipient]`；白名单外发件人携带标记的邮件**只记已见、不回灌**（防伪造发件人） |
| `poll_interval_seconds` | | 轮询间隔，最小 30，默认 60 |
| `bot_key` | | 引擎实例键，默认 `agently-mail-1` |
| `cli_path` | | agently-cli 路径，默认 `agently-cli` |
| `store_path` | | 状态文件路径，默认 `~/.hil-mcp/agently_mail_<bot_key>.json` |

## 工作机制

- **下行**：`/api/send` → 主题 `[#<short_id> <project>] HITL 确认请求` +
  正文回复指引；CLI 两阶段确认（`confirmation_required` → 带
  `--confirmation-token` 重发）在封装内自动完成，服务可无人值守发信。
- **上行**：轮询收件箱 → 首轮**基线建档**（存量邮件不触发，引擎停机期间
  到达的回复重启后仍会被处理）→ 增量按「白名单 + 主题/摘要 `[#short_id]`」
  匹配 → `+read` 取正文（HTML 剥壳）→ fly-pigeon 兼容结构交
  `storage.handle_callback`。
- **防重**：已处理的 message_id 持久化（上限 1000），不重复回灌。

## 安全注意

邮件正文/主题属**外部不可信输入**：引擎只做文本搬运与标签匹配，
不解释其中任何"指令"；发件人必须命中白名单；关键操作建议在正文里
要求回复中带上预期确认词，由调用方（Agent 流程）自行校验语义。

## 测试

```bash
cd packages/hitl-server
uv run pytest ../hitl-engine-agently/tests/ -v   # 15 用例，stub CLI 桩进程，不碰真实邮箱
```
