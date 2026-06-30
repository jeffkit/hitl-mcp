# 本地安装 hitl-server

`hitl-server` 是 hitl-mcp 的本地后端，负责维持微信/企微的长连接、管理会话与回复匹配。它跑在你本机 `127.0.0.1:8081`，**不需要公网 IP**。

每个版本都提供 **跨平台的预构建产物**，直接装就行，不用从源码编译。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Node.js | ≥ 18 | 跑 MCP 端 `npx hitl-mcp` |
| OS | macOS / Linux | 见下表选对应产物 |

`hitl-server` 本身是 **自包含二进制**（PyInstaller 打包，内嵌管理台），**不依赖** Python / uv。你只需要装它，不用准备 Python 环境。

## 选哪种产物

| 平台 | 推荐方式 | 产物 |
|------|---------|------|
| macOS（Apple Silicon） | Homebrew | `hitl-server.rb` |
| Linux（x86_64） | deb / rpm | `hitl-server_*_amd64.deb` / `hitl-server-*.x86_64.rpm` |
| 任意平台（无包管理器） | tar.gz 二进制 | `hitl-server-<os>-<arch>.tar.gz` |

所有产物都在 [GitHub Releases](https://github.com/jeffkit/hitl-mcp/releases/latest) 页面。

## macOS：Homebrew（推荐）

```bash
# 1. 下载最新 Release 里的 Homebrew formula
curl -L -o hitl-server.rb \
  https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server.rb

# 2. 安装
brew install --formula hitl-server.rb

# 3. 启动（开机自启 + 崩溃自动重启，已默认启用 iLink 引擎）
brew services start hitl-server
```

启动后：

- 服务地址 `http://127.0.0.1:8081`，管理台 `http://localhost:8081/console`
- 数据/凭证目录 `~/.hitl`
- 日志 `~/.hitl/logs/hitl-server.{out,err}.log`

::: details 不想用 Homebrew？用 tar.gz 二进制
```bash
curl -L https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server-darwin-arm64.tar.gz | tar xz
# 默认监听 8081；如需启用引擎，加环境变量
ENABLE_ILINK_ENGINE=true ILINK_BOT_KEY=ilink-bot-1 ./hitl-server/hitl-server
```
想让它常驻？自行配 launchd（macOS）或 systemd（Linux）即可，服务配置示例见 [hitl-server 文档](./hitl-server)。
:::

## Linux：deb / rpm（推荐）

从 [Releases 页](https://github.com/jeffkit/hitl-mcp/releases/latest) 下载最新版对应包：

::: code-group

```bash [deb (Debian/Ubuntu)]
sudo dpkg -i hitl-server_*_amd64.deb
sudo systemctl enable --now hitl-server
```

```bash [rpm (RHEL/Fedora/CentOS)]
sudo rpm -i hitl-server-*.x86_64.rpm
sudo systemctl enable --now hitl-server
```

:::

systemd unit 已 **默认启用 iLink 引擎**（`ENABLE_ILINK_ENGINE=true`、`ILINK_BOT_KEY=ilink-bot-1`）。企微 AI Bot 默认不启用，可在管理台运行时配置（凭证落盘后重启自动恢复），或编辑 `/etc/systemd/system/hitl-server.service` 取消注释 `WECOM_AIBOT_*` 三行后 `sudo systemctl daemon-reload && sudo systemctl restart hitl-server`。

::: details 不想用包管理器？用 tar.gz 二进制
```bash
curl -L https://github.com/jeffkit/hitl-mcp/releases/latest/download/hitl-server-linux-x86_64.tar.gz | tar xz
ENABLE_ILINK_ENGINE=true ILINK_BOT_KEY=ilink-bot-1 ./hitl-server/hitl-server
```
:::

## 启用引擎

装好并启动后，引擎可以通过两种方式启用，**任选其一**：

1. **管理台（推荐）**：打开 `http://localhost:8081/console`，在「引擎」页面扫码登录 iLink、填写企微 Bot 凭证。凭证会落盘，重启自动恢复。
2. **环境变量**：在启动命令或服务配置里设置（见下表）。Homebrew plist / systemd unit 已默认开了 iLink。

| 环境变量 | 作用 | 默认 |
|----------|------|------|
| `ENABLE_ILINK_ENGINE` | 启用微信 iLink 引擎 | `false`（brew/systemd 默认 `true`） |
| `ILINK_BOT_KEY` | iLink 引擎的路由键（MCP 端 `--bot-key` 对应它） | `ilink-bot-1` |
| `ENABLE_WECOM_AIBOT_ENGINE` | 启用企微 AI Bot 引擎 | `false` |
| `WECOM_AIBOT_BOT_KEY` | 企微引擎的路由键 | `wecom-aibot-1` |
| `WECOM_AIBOT_BOT_ID` | 企微 Bot ID | — |
| `WECOM_AIBOT_BOT_SECRET` | 企微 Bot Secret | — |
| `HITL_PORT` | 服务端口 | `8081` |

## 管理台

浏览器打开 **http://localhost:8081/console**

- 默认账号 `admin` / 密码 `jarvis2026`（可在环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 覆盖）。
- 「引擎」页面：扫码登录 iLink、填写/修改企微 Bot 凭证、查看连接状态、给 bot 发消息激活收件人。

## 验证服务正常

```bash
curl http://localhost:8081/api/ilink/login_status?bot_key=ilink-bot-1
```

返回 `{"status": "..."}` 即说明服务可达。

## 升级

- Homebrew：重新执行上面的 `curl + brew install --formula`（会覆盖旧版本），然后 `brew services restart hitl-server`。
- deb/rpm：装新版包 `sudo dpkg -i` / `sudo rpm -U`，再 `sudo systemctl restart hitl-server`。
- tar.gz：重新下载解压覆盖即可。

凭证与日志保留在 `~/.hitl`，升级不丢。

## 从源码构建（可选）

仅当需要自行修改代码或目标平台没有预构建产物时才需要。

```bash
git clone https://github.com/jeffkit/hitl-mcp.git
cd hitl-mcp/packages/hitl-server
uv sync
uv run python -m hitl_server.app
```

或一键构建二进制：`bash packaging/build.sh`（依赖 `uv` / `pnpm` / Python ≥ 3.10）。

## 下一步

- 启用具体引擎：[微信 ClawBot（iLink）](../engines/ilink) / [企微 AI 机器人](../engines/wecom-aibot)
- [配置 MCP 客户端](./mcp-config)
