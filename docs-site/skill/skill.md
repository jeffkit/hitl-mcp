---
title: hitl-mcp 一键安装 Skill
outline: [2, 3]
---

# hitl-mcp 一键安装 Skill

本页是一份 **Skill**：让 Agent 读取这一页（或本站点的 [SKILL.md 原始文件](/hitl-mcp/SKILL.md)），它就会按下面的步骤自动帮你把 hitl-mcp 装好、配置好，并验证你的手机真的能收到消息。

## 怎么用

在你的 Agent（Cursor / Claude）对话里说一句：

> 请读取 https://jeffkit.github.io/hitl-mcp/skill/skill ，帮我安装并配置 hitl-mcp，验证能收到消息。

或者让 Agent 直接读原始 Skill 文件：

> 请读取 https://raw.githubusercontent.com/jeffkit/hitl-mcp/main/docs-site/public/SKILL.md ，按里面的步骤帮我安装 hitl-mcp。

Agent 会自动按下面的流程引导你完成。

::: tip 两种读取方式等价
本页是渲染后的可读版，`SKILL.md` 是带 frontmatter 的原始版。Agent 读任一即可，内容一致。
:::

---

## 0. 总体目标

从零开始，一路引导到用户的手机真正收到一条测试消息为止，**中途不要提前结束**。

执行原则：

- **一次只问一个问题**，等用户确认后再进入下一步。
- 涉及写文件、改配置、起服务前，先简要说明要做什么、为什么。
- 遇到失败优先按本文档的「排查」小节处理，不要直接放弃。
- 不要提及 hil / pigeon / fly-pigeon 引擎——本 Skill 只覆盖 iLink 与 wecom-aibot。

## 1. 确认引擎

向用户说明两种引擎的区别，让他选一个：

| 引擎 | 通道 | 适合谁 | 需要准备 |
|------|------|--------|---------|
| **ilink** | 个人微信（ClawBot） | 个人开发者 | 微信扫码登录一次 |
| **wecom-aibot** | 企业微信 AI 机器人 | 团队 / 企业 | 企微后台的 Bot ID + Bot Secret |

> 个人用户推荐 ilink，企业团队推荐 wecom-aibot。两者可同时启用。

## 2. 检查环境

用 Bash 工具检查：`node -v`（需 ≥ 18）、`python3 --version`（需 ≥ 3.10）、`uv --version`。

- 缺 uv：提示 `curl -LsSf https://astral.sh/uv/install.sh | sh`，装好后继续。
- 缺 node：提示用户安装 Node.js 18+。
- macOS 或 Linux 才能用一键服务化；其他系统按手动流程走。

## 3. 安装并启动 hitl-server

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

## 4. 引擎初始化

### ilink

1. 打开 `http://localhost:8081/console`，扫码登录微信。
2. **关键**：让用户在手机微信里搜索 **ClawBot**，加好友并发一条任意消息。等用户确认完成。

### wecom-aibot

1. 凭证已在第 3 步提供，或让用户到 `http://localhost:8081/console` 的「引擎」页面填写 Bot ID / Secret。
2. 让用户在企微里给 bot 发一条消息激活收件人，并借此拿到 chat-id（或让管理员查群 ID）。

## 5. 写入 MCP 客户端配置

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

逻辑：读取现有文件 → 解析 JSON → 合并到 `mcpServers`（同名覆盖，其他保留）→ **展示给用户确认** → 用 Write 写回（2 空格缩进）。

## 6. 引导首次激活并验证

让用户 **完全退出并重新打开** 客户端，然后让用户在对话里说：

> 用 `send_message_only` 给我发一条「测试 hitl-mcp 🎉」

- **ilink**：首次可能触发扫码，引导用户按 AI 给的链接扫码确认后重试。
- **wecom-aibot**：应立即收到。

**等用户确认手机收到消息后，才算成功。** 没收到则排查：

- ilink：是否给 ClawBot 发过消息？token-store 是否绝对路径？客户端是否重启？
- wecom-aibot：Bot ID / Secret 是否正确？Bot 是否启用 AI 对话？chat-id 是否正确？能否访问 `openws.work.weixin.qq.com`？

排查后必要时回到第 5 步重新写入配置。

## 7. 收尾

告知用户：

> 🎉 配置完成！hitl-mcp 已接入。你可以在项目 `CLAUDE.md` 里加规则：「执行写操作前先用 hitl-mcp 向我确认」，让所有会话自动遵守。
