---
name: hitl-mcp-setup
description: >-
  帮用户把 hitl-mcp（Human-in-the-Loop MCP）从零安装到验证收消息。包括本地安装 hitl-server、
  启用 iLink（微信 ClawBot）或 wecom-aibot（企微 AI 机器人）引擎、写入 MCP 客户端配置、
  引导首次激活，并确认手机真正收到测试消息后才结束。当用户说"帮我配置 hitl-mcp"、
  "安装 Human-in-the-Loop MCP"、"我想让 AI 发微信/企微给我"、"在执行危险操作前先问我"时触发。
  不要提及 hil / pigeon / fly-pigeon 引擎——本 Skill 只覆盖 iLink 与 wecom-aibot。
version: 1.0.0
---

# hitl-mcp 配置向导

hitl-mcp 让 AI Agent 在执行关键步骤前，通过微信 / 企业微信向你发消息并等待你回复，实现"人在回路"的审批与确认。

本 Skill 的目标：**从零开始，一路引导到用户的手机真正收到一条测试消息为止，中途不要提前结束。**

执行原则：

- **一次只问一个问题**，等用户确认后再进入下一步。
- 涉及写文件、改配置、起服务前，先简要说明要做什么、为什么。
- 遇到失败优先按本文档的"排查"小节处理，不要直接放弃。
- 不要提及 hil / pigeon / fly-pigeon 引擎——本 Skill 只覆盖 iLink 与 wecom-aibot。

---

## 第 1 步：确认引擎

向用户说明两种引擎的区别，让他选一个：

| 引擎 | 通道 | 适合谁 | 需要准备 |
|------|------|--------|---------|
| **ilink** | 个人微信（ClawBot） | 个人开发者 | 微信扫码登录一次 |
| **wecom-aibot** | 企业微信 AI 机器人 | 团队 / 企业 | 企微后台的 Bot ID + Bot Secret |

个人用户推荐 ilink，企业团队推荐 wecom-aibot。两者可同时启用。

---

## 第 2 步：检查环境

用 Bash 工具检查：`node -v`（需 ≥ 18）、`python3 --version`（需 ≥ 3.10）、`uv --version`。

- 缺 uv：提示 `curl -LsSf https://astral.sh/uv/install.sh | sh`，装好后继续。
- 缺 node：提示用户安装 Node.js 18+。
- macOS 或 Linux 才能用一键服务化；其他系统按手动流程走。

---

## 第 3 步：安装并启动 hitl-server

### 3.1 拿到代码

```bash
git clone https://github.com/jeffkit/hitl-mcp.git
cd hitl-mcp/packages/hitl-server
uv sync
```

### 3.2 macOS：推荐用一键服务化

在 **仓库根目录** 执行（根据用户选的引擎调整参数）：

**ilink：**

```bash
npx -y hitl-mcp ilink-setup --service-url http://localhost:8081 --bot-key ilink-bot-1
```

该命令会建 venv、注册 launchd 服务、拉二维码引导扫码登录、打印 Cursor 配置。

**wecom-aibot：**

```bash
npx -y hitl-mcp ilink-setup --service-url http://localhost:8081 \
  --enable-wecom-aibot \
  --wecom-bot-id <BotID> --wecom-bot-secret <BotSecret> \
  --wecom-bot-key wecom-aibot-1
```

（向用户要 Bot ID / Bot Secret，一次只问一个。）

> 注：该命令也会启用 iLink 引擎，但未扫码时它不影响企微引擎工作。

### 3.3 Linux / 想手动掌控：前台启动

```bash
cd packages/hitl-server
```

ilink：

```bash
ENABLE_ILINK_ENGINE=true ILINK_BOT_KEY=ilink-bot-1 \
ILINK_TOKEN_STORE_PATH=~/.hitl/ilink_store.json \
uv run python -m hitl_server.app
```

wecom-aibot：

```bash
ENABLE_WECOM_AIBOT_ENGINE=true WECOM_AIBOT_BOT_KEY=wecom-aibot-1 \
WECOM_AIBOT_BOT_ID=<BotID> WECOM_AIBOT_BOT_SECRET=<BotSecret> \
uv run python -m hitl_server.app
```

验证服务可达：`curl http://localhost:8081/api/ilink/login_status?bot_key=ilink-bot-1` 应返回 JSON。

---

## 第 4 步：引擎初始化

### ilink

1. 打开 `http://localhost:8081/console`，扫码登录微信。
2. **关键**：让用户在手机微信里搜索 **ClawBot**，加好友并发一条任意消息。等用户确认完成。

### wecom-aibot

1. 凭证已在第 3 步提供，或让用户到 `http://localhost:8081/console` 的"引擎"页面填写 Bot ID / Secret。
2. 让用户在企微里给 bot 发一条消息激活收件人，并借此拿到 chat-id（或让管理员查群 ID）。

---

## 第 5 步：写入 MCP 客户端配置

### 5.1 探测配置文件（用 Bash 检查存在性）

- Cursor: `~/.cursor/mcp.json`
- Claude Desktop (mac): `~/Library/Application Support/Claude/claude_desktop_config.json`
- Claude Desktop (win): `%APPDATA%\Claude\claude_desktop_config.json`
- Claude Code: `~/.claude/mcp.json`

找到多个则列出让用户选；找不到则问用户配哪个客户端，并创建对应文件（先建目录）。

### 5.2 写入条目

**ilink：**

```json
"hitl-mcp-ilink": {
  "command": "npx",
  "args": ["-y", "hitl-mcp", "--engine", "ilink",
           "--service-url", "http://localhost:8081",
           "--bot-key", "ilink-bot-1"],
  "env": { "http_proxy": "", "https_proxy": "", "all_proxy": "" }
}
```

**wecom-aibot：**

```json
"hitl-mcp-wecom": {
  "command": "npx",
  "args": ["-y", "hitl-mcp", "--engine", "wecom-aibot",
           "--service-url", "http://localhost:8081",
           "--bot-key", "wecom-aibot-1",
           "--chat-id", "<chat-id>"],
  "env": { "http_proxy": "", "https_proxy": "", "all_proxy": "" }
}
```

写入逻辑：

1. 读取现有配置文件（若存在）。
2. 解析 JSON，找到 `mcpServers`（不存在则初始化为空对象）。
3. 将对应条目合并写入（同名覆盖，其他条目保持不变）。
4. **写入前向用户展示最终配置**，确认无误后用 Write 写回（2 空格缩进）。

---

## 第 6 步：引导首次激活并验证

让用户 **完全退出并重新打开** 客户端，然后让用户在对话里说：

> 用 `send_message_only` 给我发一条"测试 hitl-mcp 🎉"

- **ilink**：首次可能触发扫码，引导用户按 AI 给的链接扫码确认后重试。
- **wecom-aibot**：应立即收到。

**等用户确认手机收到消息后，才算成功。** 没收到则排查：

- ilink：是否给 ClawBot 发过消息？token-store 是否绝对路径？客户端是否重启？
- wecom-aibot：Bot ID / Secret 是否正确？Bot 是否启用 AI 对话？chat-id 是否正确？能否访问 `openws.work.weixin.qq.com`？

排查后必要时回到第 5 步重新写入配置。

---

## 第 7 步：收尾

用户确认收到消息后，告知：

> 🎉 配置完成！hitl-mcp 已成功接入你的微信 / 企业微信。
>
> 接下来你可以：
> - 在对话中告诉 AI「在执行写操作前先用 hitl-mcp 向我确认」
> - 或在项目的 `CLAUDE.md` 里写入审批规则，让所有会话都自动遵守
>
> 如需更多用法，可以问我「hitl-mcp 怎么用」。
