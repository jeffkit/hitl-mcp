# Forward Service 数据库迁移文档

## 概述

Forward Service 已从 JSON 配置文件迁移到数据库存储,提供更好的可维护性和扩展性。

**主要改进:**
- ✅ 使用 SQLAlchemy ORM,支持多种数据库 (SQLite/MySQL)
- ✅ 完整的 Repository 层,封装所有数据库操作
- ✅ 21 个单元测试,覆盖所有核心功能
- ✅ 支持开发/测试环境使用 SQLite,生产环境使用 MySQL
- ✅ 提供数据迁移工具,从 JSON 平滑迁移到数据库

---

## 数据库表结构

### 1. chatbots 表

存储企业微信机器人的配置信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| bot_key | VARCHAR(100) | 企微机器人 Webhook Key (唯一) |
| name | VARCHAR(200) | Bot 名称 |
| description | TEXT | Bot 描述 |
| url_template | VARCHAR(500) | 转发目标 URL 模板 (支持 {agent_id} 占位符) |
| agent_id | VARCHAR(100) | Agent ID (用于 URL 模板替换) |
| api_key | VARCHAR(200) | 转发请求的 API Key (可选) |
| timeout | INTEGER | 转发请求超时时间 (秒) |
| access_mode | VARCHAR(20) | 访问控制模式: allow_all, whitelist, blacklist |
| enabled | BOOLEAN | 是否启用 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 2. chat_access_rules 表

存储每个 Bot 的访问控制规则 (黑白名单)。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| chatbot_id | INTEGER | 关联的 Bot ID (外键) |
| chat_id | VARCHAR(200) | Chat ID (用户ID或群ID) |
| rule_type | VARCHAR(20) | 规则类型: whitelist 或 blacklist |
| remark | VARCHAR(500) | 备注说明 |
| created_at | DATETIME | 创建时间 |

**约束:**
- `(chatbot_id, chat_id, rule_type)` 唯一,避免重复规则
- 删除 Bot 时会级联删除所有关联的访问规则

---

## 安装依赖

```bash
# 已添加到 requirements.txt
pip install sqlalchemy>=2.0.0
pip install aiosqlite>=0.19.0  # SQLite (开发/测试)
pip install pymysql>=1.1.0     # MySQL (生产)
pip install cryptography>=41.0.0  # PyMySQL 依赖
```

---

## 数据库配置

### 环境变量

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| DATABASE_URL | 数据库连接 URL | `sqlite+aiosqlite:///./data/forward_service.db` |
| DATABASE_ECHO | 是否打印 SQL 语句 (用于调试) | `false` |

### 数据库 URL 格式

#### SQLite (开发/测试)
```bash
# 文件数据库
export DATABASE_URL="sqlite+aiosqlite:///./data/forward_service.db"

# 内存数据库 (仅用于测试)
export DATABASE_URL="sqlite+aiosqlite:///:memory:"
```

#### MySQL (生产环境)
```bash
export DATABASE_URL="mysql+pymysql://user:password@host:port/database"

# 示例
export DATABASE_URL="mysql+pymysql://forward_user:pass123@localhost:3306/forward_service"
```

---

## 数据迁移

### 从 JSON 配置迁移到数据库

#### 1. 查看现有配置

```bash
# 查看将要执行的迁移 (不实际写入数据库)
python migrate_to_database.py --dry-run
```

#### 2. 执行迁移

```bash
# 首次迁移 (跳过已存在的记录)
python migrate_to_database.py

# 强制覆盖已存在的记录
python migrate_to_database.py --force
```

#### 3. 迁移输出示例

```
============================================================
开始迁移配置到数据库
============================================================
已加载配置文件: /path/to/data/forward_bots.json
默认 Bot Key: <YOUR_BOT_KEY>
Bot 数量: 2
  创建 Bot: <YOUR_BOT_KEY> - 默认测试机器人
    迁移白名单: 0 条
    迁移黑名单: 0 条
  创建 Bot: test_bot_key_2 - 白名单测试 Bot
    迁移白名单: 1 条
    迁移黑名单: 0 条
============================================================
迁移完成:
  创建: 2
  更新: 0
  跳过: 0
============================================================
```

---

## 使用示例

### 1. 初始化数据库

```python
from forward_service.database import init_database, close_database

# 初始化 (会自动创建表)
await init_database(echo=False)

# 关闭连接
await close_database()
```

### 2. 创建 Bot 配置

```python
from forward_service.repository import get_chatbot_repository
from forward_service.database import get_db_manager

async with get_db_manager().get_session() as session:
    repo = get_chatbot_repository(session)

    bot = await repo.create(
        bot_key="test_bot_key",
        name="测试 Bot",
        url_template="https://api.com/a2a/{agent_id}/msg",
        agent_id="agent-001",
        api_key="sk-test",
        timeout=30,
        access_mode="whitelist",
        enabled=True
    )

    print(f"创建成功: {bot.id} - {bot.name}")
```

### 3. 设置访问规则

```python
from forward_service.repository import get_access_rule_repository

async with get_db_manager().get_session() as session:
    rule_repo = get_access_rule_repository(session)

    # 批量设置白名单
    await rule_repo.set_whitelist(
        chatbot_id=bot.id,
        chat_ids=["user1", "user2", "user3"]
    )

    # 批量设置黑名单
    await rule_repo.set_blacklist(
        chatbot_id=bot.id,
        chat_ids=["bad_user1", "bad_user2"]
    )
```

### 4. 查询 Bot

```python
async with get_db_manager().get_session() as session:
    repo = get_chatbot_repository(session)

    # 根据 bot_key 查询
    bot = await repo.get_by_bot_key("test_bot_key")

    # 检查访问权限
    allowed, reason = bot.check_access("user1")
    if allowed:
        print(f"用户 user1 有权限访问 {bot.name}")
    else:
        print(f"用户 user1 无权访问: {reason}")
```

### 5. 更新 Bot

```python
async with get_db_manager().get_session() as session:
    repo = get_chatbot_repository(session)

    bot = await repo.update(
        bot_id=bot.id,
        name="新名称",
        timeout=60
    )
```

### 6. 删除 Bot

```python
async with get_db_manager().get_session() as session:
    repo = get_chatbot_repository(session)

    success = await repo.delete(bot_id=bot.id)
    if success:
        print("Bot 已删除 (关联的访问规则也会自动删除)")
```

---

## 运行单元测试

```bash
# 运行所有数据库测试
python -m pytest tests/test_database.py -v

# 运行特定测试
python -m pytest tests/test_database.py::TestChatbotRepository::test_create_bot -v

# 查看测试覆盖率
python -m pytest tests/test_database.py --cov=forward_service.models --cov=forward_service.repository --cov-report=html
```

**测试覆盖:**
- ✅ Chatbot 模型 (6 个测试)
- ✅ ChatAccessRule 模型 (1 个测试)
- ✅ ChatbotRepository (7 个测试)
- ✅ ChatAccessRuleRepository (7 个测试)

---

## FastAPI 集成

### 使用依赖注入

```python
from fastapi import FastAPI, Depends
from forward_service.database import database_lifespan, get_session
from forward_service.repository import get_chatbot_repository
from sqlalchemy.ext.asyncio import AsyncSession

app = FastAPI(lifespan=database_lifespan)

@app.get("/api/bots")
async def list_bots(session: AsyncSession = Depends(get_session)):
    repo = get_chatbot_repository(session)
    bots = await repo.get_all(include_rules=True)
    return {"bots": [bot.to_dict() for bot in bots]}
```

---

## 文件结构

```
forward_service/
├── models.py          # SQLAlchemy ORM 模型定义
├── database.py        # 数据库连接管理
├── repository.py      # 数据访问层 (Repository/DAO)
└── config_v2.py       # 旧的 JSON 配置 (保留兼容)

tests/
└── test_database.py   # 单元测试 (21 个测试用例)

migrate_to_database.py # 数据迁移工具
```

---

## 下一步

### 立即可用:
1. ✅ 数据库模型和 Repository 已完成
2. ✅ 所有单元测试通过 (21/21)
3. ✅ 数据迁移工具已就绪

### 待完成:
4. ⏳ 修改 `forward_service/app.py` 以使用数据库
5. ⏳ 更新管理台 API 以支持数据库操作
6. ⏳ 生产环境 MySQL 部署配置

---

## 常见问题

### Q: 如何切换到生产环境 MySQL?

```bash
# 设置 MySQL 连接 URL
export DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/forward_service"

# 重启服务即可 (无需修改代码)
```

### Q: 如何查看 SQL 语句?

```bash
# 设置环境变量
export DATABASE_ECHO="true"

# 或在代码中
await init_database(echo=True)
```

### Q: 如何回滚到 JSON 配置?

数据库与 JSON 配置可以并存。如果需要回滚,只需:
1. 停止使用数据库代码
2. 继续使用 `config_v2.py` (JSON 配置)
3. 数据库数据保留,不影响

---

## 技术栈

- **ORM:** SQLAlchemy 2.0+ (异步支持)
- **开发数据库:** SQLite + aiosqlite
- **生产数据库:** MySQL + PyMySQL
- **测试:** pytest + pytest-asyncio
- **代码覆盖率:** 21 个单元测试,覆盖所有核心功能
