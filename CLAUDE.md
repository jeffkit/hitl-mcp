# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HIL-MCP** (Human-in-the-Loop MCP for WeCom) is an enterprise WeChat middleware system that enables AI Agents to send messages to WeChat and wait for user replies. The project is a **Monorepo** containing coordinated services.

**Core Value**: Provides real-time bidirectional communication for AI automation workflows requiring human confirmation, review, or input.

---

## Monorepo Architecture

The project is organized as a Monorepo with the following structure:

```
hil-mcp/
├── packages/
│   ├── hil-server/         # HIL Server (FastAPI + React admin console)
│   ├── devcloud-worker/    # Intranet Worker (WebSocket connection)
│   ├── forward-service/    # Message forwarding service (database support)
│   ├── mcp-server-py/      # MCP client (Python version)
│   └── mcp-server-ts/      # MCP client (TypeScript version)
├── data/                   # Data storage (SQLite/JSON)
├── tests/                  # Test suite
└── scripts/                # Deployment scripts
```

### Key Services

1. **hil-server** - Main HIL Server (Relay/Direct modes)
2. **devcloud-worker** - Intranet worker for Relay mode
3. **forward-service** - Reverse message forwarding (user-triggered → target URL)
4. **mcp-server-py** - Python MCP client (`uvx hil-mcp`)
5. **mcp-server-ts** - TypeScript MCP client (`npx @hitl/mcp-server`)

---

## Development Commands

### Python Services (hil-server, forward-service, devcloud-worker)

```bash
# Install dependencies (using uv - modern Python package manager)
cd packages/<service-name>
uv sync

# Run service (development)
uv run python -m <package>.app

# Run with specific mode
USE_DATABASE=true uv run python -m <package>.app

# Build package
uv build
```

### TypeScript Service (mcp-server-ts)

```bash
cd packages/mcp-server-ts

# Install dependencies
pnpm install

# Build
pnpm run build

# Development
pnpm run dev

# Type check
pnpm run typecheck
```

### Running Tests

```bash
# HIL Server tests
cd packages/hil-server
uv run pytest tests/ -v

# Run single test
uv run pytest tests/test_storage.py::test_create_session -v
```

### Deployment

```bash
# 同步代码到 Pro 服务器
./scripts/sync_to_pro.sh          # 同步所有服务
./scripts/sync_to_pro.sh forward  # 只同步 forward-service
./scripts/sync_to_pro.sh hil      # 只同步 hil-server
```

**⚠️ 重要**: Pro 服务器使用 **main** 分支代码，必须通过 Git 部署，**禁止使用 rsync 直接同步代码**！

正确的部署流程：
```bash
# 在 Pro 服务器上执行
cd /data/projects/hitl && git pull origin main && sudo systemctl restart hil-service as-dispatch
```

---

## Architecture Patterns

### Dual Mode Operation (HIL Server)

The HIL Server supports two operation modes that automatically switch based on configuration:

**Relay Mode** (Public network deployment):
```
MCP Client → HIL Server (public) ←WebSocket→ Worker (intranet) → fly-pigeon API → WeChat
```
- Use when MCP is on public network, fly-pigeon API only accessible from intranet
- Worker actively connects to HIL Server to penetrate intranet

**Direct Mode** (Intranet deployment):
```
MCP Client → HIL Server (intranet) → fly-pigeon API → WeChat
```
- Use when all components are in intranet
- No Worker needed, simplified deployment

**Mode auto-switching**:
- If `BOT_KEY` is configured → Direct mode
- If `BOT_KEY` not configured → Relay mode
- `HIL_MODE=direct` or `HIL_MODE=relay` → Force specific mode

### Database Configuration Pattern

Both HIL Server and Forward Service support dual configuration storage:

**JSON File** (default):
- Storage: `data/*.json`
- Hot reload without restart
- Simple and portable

**Database** (production):
- SQLite: `sqlite+aiosqlite:///./data/service.db`
- MySQL: `mysql+pymysql://user:pass@host:port/db`
- Enabled via: `USE_DATABASE=true`
- Async operations for better performance
- Session persistence survives service restarts

**API Compatibility**: Both storage modes expose identical interfaces
```python
config.get_bot(bot_key)
config.check_access(bot, user_id)
await config.update_from_dict(data)  # Async in database mode
await config.reload_config()  # Async in database mode
```

---

## Key Technical Details

### Dependency Management

**Critical Dependencies**:
- `fly-pigeon>=1.0.9` - Tencent fly-pigeon API (internal mirror required)
- `greenlet>=3.0.0,<3.1.0` - Version locked to avoid compilation failures
- `mcp>=1.0.0` - Model Context Protocol
- `alembic>=1.13.0` - Database migration tool (hil-server, forward-service)

**Tencent Mirror Configuration** (.uvrc or pyproject.toml):
```toml
extra-index-url = ["http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple"]
```

### Database Schema

**hil-server (2 张表)**:
```sql
-- hil_sessions: HIL 会话表
id, session_id (unique), short_id, chat_id, chat_type, message,
project_name, images (JSON), status, created_at, expire_at, updated_at

-- hil_replies: 会话回复表
id, session_id (foreign key), msg_type, content, image_url,
from_user (JSON), raw_data (JSON), timestamp
```

**forward-service (7 张表)**:
```sql
-- chatbots: Bot 配置表
id, bot_key (unique), name, description, url_template,
agent_id, api_key, timeout, access_mode, enabled, created_at, updated_at

-- chat_access_rules: 访问规则表（黑白名单）
id, chatbot_id (foreign key), chat_id, rule_type ('whitelist'/'blacklist'),
remark, created_at

-- user_sessions: 用户会话表
id, user_id, chat_id, bot_key, session_id, short_id,
last_message, message_count, is_active, created_at, updated_at

-- forward_logs: 转发日志表
id, timestamp, chat_id, from_user_id, from_user_name,
content, msg_type, bot_key, bot_name, target_url, session_id,
status, response, error, duration_ms

-- processing_sessions: 处理中会话表（并发控制）
id, session_key (unique), user_id, chat_id, bot_key, message, started_at

-- system_config: 系统配置表（key-value 存储）
id, key (unique), value (JSON), description, created_at, updated_at

-- tunnels: 隧道配置表（Tunely WebSocket 隧道）
id, tunnel_id (unique), name, target_url, status, connected_at
```

### Session Management (HIL Server)

- **Timeout**: Default 20 minutes (configurable)
- **Quote Reply Matching**: Multi-session concurrency via `[#short_id]` tags
- **Project Identification**: Multiple projects can share same chat group
- **Conflict Detection**: Auto-prompt users to use quote replies

### Idle Hint Message Configuration

Supports variable substitution:
```python
"👋 Hello {user_name}! 📋 Chat ID: `{chat_id}` 🕐 {timestamp}"
```

Supported variables: `{user_name}`, `{chat_id}`, `{chat_type}`, `{timestamp}`

---

## Environment Variables

### HIL Server
- `HIL_PORT` - Service port (default: 8081)
- `HIL_MODE` - Operation mode: auto/relay/direct (default: auto)
- `BOT_KEY` - fly-pigeon bot key (required for direct mode)
- `HIL_WORKER_TOKEN` - Worker authentication token (optional)
- `HIL_USE_DATABASE` - Enable database mode (true/false)
- `HIL_DATABASE_URL` - Database connection string

### Forward Service
- `FORWARD_PORT` - Service port (default: 8083)
- `USE_DATABASE` - Enable database mode (true/false)
- `DATABASE_URL` - Database connection string
- `DEFAULT_BOT_KEY` - Default bot key

### DevCloud Worker
- `HIL_URL` - HIL Server WebSocket address (default: ws://localhost:8081/ws)
- `HIL_TOKEN` - Connection authentication token
- `BOT_KEY` - fly-pigeon webhook key (required)

---

## Database Migration

**数据迁移 (JSON → Database)**:
```bash
# Dry run (no actual writes)
python migrate_to_database.py --dry-run

# Migrate from JSON to database
python migrate_to_database.py

# Force overwrite existing records
python migrate_to_database.py --force
```

**数据库结构迁移 (Alembic)**:

本项目使用 **Alembic** 管理数据库 schema 版本，支持平滑升级和回滚。

**支持的服务**:
- `hil-server` - 2 张表 (hil_sessions, hil_replies)
- `forward-service` - 7 张表 (chatbots, chat_access_rules, user_sessions, forward_logs, processing_sessions, system_config, tunnels)

**常用命令**:
```bash
# 进入服务目录
cd packages/hil-server       # 或 cd packages/forward-service

# 查看当前数据库版本
alembic current

# 查看迁移历史
alembic history

# 生成新的迁移（修改 models.py 后执行）
alembic revision --autogenerate -m "描述你的变更"

# 执行迁移（升级到最新版本）
alembic upgrade head

# 回退一个版本
alembic downgrade -1

# 生成 SQL 供审查（不执行）
alembic upgrade head --sql > migration.sql
```

**工作流程**（当需要修改数据库结构时）:
```bash
# 1. 修改 models.py（添加/删除表或字段）

# 2. 生成迁移脚本
alembic revision --autogenerate -m "add new field"

# 3. 检查生成的迁移脚本（alembic/versions/xxxxx_.py）
#    - 确认 upgrade() 函数符合预期
#    - 确认 downgrade() 函数可以正确回滚

# 4. 执行迁移
alembic upgrade head

# 5. 测试应用功能

# 6. 提交代码
git add alembic/versions/xxxxx_.py
git commit -m "feat: database migration - add new field"
```

**生产环境部署**:
```bash
# 1. 生成 SQL 供审查
alembic upgrade head --sql > migration.sql

# 2. 审查 SQL 内容

# 3. 备份数据库
cp data/service.db data/service.db.backup

# 4. 执行迁移
alembic upgrade head

# 5. 验证应用功能
```

**环境变量**:
- `hil-server`: `HIL_DATABASE_URL` - 默认 `sqlite+aiosqlite:///./data/hil_server.db`
- `forward-service`: `DATABASE_URL` - 默认 `sqlite+aiosqlite:///./data/forward_service.db`

**详细文档**:
- `packages/hil-server/ALEMBIC_GUIDE.md`
- `packages/forward-service/ALEMBIC_GUIDE.md` (if exists)

---

## Deployment Architecture

### Production Server (Pro)

| 项目 | 值 |
|------|-----|
| **主机名** | VM-243-90-tencentos |
| **IP 地址** | 21.6.243.90 |
| **域名** | hitl.woa.com |
| **SSH 别名** | pro |
| **Git 仓库** | git.woa.com/kongjie/tmp |
| **分支** | main |

#### 服务配置

| 服务 | Systemd 单元 | 端口 |
|------|-------------|------|
| HIL Server | `hil-service.service` | 8081 |
| AS-Dispatch | `as-dispatch.service` | 8083 |

#### 数据库

- **类型**: MySQL
- **主机**: 9.135.244.245:3306
- **数据库**: agentstudio
- **字符集**: utf8mb4

#### 部署流程（重要）

```bash
# 1. 在本地：确保代码已提交并合并到 main 分支
git checkout develop
git add -A && git commit -m "your change description"
git checkout main
git merge develop
git push origin main

# 2. 在 Pro 服务器上：拉取代码并重启服务
ssh pro
cd /data/projects/hitl
git pull origin main

# 3. 重启服务
sudo systemctl restart hil-service as-dispatch
```

**快捷部署（在 Pro 服务器执行）**:
```bash
cd /data/projects/hitl && git pull origin main && sudo systemctl restart hil-service as-dispatch
```

### 服务管理

```bash
# 查看状态
sudo systemctl status hil-service as-dispatch

# 查看日志
sudo journalctl -u hil-service -f
sudo journalctl -u as-dispatch -f

# 重启服务
sudo systemctl restart hil-service as-dispatch
```

**详细部署文档**: 参见 `docs/PRO_DEPLOYMENT_V2.md`

---

## Common Workflows

### Adding New Bot Configuration

**Database Mode**:
```bash
# Via API
curl -X PUT http://localhost:8083/admin/config \
  -H "Content-Type: application/json" \
  -d '{
    "default_bot_key": "bot1",
    "bots": {
      "bot1": {
        "bot_key": "bot1",
        "name": "Test Bot",
        "forward_config": {"url_template": "https://api.com"},
        "enabled": true
      }
    }
  }'
```

**JSON Mode**: Edit `data/forward_bots.json` (hot reload)

### Adding New Database Models or Fields

当需要修改数据库结构（添加新表、新字段、修改字段类型等）时，**必须使用 Alembic** 进行迁移：

```bash
# 1. 修改 models.py
# 例如：添加新字段
cd packages/hil-server  # 或 packages/forward-service

# 编辑 hil_server/models.py (或 forward_service/models.py)
# 添加新的 Column 或修改现有字段定义

# 2. 生成迁移脚本
alembic revision --autogenerate -m "add new field to table"

# 3. 检查生成的迁移脚本
cat alembic/versions/xxxxx_add_new_field_to_table.py
# 确认 upgrade() 和 downgrade() 函数正确

# 4. 执行迁移
alembic upgrade head

# 5. 测试应用功能
# 6. 提交迁移脚本
git add alembic/versions/xxxxx_add_new_field_to_table.py
git commit -m "feat: database migration - add new field"
```

**⚠️ 重要**: 不要直接修改数据库表结构，必须通过 Alembic 迁移，确保开发/测试/生产环境同步。

### Migrating from JSON to Database

```bash
# 1. Run migration
USE_DATABASE=true python migrate_to_database.py

# 2. Verify migration
curl http://localhost:8083/admin/config

# 3. Restart service with database mode
USE_DATABASE=true python -m forward_service.app
```

### Enabling SQL Debug Logging

```bash
export DATABASE_ECHO="true"
USE_DATABASE=true python -m <service>.app
```

---

## Important Notes

### Backward Compatibility

- JSON and database modes can coexist
- Switch between modes via `USE_DATABASE` environment variable
- API interfaces remain identical across both modes

### Performance Considerations

- Database mode uses async SQLAlchemy for better performance
- Connection pooling managed automatically
- Use SQLite for development, MySQL for production

### Security

- Worker connections authenticated via `HIL_WORKER_TOKEN`
- Admin console protected by JWT (username/password)
- Callback authentication supported via custom headers

---

## Related Documentation

- `README.md` - Main project documentation
- `docs/PRO_DEPLOYMENT_V2.md` - Pro 服务器部署文档（最新）⭐
- `docs/PRO_DEPLOYMENT.md` - Pro 服务器部署文档（旧版）
- `docs/DATABASE_SUMMARY.md` - Database implementation summary
- `docs/API.md` - API 接口文档
- `docs/DATABASE_MIGRATION.md` - Data migration guide (JSON → Database)
- `DEPLOY_BOT_MANAGEMENT.md` - Bot management deployment
- `packages/hil-server/ALEMBIC_GUIDE.md` - HIL Server 数据库迁移指南

---

## Quick Start

**Local Development (JSON mode)**:
```bash
cd packages/hil-server
uv run python -m hil_server.app
```

**Local Development (Database mode)**:
```bash
cd packages/forward-service
USE_DATABASE=true uv run python -m forward_service.app
```

**Build TypeScript MCP Client**:
```bash
cd packages/mcp-server-ts
pnpm run build
```
