# hitl-mcp — Human-in-the-Loop MCP

让 AI Agent 在执行关键操作前，先通过微信 / 企业微信向你确认。

AI 把「需要人确认」的请求发给 hitl-server，hitl-server 把消息推到你的手机（微信 ClawBot 或企微 AI 机器人），你回复后 AI 拿到结果继续执行。

两种部署形态：
- **本地单用户**：hitl-server 跑在自己机器上，整个链路无需公网服务器（默认）。
- **服务器共享部署**：hitl-server 跑在一台服务器上，全公司共用一个企微 AI Bot，每人用自己的 `chat_id` + API Key 收发消息。详见下文[服务器共享部署](#服务器共享部署多人共用一个企微-bot)。

```
┌──────────┐  MCP(stdio)  ┌──────────┐  HTTP   ┌────────────┐  长连接   ┌──────────┐
│ AI Agent │ ───────────▶ │ hitl-mcp │ ──────▶ │ hitl-server│ ────────▶ │ 你的手机 │
│ Cursor   │ ◀─────────── │  (npx)   │ ◀────── │  :8081     │ ◀──────── │ 微信/企微 │
└──────────┘              └──────────┘         └────────────┘           └──────────┘
```

## 项目结构

```
hitl-mcp/
├── packages/
│   ├── hitl-server/     # 本地后端（FastAPI + 内置引擎 + React 管理台）
│   ├── mcp-server-py/   # MCP 客户端（Python 版，uvx hil-mcp）
│   └── mcp-server-ts/   # MCP 客户端（TypeScript 版，npx hitl-mcp）
├── docs/                # 设计文档
├── docs-site/           # 用户文档站点源码
└── scripts/             # 辅助脚本
```

## 两个引擎

两个引擎架构对等，可同时启用，互不干扰。MCP 端用 `--engine` 指定，或 `--engine auto` 按管理台状态自动选用。

| | ilink 引擎 | wecom-aibot 引擎 |
|---|---|---|
| 通道 | 个人微信（ClawBot） | 企业微信 AI 机器人 |
| 连接方式 | iLink 长轮询 | 企微 WebSocket |
| 鉴权 | 微信扫码登录 | Bot ID + Bot Secret |
| 收件人 | 给 ClawBot 发过消息的微信用户 | 企微里的群 / 用户 |
| 启用 | `ENABLE_ILINK_ENGINE=true` | 管理台填凭证或 `ENABLE_WECOM_AIBOT_ENGINE=true` |

## 快速开始

### 1. 安装并启动 hitl-server

::: tip 详见 [本地安装 hitl-server](./docs-site/guide/hitl-server.md)
:::

macOS（Homebrew，已默认启用 iLink 引擎）：

```bash
curl -L -o hitl-server.rb \
  https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server.rb
brew install --formula hitl-server.rb
brew services start hitl-server
```

Linux（deb / rpm）见 [Releases](https://github.com/jeffkit/hitl-mcp/releases/latest)。无包管理器时用 tar.gz 二进制：

```bash
curl -L https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server-darwin-arm64.tar.gz | tar xz
ENABLE_ILINK_ENGINE=true ./hitl-server/hitl-server
```

服务起来后监听 `http://127.0.0.1:8081`，管理台在 `http://localhost:8081/console`。

### 2. 启用引擎

打开管理台 `http://localhost:8081/console`：

- **iLink**：在引擎页面扫码登录微信，然后给 ClawBot 发一条消息激活收件人。
- **wecom-aibot**：填写 Bot ID / Bot Secret 并启动，然后在企微给 bot 发一条消息激活收件人。

凭证落盘后重启自动恢复。详见 [iLink 引擎](./docs-site/engines/ilink.md) / [企微 AI 机器人引擎](./docs-site/engines/wecom-aibot.md)。

### 3. 配置 MCP 客户端

以 Cursor 为例，编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "hitl-mcp-ilink": {
      "command": "npx",
      "args": [
        "-y", "hitl-mcp",
        "--engine", "ilink",
        "--service-url", "http://localhost:8081",
        "--bot-key", "ilink-bot-1"
      ]
    }
  }
}
```

企微 wecom-aibot 把 `--engine` 换成 `wecom-aibot`、`--bot-key` 换成 `wecom-aibot-1`，并按需加 `--chat-id`。完整参数见 [配置 MCP 客户端](./docs-site/guide/mcp-config.md)。

### 4. 重启客户端并验证

完全退出并重新打开 Cursor，对 AI 说：

> 请用 `send_message_only` 给我发一条消息：「测试 hitl-mcp 🎉」

手机收到即链路打通。再试「等回复」：

> 请用 `send_and_wait_reply` 发「请回复 OK」并等我的回复。

## 服务器共享部署（多人共用一个企微 bot）

把 hitl-server 部署到一台服务器，全员共用一个企微 AI Bot。运维在服务端持有 bot 凭证，普通用户只需在 MCP 侧配置自己的 `chat_id` + API Key。

### 服务端配置

关键环境变量（`.env` 或 systemd unit）：

| 变量 | 说明 |
|---|---|
| `HITL_SHARED_MODE=true` | 开启共享模式：`/api/*` 强制 Bearer 鉴权；wecom-aibot 不再回退全局最近活跃收件人（`chat_id` 必填，避免把 A 的确认请求发到 B） |
| `HITL_API_KEY=<key>` | 单一 API Key，持有者可对任意 `chat_id` 发消息（可信单租户） |
| `HITL_API_TOKENS=<json>` | 多租户白名单：`{"tokenTom":["tom_userid"],"tokenGroupA":["grp_chatid"]}`，把 token 绑定到允许的 `chat_id`，防越权。与 `HITL_API_KEY` 二选一或并存，tokens 优先 |
| `HIL_USE_DATABASE=true` | 会话持久化，重启不丢（多用户强烈建议） |
| `HIL_DATABASE_URL` | `mysql+aiomysql://user:pwd@host:3306/db?charset=utf8mb4` 或留空走 SQLite（`HIL_DATABASE_PATH`） |
| `HITL_HOST=127.0.0.1` | 监听地址；服务器上建议保持 `127.0.0.1`，由 nginx 反代到公网/HTTPS |
| `ADMIN_PASSWORD` / `ADMIN_TOKEN_SECRET` | 服务器部署务必改掉默认值 |

`packaging/hitl-server.service` 内有完整的共享部署环境变量示例，可直接参照。用户首次在企微给 bot 发消息时，bot 会**自动回告其 `chat_id`**，方便自助配置。

### 安全网关

`/api/*` 由应用层 Bearer Token 鉴权；管理面（`/console`、`/admin/*`）默认无应用层登录，服务器暴露公网时建议在 nginx 层加 basic auth 保护 `/console` 与 `/admin/`，并上 HTTPS。

### MCP 客户端配置（共享模式）

用户在 Cursor 的 `mcp.json` 里带上 `--shared` / `--api-key` / `--chat-id`：

```json
{
  "mcpServers": {
    "hitl-mcp-shared": {
      "command": "npx",
      "args": [
        "-y", "hitl-mcp",
        "--engine", "wecom-aibot",
        "--service-url", "https://hitl.example.com",
        "--shared",
        "--api-key", "<你的 API Key>",
        "--chat-id", "<你的 chat_id>"
      ]
    }
  }
}
```

`--chat-id` 留空时 MCP 端直接报错引导，不会发请求。401/403 会给出中文提示。

> 注意：企微同凭证只允许一条 WebSocket 长连接，hitl-server **不能多副本水平扩展**（多连接互踢）。要扩容需单实例 + 反代，或多 bot_id 分片。

## MCP 工具

| 工具 | 作用 |
|------|------|
| `send_and_wait_reply` | 发消息并等待用户回复（带 `[#id]` 标识，支持引用回复精确匹配） |
| `send_message_only` | 仅发送通知，不等待回复 |

未初始化时返回 `not_initialized`（含管理台链接 `init_url`），引导用户打开管理台完成初始化后重试。详见 [工具说明](./docs-site/guide/tools.md)。

## 从源码构建（可选）

hitl-server 是自包含二进制，通常无需从源码构建。需要时：

```bash
git clone https://github.com/jeffkit/hitl-mcp.git
cd hitl-mcp/packages/hitl-server
uv sync
uv run python -m hitl_server.app
```

或一键构建二进制：`bash packaging/build.sh`（依赖 `uv` / `pnpm` / Python ≥ 3.10）。

## 文档

完整文档见 docs-site：

- [整体架构](./docs-site/guide/architecture.md)
- [5 分钟快速开始](./docs-site/guide/quickstart.md)
- [本地安装 hitl-server](./docs-site/guide/hitl-server.md)
- [配置 MCP 客户端](./docs-site/guide/mcp-config.md)
- [使用方法：人在回路](./docs-site/guide/usage.md)
- [常见问题](./docs-site/guide/faq.md)
- 引擎：[iLink](./docs-site/engines/ilink.md) / [wecom-aibot](./docs-site/engines/wecom-aibot.md)

## License

MIT
