# 企微 AI 机器人引擎（wecom-aibot）

wecom-aibot 引擎通过 **企业微信智能机器人（AI Bot）** 收发消息：AI 可以向企微群聊或私聊发消息并等回复。适合团队 / 企业用户。

> 协议参考：[企业微信 AI Bot 接入文档](https://developer.work.weixin.qq.com/document/path/101463)

## 工作原理

```
AI → hitl-mcp → hitl-server (wecom-aibot 引擎) → 企微 WebSocket → 企业微信 → 📱 你
```

企微 AI Bot 的 WebSocket 长连接由 `hitl-server` 进程内维持，断线自动重连。Bot 凭证（ID / Secret）落盘在 `~/.hitl/wecom_aibot_store.json`，重启后自动注册，无需在管理台重填。

## 你需要准备什么

- 一台 macOS 或 Linux 机器跑 `hitl-server`。
- **企业微信管理员** 权限（或请管理员帮你拿到 Bot 凭证）。
- Node.js 18+（跑 MCP 端）。
- Python 3.10+ 与 [uv](https://docs.astral.sh/uv/)。
- 出网到 `openws.work.weixin.qq.com`。

## 第 1 步：获取企微 Bot 凭证

让企微管理员在 **企业微信管理后台** 操作：

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/)。
2. 进入 **应用管理 → AI Bot**（智能机器人）。
3. 创建或选择一个 AI Bot，进入「基本信息」页面。
4. 记下：
   - **Bot ID**（`--bot-id`）
   - **Bot Secret**（`--bot-secret`）
5. 确认该 Bot 已启用 **「AI 对话」** 权限。

## 第 2 步：启动 hitl-server 并启用引擎

```bash
cd packages/hitl-server

ENABLE_WECOM_AIBOT_ENGINE=true \
WECOM_AIBOT_BOT_KEY=wecom-aibot-1 \
WECOM_AIBOT_BOT_ID=你的BotID \
WECOM_AIBOT_BOT_SECRET=你的BotSecret \
uv run python -m hitl_server.app
```

启动后日志里应看到引擎连接成功。也可以在管理台 `http://localhost:8081/console` 的「引擎」页面查看状态。

::: tip 也可以在管理台填凭证
如果你不想把 Secret 写在命令行，可以只设 `ENABLE_WECOM_AIBOT_ENGINE=true` 启用引擎，然后到管理台「引擎」页面填写 Bot ID / Bot Secret。填写后会自动落盘，之后重启无需重填。
:::

### 想要常驻后台（macOS）

借用 iLink 的「一键服务化」命令把 hitl-server 注册成 launchd 服务，并顺带启用企微引擎：

```bash
cd hitl-mcp  # 仓库根目录

npx -y hitl-mcp ilink-setup \
  --service-url http://localhost:8081 \
  --enable-wecom-aibot \
  --wecom-bot-id 你的BotID \
  --wecom-bot-secret 你的BotSecret \
  --wecom-bot-key wecom-aibot-1
```

> 即使你不用 iLink，这个命令也能用来服务化 hitl-server；不想启用 iLink 引擎的话，加 `--bot-key` 不影响——它只是 iLink 的路由键，未扫码登录时 iLink 引擎会安静地待命，不影响企微引擎工作。

Linux 用户请用 systemd 自行管理，见 [本地安装 hitl-server](../guide/hitl-server#后台常驻-linux)。

## 第 3 步：拿到 chat-id（收件人）

`wecom-aibot` 引擎需要知道消息发给谁：

- **群聊**：让管理员在企微后台查群 ID；或把 bot 拉进群，在群里 @bot 发一条消息，然后到管理台日志里看 `chatid`。
- **私聊**：用你的企微用户 ID。

::: tip 强烈建议填 `--chat-id`
不填的话，每次调用 `send_and_wait_reply` 都要手动指定 `recipient`，AI 容易遗漏。先填一个默认收件人最省心。
:::

一个快捷办法：在企微里给 bot 发一条消息，bot 会自动回复你的 chat_id（若已配置自动回复）。

## 第 4 步：配置 MCP 客户端

编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "hitl-mcp-wecom": {
      "command": "npx",
      "args": [
        "-y", "hitl-mcp",
        "--engine", "wecom-aibot",
        "--service-url", "http://localhost:8081",
        "--bot-key", "wecom-aibot-1",
        "--chat-id", "你的chat-id"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

> `--bot-key` 要和后端 `WECOM_AIBOT_BOT_KEY` 一致（默认都是 `wecom-aibot-1`）。`--bot-id` / `--bot-secret` 在 MCP 端是可选的（兜底自动注册用），推荐在管理台填，不必在 MCP 配置里携带 Secret。

## 第 5 步：重启客户端并验证

1. 完全退出并重新打开 Cursor。
2. 在对话里说：

   > 用 `send_message_only` 给我发一条「测试企微引擎 🎉」

3. 你的企业微信应立即收到。再试：

   > 用 `send_and_wait_reply` 发「请回复 OK」并等我的回复

   在企微里回复 `OK`，AI 收到后继续。

## 未初始化的处理

如果返回 `not_initialized`，通常是：

- Bot 凭证没填或填错 → 到管理台核对。
- 还没在企微里给 bot 发过消息 → 给 bot 发一条消息激活收件人。

返回里带 `init_url`，打开它即管理台。

## 常见问题

- **收不到消息** → 见 [FAQ - wecom-aibot](../guide/faq#wecom-aibot企微)。
- **多会话回复混乱** → 用企微的「引用回复」精确选要回的那条。
- **凭证不想写在命令行** → 只设 `ENABLE_WECOM_AIBOT_ENGINE=true`，到管理台填写。

## 下一步

- [MCP 工具说明](../guide/tools)
- [同时启用 iLink 引擎](../engines/ilink)
