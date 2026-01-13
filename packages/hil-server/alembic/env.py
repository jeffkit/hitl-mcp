"""Alembic 迁移环境配置

此文件由 Alembic 自动生成，用于配置迁移环境。

关键配置：
1. 从环境变量 HIL_DATABASE_URL 读取数据库连接
2. 导入项目模型 (hil_server.models)
3. 支持 async SQLAlchemy (SQLite/MySQL)
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# 将项目根目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from alembic import context
from hil_server.models import Base

# ============== Alembic Config ==============

config = context.config

# ============== 日志配置 ==============

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ============== 数据库 URL 配置 ==============

# 从环境变量读取 HIL_DATABASE_URL (优先级高于 alembic.ini)
database_url = os.getenv("HIL_DATABASE_URL")
if database_url:
    # 转换 async URL 为 sync URL (Alembic 需要同步引擎)
    # sqlite+aiosqlite:///... -> sqlite:///
    # mysql+aiomysql:///... -> mysql+pymysql:///
    if database_url.startswith("sqlite+aiosqlite"):
        sync_url = database_url.replace("sqlite+aiosqlite", "sqlite")
    elif database_url.startswith("mysql+aiomysql"):
        sync_url = database_url.replace("mysql+aiomysql", "mysql+pymysql")
    else:
        # 未知类型，保持原样
        sync_url = database_url

    # 转义 % 符号，避免 configparser 解析问题
    escaped_url = sync_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", escaped_url)
    print(f"[Alembic] 使用环境变量 HIL_DATABASE_URL: {sync_url[:50]}...")

# ============== 模型元数据 ==============

# 导入项目的模型元数据，用于 autogenerate
target_metadata = Base.metadata

# ============== 其他配置 ==============

# 其他自定义配置可以在这里添加
# my_important_option = config.get_main_option("my_important_option")


# ============== 迁移执行函数 ==============

def run_migrations_offline() -> None:
    """离线模式运行迁移

    此模式下不需要数据库连接，只生成 SQL 脚本。
    适用于生产环境需要审查 SQL 的情况。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 渲染项配置
        render_as_batch=True,  # SQLite 支持 ALTER TABLE
        version_table="hil_alembic_version",  # 使用独立的版本表
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移

    此模式下会连接数据库并执行迁移。
    """
    # 使用同步引擎创建迁移 (Alembic 不支持 async)
    configuration = config.get_section(config.config_ini_section, {})

    # SQLite 连接参数配置
    url = configuration.get("sqlalchemy.url", "")
    if url.startswith("sqlite"):
        configuration["sqlalchemy.connect_args"] = {"check_same_thread": False}

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 配置项
            render_as_batch=True,  # SQLite 支持 ALTER TABLE
            compare_type=True,  # 比较列类型
            compare_server_default=True,  # 比较默认值
            version_table="hil_alembic_version",  # 使用独立的版本表
        )

        with context.begin_transaction():
            context.run_migrations()


# ============== 入口点 ==============

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
