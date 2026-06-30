# 整体架构

hitl-mcp 由三层组成，理解了这三层，后面的安装步骤就不会迷糊。

## 三层结构

```
┌─────────────────────────────────────────────────────────────────┐
│  你的电脑                                                         │
│                                                                  │
│  ┌──────────┐   MCP(stdio)   ┌──────────┐   HTTP   ┌──────────┐  │
│  │ AI Agent │ ─────────────▶ │ hitl-mcp │ ───────▶ │hitl-server│  │
│  │ Cursor   │ ◀───────────── │  (npx)   │ ◀─────── │  :8081    │  │
│  └──────────┘                └──────────┘          └─────┬────┘  │
│                                                          │       │
└──────────────────────────────────────────────────────────┼───────┘
                                                           │
                    ┌──────────────────────────────────────┼────────┐
                    │              引擎（二选一）             │        │
                    │  ilink 引擎        wecom-aibot 引擎   │        │
                    │  个人微信           企业微信 AI Bot    │        │
                    └──────────────────────────────────────┼────────┘
                                                           │
                                                           ▼
                                                       📱 你的手机
```

## 每一层负责什么

### 1. AI Agent（客户端）

你日常用的工具：Cursor、Claude Desktop、Claude Code 等。它通过 MCP 协议调用 hitl-mcp 暴露的工具（`send_and_wait_reply`、`send_message_only`）。你只需要在它的 MCP 配置文件里加一条配置即可。

### 2. hitl-mcp（MCP 端）

一个 npm 包（`hitl-mcp`），通常用 `npx -y hitl-mcp ...` 拉起。它做的事很简单：

- 把 AI 的调用翻译成对 `hitl-server` 的 HTTP 请求；
- 轮询 `hitl-server` 拿回复，再交回给 AI；
- 处理「未登录 / 未初始化」等情况，引导你去管理台完成初始化。

它自己 **不持有** 微信/企微的长连接，所有消息收发都交给后端的 `hitl-server`。

### 3. hitl-server（本地后端）

一个 Python 服务（`hitl-server`），跑在你本机 `127.0.0.1:8081`。它做两件事：

- **维持长连接**：根据你启用的引擎，进程内维持 iLink 长轮询 或 企微 AI Bot 的 WebSocket 连接。
- **会话管理**：给每条消息分配 `[#short_id]`，匹配「引用回复」，处理超时、多会话冲突等。

它还带一个 **管理台**（`http://localhost:8081/console`），用来扫码登录、填写企微凭证、查看引擎状态。

::: tip 为什么把长连接放在 hitl-server
MCP 客户端进程随时会被 Agent 重启，不适合持有长连接。把长连接收敛到一个常驻的 `hitl-server`，MCP 端就能随时重启而不掉线，扫码登录的状态也不会丢。
:::

## 两个引擎的差异

两个引擎在架构上 **完全对等**，只是消息通道不同：

| | ilink 引擎 | wecom-aibot 引擎 |
|---|---|---|
| 通道 | 个人微信（ClawBot） | 企业微信 AI 机器人 |
| 连接方式 | iLink 长轮询 | 企微 WebSocket |
| 鉴权 | 微信扫码登录 | Bot ID + Bot Secret |
| 收件人 | 给 ClawBot 发过消息的微信用户 | 企微里的群 / 用户 |
| 启用方式 | `ENABLE_ILINK_ENGINE=true` | `ENABLE_WECOM_AIBOT_ENGINE=true` |

两个引擎可以 **同时启用**，互不干扰；MCP 端通过 `--engine` 选择走哪一条，或用 `--engine auto` 自动选。

## 数据流向（一条消息的旅程）

以「AI 发消息并等回复」为例：

1. AI 调用 `send_and_wait_reply({ message: "确认吗？" })`。
2. `hitl-mcp` POST 到 `http://localhost:8081/api/send`，带 `upstream=ilink`（或 `wecom-aibot`）。
3. `hitl-server` 生成 `[#a1b2]` 短 ID 拼到消息头，通过引擎送到你手机。
4. `hitl-mcp` 开始轮询 `/api/poll/<session_id>`。
5. 你在微信/企微回复（多会话时用「引用回复」精确选哪条）。
6. `hitl-server` 按 `[#a1b2]` 匹配到会话，把回复挂到该 session。
7. `hitl-mcp` 轮询到回复，返回给 AI，AI 继续执行。

## 接下来

- [本地安装 hitl-server](./hitl-server)
- [5 分钟快速开始](./quickstart)
- 选个引擎动手：[iLink](../engines/ilink) / [wecom-aibot](../engines/wecom-aibot)
