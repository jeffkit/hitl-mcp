# 本地安装 hitl-server

`hitl-server` 是 hitl-mcp 的本地后端，负责维持微信/企微的长连接、管理会话与回复匹配。它跑在你本机 `127.0.0.1:8081`，**不需要公网 IP**。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | 跑 hitl-server |
| [uv](https://docs.astral.sh/uv/) | 最新 | 管理依赖与虚拟环境（推荐） |
| Node.js | ≥ 18 | 跑 MCP 端 `npx hitl-mcp` |
| OS | macOS / Linux | 一键服务化仅 macOS |

安装 uv（如尚未安装）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 安装

### 方式一：从源码安装（推荐）

```bash
git clone https://github.com/jeffkit/hitl-mcp.git
cd hitl-mcp/packages/hitl-server

# 创建虚拟环境并安装依赖
uv sync
```

`uv sync` 会在 `packages/hitl-server/.venv` 里装好所有依赖（fastapi、uvicorn、websockets、httpx 等）。

### 方式二：从 PyPI 安装

```bash
uv tool install hitl-server
# 之后可直接：hitl-server
```

> 个人端默认只装 iLink + wecom-aibot 引擎所需的依赖。**无需** 安装腾讯内网的 fly-pigeon，本文档也不涉及它。

## 启动

### 前台运行（调试用）

```bash
cd packages/hitl-server
uv run python -m hitl_server.app
```

看到类似下面的日志就说明起来了：

```
INFO:     Uvicorn running on http://127.0.0.1:8081
INFO:     管理台: http://localhost:8081/console
```

### 后台常驻（macOS，推荐）

iLink 引擎自带「一键服务化」命令，会把 hitl-server 注册成 launchd 服务：开机自启、崩溃自动重启、日志落到 `~/.hitl/logs/`。

```bash
npx -y hitl-mcp ilink-setup --service-url http://localhost:8081
```

> 即使你主要用 wecom-aibot，也可以借用这个命令把 hitl-server 服务化，加 `--enable-wecom-aibot` 一起启用企微引擎。详见 [iLink 一键安装](../engines/ilink#一键安装推荐)。

### 后台常驻（Linux）

用 systemd 自行管理，示例：

```ini
# /etc/systemd/system/hitl-server.service
[Unit]
Description=hitl-server
After=network.target

[Service]
WorkingDirectory=/opt/hitl-mcp/packages/hitl-server
Environment=ENABLE_ILINK_ENGINE=true
Environment=ILINK_BOT_KEY=ilink-bot-1
ExecStart=/opt/hitl-mcp/packages/hitl-server/.venv/bin/python -m hitl_server.app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now hitl-server
```

## 启用引擎

引擎通过环境变量开关。两个引擎可同时启用。

| 环境变量 | 作用 | 默认 |
|----------|------|------|
| `ENABLE_ILINK_ENGINE` | 启用微信 iLink 引擎 | `false` |
| `ILINK_BOT_KEY` | iLink 引擎的路由键（MCP 端 `--bot-key` 对应它） | `ilink-bot-1` |
| `ILINK_BASE_URL` | iLink API 地址 | `https://ilinkai.weixin.qq.com` |
| `ILINK_TOKEN_STORE_PATH` | iLink 凭证存储路径 | `~/.hil-mcp/ilink_store.json` |
| `ENABLE_WECOM_AIBOT_ENGINE` | 启用企微 AI Bot 引擎 | `false` |
| `WECOM_AIBOT_BOT_KEY` | 企微引擎的路由键 | `wecom-aibot-1` |
| `WECOM_AIBOT_BOT_ID` | 企微 Bot ID | — |
| `WECOM_AIBOT_BOT_SECRET` | 企微 Bot Secret | — |
| `WECOM_AIBOT_WS_URL` | 企微 WebSocket 地址 | `wss://openws.work.weixin.qq.com` |
| `HITL_PORT` | 服务端口 | `8081` |

也可以 **不设环境变量**，启动后到管理台里手动启用并填凭证。两种方式等价。

## 管理台

启动后浏览器打开：**http://localhost:8081/console**

- 默认账号 `admin` / 密码 `jarvis2026`（可在环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 覆盖）。
- 在「引擎」页面可以：扫码登录 iLink、填写/修改企微 Bot 凭证、查看连接状态、给 bot 发消息激活收件人。

## 验证服务正常

```bash
# 健康检查
curl http://localhost:8081/api/ilink/login_status?bot_key=ilink-bot-1
```

返回 `{"status": "..."}` 即说明服务可达（`status` 取决于是否已扫码登录）。

## 升级

```bash
cd packages/hitl-server
git pull
uv sync
# 重启服务
```

## 下一步

- 启用具体引擎：[微信 ClawBot（iLink）](../engines/ilink) / [企微 AI 机器人](../engines/wecom-aibot)
- [配置 MCP 客户端](./mcp-config)
