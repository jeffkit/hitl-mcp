# hitl-mcp — Human-in-the-Loop MCP

让 AI Agent 在执行关键操作前，先通过微信 / 企业微信向你确认。

AI 把「需要人确认」的请求发给 hitl-server，hitl-server 把消息推到你的手机（微信 ClawBot 或企微 AI 机器人），你回复后 AI 拿到结果继续执行。整个链路本地运行，无需公网服务器。

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
