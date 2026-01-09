# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HIL-MCP** (Human-in-the-Loop MCP for WeCom) is an enterprise WeChat middleware system that enables AI Agents to send messages to WeChat and wait for user replies. The project is a **Monorepo** containing 5 independent but coordinated services.

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
├── tests/                  # Test suite (21 unit tests, all passing)
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
# Forward Service database tests (21 tests)
cd packages/forward-service
uv run pytest tests/test_database.py -v

# Run single test
uv run pytest tests/test_database.py::TestChatbotRepository::test_create_bot -v
```

### Deployment

```bash
# Deploy HIL Server
./deploy_hil.sh

# Deploy Forward Service
./deploy_forward.sh

# Deploy DevCloud Worker
./deploy_worker.sh
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

### Repository Pattern (Database Layer)

Forward Service uses the Repository pattern for data access:

```
models.py (ORM models)
    ↓
repository.py (data access layer)
    ↓
config_db.py (business logic)
    ↓
app.py (API endpoints)
```

**Key files**:
- `models.py` - SQLAlchemy ORM models (Chatbot, ChatAccessRule)
- `repository.py` - Data access with CRUD operations
- `config_db.py` - Business logic wrapper

---

## Key Technical Details

### Dependency Management

**Critical Dependencies**:
- `fly-pigeon>=2.0.0` - Tencent fly-pigeon API (internal mirror required)
- `greenlet>=3.0.0,<3.1.0` - Version locked to avoid compilation failures
- `mcp>=1.0.0` - Model Context Protocol

**Tencent Mirror Configuration** (.uvrc):
```toml
extra-index-url = ["http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple"]
```

### Database Schema

**chatbots table**:
```sql
id, bot_key (unique), name, description, url_template,
agent_id, api_key, timeout, access_mode, enabled,
created_at, updated_at
```

**chat_access_rules table**:
```sql
id, chatbot_id (foreign key), chat_id, rule_type ('whitelist'/'blacklist'),
remark, created_at
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
- `USE_DATABASE` - Enable database mode (true/false)
- `DATABASE_URL` - Database connection string

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

## Testing

### Forward Service Database Tests

**Test Coverage**: 21 unit tests (all passing ✅)
- Chatbot model: 6 tests
- ChatAccessRule model: 1 test
- ChatbotRepository: 7 tests
- ChatAccessRuleRepository: 7 tests

**Running tests**:
```bash
cd packages/forward-service
uv run pytest tests/test_database.py -v
# ========================= 21 passed in 0.31s =========================
```

### Database Migration

```bash
# Dry run (no actual writes)
python migrate_to_database.py --dry-run

# Migrate from JSON to database
python migrate_to_database.py

# Force overwrite existing records
python migrate_to_database.py --force
```

---

## Deployment Architecture

### Production Servers

#### **dev 服务器** (旧目录结构)

| 服务 | 代码位置 | WorkingDirectory |
|------|----------|------------------|
| forward-service | `/root/projects/hil-mcp/forward_service/` | `/root/projects/hil-mcp` |
| hil-server | `/root/projects/hil-mcp-direct/hil_server/` | `/root/projects/hil-mcp-direct` |

**⚠️ 重要**: dev 服务器使用旧目录结构，代码需同步到正确位置：
```bash
# forward-service: 同步 forward_service/ 子目录内容（不含 tests）
rsync -avz packages/forward-service/forward_service/ dev:/root/projects/hil-mcp/forward_service/

# hil-server: 同步 hil_server/ 子目录内容
rsync -avz packages/hil-server/hil_server/ dev:/root/projects/hil-mcp-direct/hil_server/
```

#### **devg 服务器** (monorepo 结构)

| 服务 | 代码位置 | WorkingDirectory |
|------|----------|------------------|
| forward-service | `/data/projects/hil-mcp/packages/forward-service/` | 同左 |
| hil-server | `/data/projects/hil-mcp/packages/hil-server/` | 同左 |

**部署命令**:
```bash
# forward-service
rsync -avz packages/forward-service/ devg:/data/projects/hil-mcp/packages/forward-service/

# hil-server
rsync -avz packages/hil-server/ devg:/data/projects/hil-mcp/packages/hil-server/
```

#### 端口配置

| 服务 | 端口 | 域名 (devg) |
|------|------|-------------|
| hil-server | 8081 | test-hitl.woa.com |
| forward-service | 8083 | test-hitl.woa.com/forward/ |

### Systemd Services

- `hil-forward.service` - Forward Service
- `hil-worker.service` - DevCloud Worker
- `hil-server-direct.service` - HIL Server

**Service management**:
```bash
sudo systemctl start|stop|restart|status <service-name>
sudo journalctl -u <service-name> -f  # View logs
```

### 部署脚本

项目提供了两个同步脚本，避免手动部署时搞错路径：

```bash
# 同步代码到 dev 服务器
./scripts/deploy/sync_to_dev.sh          # 同步所有服务
./scripts/deploy/sync_to_dev.sh forward  # 只同步 forward-service
./scripts/deploy/sync_to_dev.sh hil      # 只同步 hil-server

# 同步代码到 devg 服务器
./scripts/deploy/sync_to_devg.sh         # 同步所有服务
./scripts/deploy/sync_to_devg.sh forward # 只同步 forward-service
./scripts/deploy/sync_to_devg.sh hil     # 只同步 hil-server
```

**⚠️ 重要**: 始终使用这些脚本进行部署，它们会自动处理不同服务器的目录结构差异。

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

- `README.md` - Main project documentation (840+ lines)
- `DATABASE_SUMMARY.md` - Database implementation summary
- `DATABASE_MIGRATION.md` - Data migration guide
- `DEPLOY_BOT_MANAGEMENT.md` - Bot management deployment

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
