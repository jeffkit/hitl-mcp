# 微信 ClawBot 引擎（iLink）

iLink 引擎通过 **个人微信** 收发消息：你扫码登录一次微信，AI 就能通过微信给你发消息、等你回复。适合个人开发者，无需任何企业账号。

> 通道基于微信 ClawBot。机制是「你先找 Bot，Bot 才认识你」——首次必须用手机微信给 **ClawBot** 发一条消息，Bot 才能向你推送。

## 工作原理

```
AI → hitl-mcp → hitl-server (iLink 引擎) → iLink 长轮询 → 微信 → 📱 你
```

iLink 的长轮询由 `hitl-server` 进程内维持。扫码登录状态存在 `~/.hitl/ilink_store.json`，重启不丢。

## 你需要准备什么

- 一台 macOS 或 Linux 机器跑 `hitl-server`。
- 一部装了微信的手机。
- Node.js 18+（跑 MCP 端）。

## 第 1 步：安装并启动 hitl-server

::: code-group

```bash [macOS Homebrew]
curl -L -o hitl-server.rb \
  https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server.rb
brew install --formula hitl-server.rb
brew services start hitl-server
```

```bash [Linux deb]
sudo dpkg -i hitl-server_*_amd64.deb
sudo systemctl enable --now hitl-server
```

```bash [Linux rpm]
sudo rpm -i hitl-server-*.x86_64.rpm
sudo systemctl enable --now hitl-server
```

:::

Homebrew plist 与 systemd unit **已默认启用 iLink 引擎**（`ILINK_BOT_KEY=ilink-bot-1`），无需额外配置。tar.gz 二进制用户见 [hitl-server 文档](../guide/hitl-server)。

## 第 2 步：扫码登录微信

打开 `http://localhost:8081/console`（默认账号 `admin` / `jarvis2026`），在 iLink 引擎页面点「获取二维码」，用手机微信扫码确认。

或用 API 拉二维码：

```bash
curl "http://localhost:8081/api/ilink/qr?bot_key=ilink-bot-1"
```

返回里有 `qr_url`（浏览器打开扫码）和 `qr_base64`（二维码图片）。查登录状态：

```bash
curl "http://localhost:8081/api/ilink/login_status?bot_key=ilink-bot-1"
# {"status": "success"}  ← 已登录
```

## 第 3 步：给 ClawBot 发一条消息（关键）

打开手机微信，搜索 **ClawBot**，加为好友，给它发一条任意消息（如「你好」。

> 这一步必须做。否则 Bot 没有你的账号信息，无法向你推送消息。这也是「收不到消息」最常见的原因。

## 第 4 步：配置 MCP 客户端

编辑 `~/.cursor/mcp.json`：

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

完整参数说明见 [配置 MCP 客户端](../guide/mcp-config)。

## 第 5 步：重启客户端并验证

完全退出并重新打开 Cursor，在对话里说：

> 用 `send_message_only` 给我发一条「测试 iLink 🎉」

首次若触发扫码，按 AI 给的链接扫码确认后重试。手机收到消息即成功。

## 一键从源码安装（可选）

如果你更想要 **一条命令** 从源码构建 + 服务化 + 扫码 + 打印 Cursor 配置，可以用 `ilink-setup`（会 `git clone` 并用 `uv` 构建 hitl-server，注册成 launchd 服务，仅 macOS）：

```bash
npx -y hitl-mcp ilink-setup --service-url http://localhost:8081 --bot-key ilink-bot-1
```

::: details 全部参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--service-url <url>` | hitl-server 地址 | `http://localhost:8081` |
| `--bot-key <key>` | iLink 引擎路由键 | `ilink-bot-1` |
| `--ilink-base-url <url>` | iLink API 地址 | `https://ilinkai.weixin.qq.com` |
| `--token-store <path>` | 凭证存储路径 | `~/.hitl/ilink_store.json` |
| `--project-name <name>` | 写入 Cursor 配置的默认项目名 | — |
| `--enable-wecom-aibot` | 同时启用企微 AI Bot 引擎 | 关 |
| `--wecom-bot-id <id>` | 企微 Bot ID（配合上一项） | — |
| `--wecom-bot-secret <secret>` | 企微 Bot Secret | — |
| `--wecom-bot-key <key>` | 企微引擎路由键 | `wecom-aibot-1` |
| `--uninstall` | 卸载 launchd 服务（凭证保留） | — |

:::

已经用 Homebrew 装好的用户 **不需要** 再跑这个命令——它主要用于从源码构建的场景。

## 多用户场景

iLink 支持「已激活用户」机制：任何给 ClawBot 发过消息的微信用户都能成为收件人。

- 查看已激活用户：AI 调用 `list_activated_users`，或在管理台查看。
- 默认情况下 AI 会发给最近激活的用户；如需指定，可在 `send_and_wait_reply` 的 `recipient` 里传 `wxid`。

## 卸载

::: code-group

```bash [Homebrew]
brew services stop hitl-server
brew uninstall hitl-server
```

```bash [Linux deb/rpm]
sudo systemctl disable --now hitl-server
sudo dpkg -r hitl-server   # 或 sudo rpm -e hitl-server
```

```bash [ilink-setup 安装的]
npx hitl-mcp ilink-setup --uninstall
```

:::

凭证与日志保留在 `~/.hitl`，如需彻底清理：`rm -rf ~/.hitl ~/.hil-mcp`。

## 常见问题

- **收不到消息** → 八成是没给 ClawBot 发过消息，或没扫码登录。见 [FAQ](../guide/faq#ilink微信)。
- **每次重启都要扫码** → 凭证文件被删或权限问题；正常情况 `~/.hitl/ilink_store.json` 会保留登录态。
- **二维码过期** → 在管理台重新获取。

## 下一步

- [MCP 工具说明](../guide/tools)
- [同时启用企微引擎](../engines/wecom-aibot)
