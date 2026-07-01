# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**hitl-mcp** (Human-in-the-Loop MCP) 让 AI Agent 在执行关键操作前，通过微信 / 企业微信向用户确认。AI 把请求发给本地 `hitl-server`，`hitl-server` 把消息推到用户手机（微信 ClawBot 或企微 AI 机器人），用户回复后 AI 拿到结果继续执行。整个链路本地运行，无需公网服务器。

**Core Value**: 为需要人工确认 / 审阅 / 输入的 AI 自动化流程提供实时双向通信。

---

## Monorepo Architecture

```
hil-mcp/
├── packages/
│   ├── hitl-server/     # 本地后端（FastAPI + 内置引擎 + React 管理台）
│   ├── mcp-server-py/   # MCP 客户端（Python 版，uvx hil-mcp）
│   └── mcp-server-ts/   # MCP 客户端（TypeScript 版，npx hitl-mcp）
├── data/                # 数据存储（SQLite/JSON）
├── docs/                # 设计文档
├── docs-site/           # 用户文档站点源码
└── scripts/             # 辅助脚本
```

### Key Services

1. **hitl-server** - 本地单进程后端（内置 ilink + wecom-aibot 引擎 + React 管理台）
2. **mcp-server-py** - Python MCP 客户端 (`uvx hil-mcp`)
3. **mcp-server-ts** - TypeScript MCP 客户端 (`npx hitl-mcp`)

> **架构演进（2026-06-30）**：已移除旧的 relay/direct 模式、fly-pigeon 上游、
> `devcloud-worker` / `forward-service` / `ws-tunnel` 三个包、`ws_manager` / `sender` /
> `handlers/forward_client` / `handlers/websocket` / `slash_commands` / `idle_hint_config`
> 等模块，以及 MCP 端的 `hil` 引擎。新架构只保留 `hitl-server` 内置的 ilink 与
> wecom-aibot 两个引擎，所有消息收发在进程内完成。

---

## Development Commands

### Python Service (hitl-server)

```bash
cd packages/hitl-server
uv sync
uv run python -m hitl_server.app          # 前台运行
USE_DATABASE=true uv run python -m hitl_server.app   # 数据库模式
uv run pytest tests/ -v                    # 测试
uv build                                   # 构建包
```

### TypeScript Service (mcp-server-ts)

```bash
cd packages/mcp-server-ts
pnpm install
pnpm run build        # tsc + chmod +x dist/index.js
pnpm run typecheck    # tsc --noEmit
pnpm run dev
```

---

## Architecture Patterns

### 内置引擎（单进程）

`hitl-server` 进程内维持长连接，消息收发不经任何外部 Worker：

```
MCP Client ──HTTP──▶ hitl-server ──长连接──▶ 微信 / 企微
                      ├─ ilink 引擎（iLink 长轮询，个人微信 ClawBot）
                      └─ wecom-aibot 引擎（企微 WebSocket，企业微信 AI 机器人）
```

- 收到上游用户消息 → 进程内直接调 `storage.handle_callback`
- `/api/send` 命中内置引擎 → 进程内直接调 `engine.send_message`
- MCP 端 `--engine auto` 启动时查 `/admin/api/engines`，按 ilink→wecom-aibot 优先级选用

### 引擎注册

`hitl_server/engines/manager.py` 持有按配置启用的引擎实例，按 `worker_type` / `bot_key` 索引。`worker_type` 为引擎类型字段（`ilink` / `wecom-aibot`），名称沿用历史，非 Worker 概念。wecom-aibot 支持运行时动态注册（`/api/engines/wecom-aibot/start`，MCP 启动时自举）。

### Database Configuration

支持 JSON 文件与数据库两种存储，接口一致：

- **JSON**（默认）：`data/*.json`，热重载
- **Database**：`sqlite+aiosqlite:///./data/service.db` 或 MySQL，`USE_DATABASE=true` 启用，异步 SQLAlchemy

### Database Schema (hitl-server, 2 张表)

```sql
-- hil_sessions: 会话表
id, session_id (unique), short_id, chat_id, chat_type, message,
project_name, images (JSON), status, created_at, expire_at, updated_at

-- hil_replies: 回复表
id, session_id (foreign key), msg_type, content, image_url,
from_user (JSON), raw_data (JSON), timestamp
```

### Session Management

- **Timeout**: 默认 20 分钟（可配置）
- **Quote Reply Matching**: 多会话并发靠 `[#short_id]` 标签匹配
- **Project Identification**: 多项目可共用同一会话
- **收件人解析**: ilink/wecom-aibot 在未指定 chat_id 时，引擎解析出实际收件人后回传 chat_id，更新 session

---

## Environment Variables (hitl-server)

| 变量 | 作用 | 默认 |
|------|------|------|
| `HITL_PORT` | 服务端口 | `8081` |
| `HITL_HOST` | 监听地址 | `0.0.0.0` |
| `ENABLE_ILINK_ENGINE` | 启用 iLink 引擎 | `false` |
| `ILINK_BOT_KEY` | iLink 引擎路由键 | `ilink-bot-1` |
| `ILINK_BASE_URL` | iLink API 地址 | `https://ilinkai.weixin.qq.com` |
| `ILINK_TOKEN_STORE_PATH` | iLink 凭证存储路径 | `~/.hil-mcp/ilink_store.json` |
| `ENABLE_WECOM_AIBOT_ENGINE` | 启用企微 AI Bot 引擎 | `false` |
| `WECOM_AIBOT_BOT_KEY` | 企微引擎路由键 | `wecom-aibot-1` |
| `WECOM_AIBOT_BOT_ID` | 企微 Bot ID | — |
| `WECOM_AIBOT_BOT_SECRET` | 企微 Bot Secret | — |
| `USE_DATABASE` | 启用数据库模式 | `false` |
| `DATABASE_URL` | 数据库连接串 | `sqlite+aiosqlite:///./data/service.db` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理台账号 | `admin` / `jarvis2026` |
| `ADMIN_TOKEN_SECRET` | JWT 密钥 | `hil-mcp-secret-key-2026` |

---

## Database Migration (Alembic)

仅 `hitl-server` 使用 Alembic（2 张表）。常用命令：

```bash
cd packages/hitl-server
alembic current                              # 当前版本
alembic history                              # 迁移历史
alembic revision --autogenerate -m "desc"    # 生成迁移
alembic upgrade head                         # 升级
alembic downgrade -1                         # 回退一个版本
alembic upgrade head --sql > migration.sql   # 生成 SQL 供审查
```

修改 `hitl_server/models.py` 后必须用 Alembic 生成迁移脚本，不要直接改表结构。详见 `packages/hitl-server/ALEMBIC_GUIDE.md`。

---

## HTTP API (hitl-server)

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/send` | 发送消息（命中内置引擎进程内调用） |
| GET | `/api/poll/{session_id}` | 轮询回复 |
| POST | `/api/session/{session_id}/timeout` | 标记会话超时 |
| POST | `/api/upload-image` | 上传图片，返回 data URL |
| GET | `/api/ilink/qr` | iLink 扫码二维码 |
| GET | `/api/ilink/login_status` | iLink 登录状态 |
| GET | `/api/ilink/activated_users` | iLink 已激活用户 |
| POST | `/api/engines/wecom-aibot/start` | 运行时启动企微 AI Bot 引擎 |
| GET | `/health` | 健康检查 |

完整说明见 `docs/API.md`。

---

## Common Workflows

### 本地开发

```bash
cd packages/hitl-server
uv run python -m hitl_server.app
# 管理台 http://localhost:8081/console
```

### 构建 TypeScript MCP 客户端

```bash
cd packages/mcp-server-ts
pnpm run build
```

### 添加 / 修改数据库字段

```bash
cd packages/hitl-server
# 1. 编辑 hitl_server/models.py
# 2. 生成迁移
alembic revision --autogenerate -m "add new field"
# 3. 检查 alembic/versions/xxxxx_.py
# 4. 执行
alembic upgrade head
```

---

## Important Notes

- **存储模式**：JSON 与数据库模式 API 一致，通过 `USE_DATABASE` 切换；开发用 SQLite，生产用 MySQL。
- **安全**：管理台由 JWT（账号密码）保护；iLink 凭证落盘于 `ILINK_TOKEN_STORE_PATH`，企微凭证落盘后重启自动恢复。
- **MCP 引擎类型**：`auto` / `ilink` / `wecom-aibot`（`hil` 已移除）。

---

## Related Documentation

- `README.md` - 项目主文档
- `docs/API.md` - HTTP API 文档
- `docs/SHARED_POLLING_BACKEND_DESIGN.md` - 共享轮询后端设计
- `docs-site/guide/` - 用户文档（架构 / 快速开始 / 安装 / 配置 / FAQ）
- `docs-site/engines/` - 引擎文档（ilink / wecom-aibot）
- `packages/hitl-server/ALEMBIC_GUIDE.md` - 数据库迁移指南
