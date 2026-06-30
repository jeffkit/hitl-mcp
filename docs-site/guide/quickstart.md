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
- **一个 MCP 客户端**：Cursor / Claude Desktop / Claude Code 任选其一。
- **macOS 或 Linux**：hitl-server 提供Homebrew / deb / rpm 预构建产物。

> `hitl-server` 是自包含二进制，**不需要** 预装 Python 或 uv。仅在你想从源码构建时才需要它们。

## 第 1 步：安装并启动 hitl-server

hitl-server 有跨平台预构建产物，直接装即可（自包含二进制，无需 Python）。

::: code-group

```bash [macOS Homebrew]
curl -L -o hitl-server.rb \
  https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server.rb
brew install --formula hitl-server.rb
brew services start hitl-server
```

```bash [Linux deb]
# 从 https://github.com/jeffkit/hitl-mcp/releases/latest 下载 deb 后：
sudo dpkg -i hitl-server_*_amd64.deb
sudo systemctl enable --now hitl-server
```

```bash [Linux rpm]
# 从 https://github.com/jeffkit/hitl-mcp/releases/latest 下载 rpm 后：
sudo rpm -i hitl-server-*.x86_64.rpm
sudo systemctl enable --now hitl-server
```

:::

服务起来后监听 `http://127.0.0.1:8081`，管理台在 `http://localhost:8081/console`。iLink 引擎默认已启用。

::: details 没有包管理器？用 tar.gz 二进制
```bash
# macOS Apple Silicon
curl -L https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server-darwin-arm64.tar.gz | tar xz
ENABLE_ILINK_ENGINE=true ./hitl-server/hitl-server
# Linux x86_64
curl -L https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server-linux-x86_64.tar.gz | tar xz
ENABLE_ILINK_ENGINE=true ./hitl-server/hitl-server
```
更多见 [本地安装 hitl-server](./hitl-server)。
:::

## 第 2 步：启用一个引擎

二选一（也可以两个都开）。brew/systemd 安装已默认启用 iLink 引擎，所以 iLink 只需扫码登录；wecom-aibot 在管理台填凭证即可。

### 选项 A：微信 ClawBot（iLink）

iLink 引擎默认已启用（`ILINK_BOT_KEY=ilink-bot-1`）。打开 `http://localhost:8081/console`，在 iLink 引擎页面 **扫码登录** 微信即可。

详细步骤见 [微信 ClawBot 引擎](../engines/ilink)。

### 选项 B：企微 AI 机器人（wecom-aibot）

打开 `http://localhost:8081/console`，在「引擎」页面填写 Bot ID / Bot Secret 并启动。凭证落盘后重启自动恢复。

或编辑服务配置用环境变量启用（macOS 改 brew plist / Linux 改 `/etc/systemd/system/hitl-server.service` 后重启服务）：

```
ENABLE_WECOM_AIBOT_ENGINE=true
WECOM_AIBOT_BOT_KEY=wecom-aibot-1
WECOM_AIBOT_BOT_ID=你的BotID
WECOM_AIBOT_BOT_SECRET=你的BotSecret
```

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
