# 配置 MCP 客户端

`hitl-mcp` 是一个标准的 MCP 服务，所有支持 MCP 的客户端都能接入。本文以 Cursor 为例，并给出 Claude Desktop / Claude Code 的配置位置。

## 配置文件在哪

| 客户端 | 配置文件路径 |
|--------|------------|
| Cursor | `~/.cursor/mcp.json` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude/mcp.json` |

文件不存在就新建（先建好父目录）。

## 配置模板

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

```json [wecom-aibot 引擎]
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

```json [auto 自动选用]
{
  "mcpServers": {
    "hitl-mcp": {
      "command": "npx",
      "args": [
        "-y", "hitl-mcp",
        "--service-url", "http://localhost:8081"
      ]
    }
  }
}
```

:::

> `auto` 模式会在启动时查询管理台，按 `ilink → wecom-aibot` 优先级自动选一个已配置好的引擎。如果你只启用了一个引擎，用 `auto` 最省心。

## 命令行参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--engine <type>` | 引擎：`auto` / `ilink` / `wecom-aibot` | `auto` |
| `--service-url <url>` | hitl-server 地址 | `http://localhost:8081` |
| `--bot-key <key>` | 路由键，对应后端 `ILINK_BOT_KEY` / `WECOM_AIBOT_BOT_KEY` | 后端按引擎自动路由 |
| `--chat-id <id>` | 默认收件人（wecom-aibot 常用；ilink 自动推断） | — |
| `--project-name <name>` | 消息头显示的项目名 | — |
| `--timeout <seconds>` | 等待回复超时秒数 | `1200`（20 分钟） |
| `--bot-id <id>` | 企微 Bot ID（仅 wecom-aibot，可省略，建议在管理台填） | — |
| `--bot-secret <secret>` | 企微 Bot Secret（同上） | — |
| `--token-store <path>` | iLink token 存储路径（仅 ilink） | `./data/ilink_store.json` |
| `--base-url <url>` | iLink API 地址（仅 ilink） | `https://ilinkai.weixin.qq.com` |

::: warning iLink 的 token-store 用绝对路径
iLink 引擎的 `--token-store` 默认是相对路径 `./data/ilink_store.json`，MCP 客户端的工作目录可能变化，建议改成绝对路径，例如 `~/.hil-mcp/ilink_store.json`，否则每次重启可能都要重新扫码。

不过更推荐的做法是直接用 Homebrew / deb / rpm 安装 hitl-server（服务配置已用 `~/.hitl/` 下的绝对路径并服务化），见 [iLink 引擎 → 安装](../engines/ilink#第-1-步-安装并启动-hitl-server)。
:::

## 禁用代理（重要）

如果你机器上设了 HTTP 代理，`npx` 访问 `localhost` 会走代理导致 502。在配置里把代理清空：

```json
{
  "mcpServers": {
    "hitl-mcp-ilink": {
      "command": "npx",
      "args": ["-y", "hitl-mcp", "--engine", "ilink", "--service-url", "http://localhost:8081"],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

## npx 每次都下载很慢？

全局安装一次，之后配置里直接用 `hitl-mcp` 命令：

```bash
pnpm add -g hitl-mcp
# 或
npm install -g hitl-mcp
```

```json
{
  "mcpServers": {
    "hitl-mcp-ilink": {
      "command": "hitl-mcp",
      "args": ["--engine", "ilink", "--service-url", "http://localhost:8081"]
    }
  }
}
```

## 同时接入两个引擎

在 `mcpServers` 下加两条即可，AI 会同时看到两组工具：

```json
{
  "mcpServers": {
    "hitl-mcp-ilink": {
      "command": "npx",
      "args": ["-y", "hitl-mcp", "--engine", "ilink", "--service-url", "http://localhost:8081"]
    },
    "hitl-mcp-wecom": {
      "command": "npx",
      "args": ["-y", "hitl-mcp", "--engine", "wecom-aibot", "--service-url", "http://localhost:8081", "--chat-id", "xxx"]
    }
  }
}
```

## 让 Agent 自动帮你配置

如果你不想手动改 JSON，让你的 Agent 读取本站的 [Agent Skill](../skill/skill)，它会自动探测配置文件、写入、并引导你完成验证。

## 下一步

- [MCP 工具说明](./tools)
- [常见问题](./faq)
