# 5 分钟快速开始

本页带你从零跑通一次「AI 发消息到手机 → 你回复 → AI 收到」的完整链路。

## 总览

整个过程分 4 步：

1. **安装并启动 hitl-server**（本地后端）
2. **启用一个引擎**（微信 ClawBot 或 企微 AI 机器人）
3. **在 MCP 客户端里配置 hitl-mcp**
4. **发一条测试消息验证**

::: tip 不想手动一步步来？
直接让你的 Agent 读取本站的 [Agent Skill](../skill/skill)，它会自动引导你完成全部步骤并验证收消息。
:::

## 前置条件

- **Node.js 18+**：用来跑 `npx hitl-mcp`（MCP 端）。
- **Python 3.10+** 与 **[uv](https://docs.astral.sh/uv/)**：用来跑 `hitl-server`。
  - 安装 uv：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- **一个 MCP 客户端**：Cursor / Claude Desktop / Claude Code 任选其一。
- **macOS 或 Linux**：`hitl-server` 的「一键服务化」目前仅 macOS（launchd），Linux 需自行用 systemd 管理。

## 第 1 步：拿到代码并安装 hitl-server

```bash
git clone https://github.com/jeffkit/hitl-mcp.git
cd hitl-mcp/packages/hitl-server

# 安装依赖（建一个 .venv）
uv sync
```

启动服务：

```bash
uv run python -m hitl_server.app
```

默认监听 `http://127.0.0.1:8081`，管理台在 `http://localhost:8081/console`。

::: details 想让它常驻后台（macOS）
iLink 引擎提供了「一键服务化」命令，会把 hitl-server 注册成 launchd 服务（开机自启 + 崩溃自动重启）：

```bash
npx -y hitl-mcp ilink-setup --service-url http://localhost:8081
```

详见 [iLink 引擎文档 → 一键安装](../engines/ilink#一键安装推荐)。
:::

## 第 2 步：启用一个引擎

二选一（也可以两个都开）。最快的方式是设环境变量后重启 `hitl-server`。

### 选项 A：微信 ClawBot（iLink）

```bash
ENABLE_ILINK_ENGINE=true \
ILINK_BOT_KEY=ilink-bot-1 \
uv run python -m hitl_server.app
```

然后打开 `http://localhost:8081/console`，在 iLink 引擎页面 **扫码登录** 微信。

详细步骤见 [微信 ClawBot 引擎](../engines/ilink)。

### 选项 B：企微 AI 机器人（wecom-aibot）

```bash
ENABLE_WECOM_AIBOT_ENGINE=true \
WECOM_AIBOT_BOT_KEY=wecom-aibot-1 \
WECOM_AIBOT_BOT_ID=你的BotID \
WECOM_AIBOT_BOT_SECRET=你的BotSecret \
uv run python -m hitl_server.app
```

或在管理台 `http://localhost:8081/console` 里填写 Bot ID / Bot Secret。

详细步骤见 [企微 AI 机器人引擎](../engines/wecom-aibot)。

## 第 3 步：在 MCP 客户端配置 hitl-mcp

以 Cursor 为例，编辑 `~/.cursor/mcp.json`：

::: code-group

```json [iLink 引擎]
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

```json [企微 wecom-aibot 引擎]
{
  "mcpServers": {
    "hitl-mcp-wecom": {
      "command": "npx",
      "args": [
        "-y", "hitl-mcp",
        "--engine", "wecom-aibot",
        "--service-url", "http://localhost:8081",
        "--bot-key", "wecom-aibot-1",
        "--chat-id", "你的企微群或用户ID"
      ]
    }
  }
}
```

:::

完整参数说明见 [配置 MCP 客户端](./mcp-config)。

## 第 4 步：重启客户端并验证

1. **完全退出并重新打开** Cursor / Claude Desktop，让新配置生效。
2. 在对话里对 AI 说：

   > 请用 `send_message_only` 给我发一条消息：「测试 hitl-mcp 🎉」

3. 看你的微信 / 企微是否收到。
   - **iLink**：首次会触发扫码登录，按 AI 给的链接扫码确认后重试即可。
   - **wecom-aibot**：配置正确应立即收到。

4. 再试「等回复」：

   > 请用 `send_and_wait_reply` 发「请回复 OK」并等我的回复。

   你在手机上回复 `OK`，AI 应该能收到并继续。

## 收到消息 = 成功

🎉 如果你的手机收到了消息，整个链路就通了。接下来你可以：

- 在项目的 `CLAUDE.md` 里写一条规则：「执行写操作前先用 hitl-mcp 向我确认」。
- 调整 `--timeout`（默认 1200 秒 / 20 分钟）。
- 同时启用两个引擎，用 `--engine auto` 自动选用。

## 下一步

- [MCP 工具说明](./tools) — `send_and_wait_reply` / `send_message_only` 的参数与返回。
- [常见问题](./faq) — 收不到消息、502、npx 慢怎么办。
- 深入某个引擎：[iLink](../engines/ilink) / [wecom-aibot](../engines/wecom-aibot)
