# HIL-MCP Deployment Guide

本文档记录 HIL-MCP 项目的部署相关知识和注意事项。

## 项目架构

项目包含三个主要服务:
- **hil-forward**: Forward Service - 企业微信消息转发服务 (现已支持数据库模式)
- **hil-worker**: Worker Service - 后台任务处理服务
- **hil-server-direct**: Direct MCP Server

## 开发环境

### Python 版本
- **要求**: Python 3.10 或更高版本
- **管理工具**: uv (现代 Python 包管理器)
- **虚拟环境**: `.venv` (由 uv 创建和管理)

### 依赖说明

**重要依赖**:
- `fly-pigeon>=2.0.0` - 腾讯内部包,需要使用腾讯镜像源
- `greenlet>=3.0.0,<3.1.0` - 必须锁定版本,避免编译失败

**为什么锁定 greenlet 版本?**
- greenlet 3.3.0 在 CentOS 上编译失败
- 解决方案: 锁定到 `>=3.0.0,<3.1.0`

## 开发环境设置

### 1. 安装 uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 创建虚拟环境
```bash
cd /path/to/hil-mcp
uv venv .venv
```

### 3. 安装依赖
```bash
# 标准依赖 (PyPI)
uv pip install -r requirements.txt

# 或安装 fly-pigeon (腾讯内部包)
uv pip install \
  --index-url https://pypi.org/simple \
  --extra-index-url http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple \
  fly-pigeon
```

### 4. 运行服务 (开发模式)
```bash
# JSON 配置模式 (默认)
.venv/bin/python -m forward_service.app

# 数据库配置模式
USE_DATABASE=true .venv/bin/python -m forward_service.app
```

## 生产环境部署 (dev 服务器)

### 服务器信息
- **地址**: dev (通过 SSH 访问)
- **工作目录**: `/root/projects/hil-mcp`
- **Python**: 由 uv 管理的 3.10+ 版本
- **Git 仓库**: `git@git.woa.com:kongjie/tmp.git`

### 部署流程

#### 方式一: Git Pull (推荐)

```bash
# 1. SSH 登录服务器
ssh dev

# 2. 进入项目目录
cd /root/projects/hil-mcp

# 3. 拉取最新代码
git pull origin main

# 4. 如果有新依赖,同步安装
uv sync

# 5. 重启需要更新的服务
sudo systemctl restart hil-forward
# 或其他服务: hil-worker, hil-server-direct
```

#### 方式二: Rsync (应急使用)

```bash
# 仅同步特定文件到服务器
rsync -avz forward_service/*.py dev:/root/projects/hil-mcp/forward_service/

# 然后重启服务
ssh dev "sudo systemctl restart hil-forward"
```

### 服务管理

#### Systemd 服务配置

**Forward Service** (`/etc/systemd/system/hil-forward.service`):
```ini
[Unit]
Description=HIL-MCP Forward Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/projects/hil-mcp
Environment="PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="FORWARD_TIMEOUT=1800"
Environment="USE_DATABASE=true"
ExecStart=/root/projects/hil-mcp/.venv/bin/python -m forward_service.app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**服务操作命令**:
```bash
# 启动服务
sudo systemctl start hil-forward

# 停止服务
sudo systemctl stop hil-forward

# 重启服务
sudo systemctl restart hil-forward

# 查看服务状态
sudo systemctl status hil-forward

# 查看实时日志
sudo journalctl -u hil-forward -f

# 查看最近 100 行日志
sudo journalctl -u hil-forward -n 100
```

#### 检查服务健康

```bash
# 检查所有服务状态
sudo systemctl status hil-forward hil-worker hil-server-direct

# 检查端口占用
sudo netstat -tlnp | grep python

# 检查进程
ps aux | grep "forward_service\|hil-worker\|hil-server"
```

## 数据库模式部署

### 数据库支持

Forward Service 现在支持两种配置存储方式:

1. **JSON 文件** (默认) - `data/forward_bots.json`
2. **数据库** (SQLite 或 MySQL) - 通过 `USE_DATABASE=true` 启用

### 环境变量

```bash
# 启用数据库模式
export USE_DATABASE=true

# 数据库 URL (可选,默认使用 SQLite)
export DATABASE_URL="sqlite+aiosqlite:///./data/forward_service.db"
# 或使用 MySQL:
# export DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/forward_service"

# 默认 Bot Key
export DEFAULT_BOT_KEY="your_default_bot_key"

# 服务配置
export FORWARD_PORT="8083"
export FORWARD_TIMEOUT="60"
```

### 数据迁移

从 JSON 配置迁移到数据库:

```bash
# 1. 试运行 (不实际写入数据库)
python migrate_to_database.py --dry-run

# 2. 实际迁移
python migrate_to_database.py

# 3. 强制覆盖已存在的记录
python migrate_to_database.py --force
```

**迁移脚本输出示例**:
```
============================================================
开始迁移配置到数据库...
源文件: data/forward_bots.json
数据库: sqlite+aiosqlite:///./data/forward_service.db
============================================================

✅ 创建: 18c6cb5d-611c-4829-ad86-e5b9d46729c0
   名称: 测试 Bot
   白名单: 1 条

✅ 创建: 21b6cb5d-611c-4829-ad86-e5b9d46729c1
   名称: 开发 Bot
   黑名单: 1 条

============================================================
迁移完成:
  创建: 2
  更新: 0
  跳过: 0
============================================================
```

### 验证数据库模式

```bash
# 检查服务日志
sudo journalctl -u hil-forward -n 50 | grep "数据库模式"

# 应该看到类似输出:
# ✅ 使用数据库配置 (USE_DATABASE=true)
# ✅ 数据库连接: sqlite+aiosqlite:///./data/forward_service.db
# ✅ 从数据库加载了 6 个 Bot 配置
```

## 常见部署问题及解决方案

### 问题 1: fly-pigeon 包找不到

**错误信息**:
```
Because fly-pigeon was not found in the package registry
```

**原因**: fly-pigeon 是腾讯内部包,不在 PyPI 上

**解决方案**:
```bash
# 方案 1: 使用镜像源安装
uv pip install \
  --index-url https://pypi.org/simple \
  --extra-index-url http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple \
  fly-pigeon

# 方案 2: 使用 requirements.txt (已配置镜像源)
uv pip install -r requirements.txt

# 方案 3: 修改 .uvrc 配置文件 (已配置)
extra-index-url = ["http://mirrors.tencent.com/repository/pypi/tencent_pypi/simple"]
```

### 问题 2: greenlet 编译失败

**错误信息**:
```
greenlet 3.3.0: compilation failed with C++ errors
```

**原因**: greenlet 3.3.0 在某些系统上编译失败

**解决方案**: 在 `pyproject.toml` 中锁定版本
```toml
"greenlet>=3.0.0,<3.1.0",
```

然后重新安装:
```bash
uv sync
```

### 问题 3: Python 版本不匹配

**错误信息**:
```
ImportError: cannot import name 'Literal' from 'typing'
```

**原因**: 代码使用了 Python 3.10+ 特性,但运行在 Python 3.7

**解决方案**:
1. 确认 Python 版本: `python --version`
2. 使用 uv 管理: `uv venv .venv --python 3.10`
3. 或使用 `typing_extensions` 兼容 (已在代码中处理)

### 问题 4: 服务启动失败

**检查步骤**:
```bash
# 1. 检查服务状态
sudo systemctl status hil-forward

# 2. 查看详细日志
sudo journalctl -u hil-forward -n 100 --no-pager

# 3. 手动运行测试
cd /root/projects/hil-mcp
USE_DATABASE=true .venv/bin/python -m forward_service.app

# 4. 检查端口占用
sudo netstat -tlnp | grep 8083
```

**常见原因**:
- 端口被占用 → 修改 `FORWARD_PORT` 或停止占用进程
- 依赖缺失 → 运行 `uv sync`
- 数据库未初始化 → 运行 `migrate_to_database.py`
- 配置文件错误 → 检查 JSON 格式或数据库连接

### 问题 5: 数据库模式未启用

**症状**: 服务日志显示 "使用 JSON 文件配置"

**解决方案**:
```bash
# 1. 检查环境变量
sudo systemctl show hil-forward | grep USE_DATABASE

# 2. 修改 systemd 配置
sudo vim /etc/systemd/system/hil-forward.service
# 添加: Environment="USE_DATABASE=true"

# 3. 重新加载并重启
sudo systemctl daemon-reload
sudo systemctl restart hil-forward
```

### 问题 6: Git Pull 失败

**错误信息**:
```
fatal: unable to access 'https://github.com/...': Failed to connect
```

**解决方案**:
```bash
# 1. 检查远程仓库
git remote -v

# 2. 如果使用 SSH,检查密钥
ssh -T git@git.woa.com

# 3. 如果需要添加远程仓库
git remote add origin git@git.woa.com:kongjie/tmp.git

# 4. 拉取前先暂存本地更改
git stash save "Auto stash before pull"
git pull origin main
```

## 项目文件结构

```
hil-mcp/
├── forward_service/
│   ├── app.py              # FastAPI 应用 (支持 USE_DATABASE)
│   ├── config_v2.py        # JSON 配置类
│   ├── config_db.py        # 数据库配置类
│   ├── database.py         # 数据库连接管理
│   ├── models.py           # SQLAlchemy ORM 模型
│   ├── repository.py       # 数据访问层 (DAO)
│   └── sender.py           # 消息发送
├── tests/
│   ├── test_database.py    # 数据库单元测试 (21 个测试,全部通过)
│   └── test_db_integration.py  # 数据库集成测试
├── data/
│   ├── forward_bots.json   # JSON 配置文件 (可选)
│   └── forward_service.db  # SQLite 数据库 (如果使用数据库模式)
├── migrate_to_database.py  # 数据迁移工具
├── requirements.txt        # 项目依赖
├── pyproject.toml          # 项目配置
├── .uvrc                  # uv 配置 (腾讯镜像源)
└── CLAUDE.md              # 本文档
```

## 数据库表结构

### chatbots 表
```sql
CREATE TABLE chatbots (
    id INTEGER PRIMARY KEY,
    bot_key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    url_template VARCHAR(500) NOT NULL,
    agent_id VARCHAR(100),
    api_key VARCHAR(200),
    timeout INTEGER NOT NULL DEFAULT 60,
    access_mode VARCHAR(20) NOT NULL DEFAULT 'allow_all',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

### chat_access_rules 表
```sql
CREATE TABLE chat_access_rules (
    id INTEGER PRIMARY KEY,
    chatbot_id INTEGER NOT NULL,
    chat_id VARCHAR(200) NOT NULL,
    rule_type VARCHAR(20) NOT NULL,  -- 'whitelist' or 'blacklist'
    remark VARCHAR(500),
    created_at DATETIME NOT NULL,
    FOREIGN KEY (chatbot_id) REFERENCES chatbots(id) ON DELETE CASCADE,
    UNIQUE (chatbot_id, chat_id, rule_type)
);
```

## API 端点

### 管理 API
- `GET /admin/config` - 获取配置
- `PUT /admin/config` - 更新配置 (数据库模式下异步)
- `POST /admin/config/reload` - 重新加载配置 (数据库模式下异步)
- `GET /admin/rules` - 获取所有 Bot
- `GET /health` - 健康检查

### 使用示例
```bash
# 获取配置
curl http://localhost:8083/admin/config

# 更新配置
curl -X PUT http://localhost:8083/admin/config \
  -H "Content-Type: application/json" \
  -d '{
    "default_bot_key": "bot1",
    "bots": {
      "bot1": {
        "bot_key": "bot1",
        "name": "测试 Bot",
        "forward_config": {
          "url_template": "https://api.com"
        },
        "enabled": true
      }
    }
  }'
```

## 回滚方案

### 回退到 JSON 配置

如果数据库模式出现问题,可以快速回退:

```bash
# 1. 修改 systemd 配置
sudo vim /etc/systemd/system/hil-forward.service
# 删除或注释: Environment="USE_DATABASE=true"

# 2. 重新加载并重启
sudo systemctl daemon-reload
sudo systemctl restart hil-forward

# 3. 验证
sudo journalctl -u hil-forward -n 20 | grep "JSON 文件配置"
```

### 回退代码版本

```bash
# 查看提交历史
git log --oneline -10

# 回退到指定版本
git reset --hard <commit-hash>

# 或使用 git revert (保留历史)
git revert <commit-hash>
```

## 监控和日志

### 日志位置
- **Systemd 日志**: `journalctl -u hil-forward`
- **应用日志**: 配置中未指定,默认输出到 stdout

### 常用监控命令

```bash
# 实时日志
sudo journalctl -u hil-forward -f

# 最近 1 小时日志
sudo journalctl -u hil-forward --since "1 hour ago"

# 按时间过滤
sudo journalctl -u hil-forward --since "2025-01-07 10:00:00"

# 查找关键字
sudo journalctl -u hil-forward | grep "ERROR"

# 统计请求数
sudo journalctl -u hil-forward | grep "POST /forward" | wc -l
```

## 开发和调试

### 本地运行数据库模式

```bash
# 1. 迁移数据
python migrate_to_database.py

# 2. 启用数据库模式
export USE_DATABASE=true
python -m forward_service.app

# 3. 测试 API
curl http://localhost:8083/admin/config
```

### 运行单元测试

```bash
# 所有测试
python -m pytest tests/test_database.py -v

# 特定测试
python -m pytest tests/test_database.py::TestChatbotRepository::test_create_bot -v

# 查看覆盖率
python -m pytest tests/test_database.py --cov=forward_service
```

### 数据库调试

```bash
# 启用 SQL 日志
export DATABASE_ECHO="true"
USE_DATABASE=true python -m forward_service.app

# 查看数据库内容
sqlite3 data/forward_service.db
> .tables
> SELECT * FROM chatbots;
> .quit
```

## 未来改进

### 待实现功能
- [ ] 管理台前端适配数据库模式
- [ ] 数据库性能监控
- [ ] 数据库备份策略
- [ ] MySQL 生产环境部署
- [ ] 数据库迁移回滚工具
- [ ] 配置版本管理

### 性能优化
- [ ] 数据库连接池调优
- [ ] 查询缓存
- [ ] 异步批量操作
- [ ] 数据库索引优化

## 联系方式

- **开发者**: Kong Jie (jeffkit)
- **Email**: bbmyth@gmail.com
- **GitHub**: https://github.com/jeffkit
- **仓库**: https://git.woa.com/kongjie/tmp.git

## 更新日志

### 2025-01-07
- ✅ 完成数据库模式实现
- ✅ 部署到 dev 服务器
- ✅ 配置 Git 远程仓库
- ✅ 编写部署文档
- ✅ 所有单元测试通过 (21/21)
- ✅ 成功迁移 6 个 Bot 配置

### 相关文档
- **DATABASE_SUMMARY.md** - 数据库实现总结
- **DATABASE_MIGRATION.md** - 数据迁移详细指南
