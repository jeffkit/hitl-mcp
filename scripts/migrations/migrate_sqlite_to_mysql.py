#!/usr/bin/env python3
"""
SQLite 到 MySQL 数据迁移脚本

将 forward-service 的数据从 SQLite 迁移到 MySQL。

用法:
    python migrate_sqlite_to_mysql.py [--dry-run]

环境变量:
    SQLITE_PATH: SQLite 数据库路径 (默认: data/forward_service.db)
    MYSQL_URL: MySQL 连接 URL (默认: mysql+pymysql://hil:hil@mcp2026@9.134.37.237:3306/hil_mcp)
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../packages/forward-service'))

import aiosqlite
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from forward_service.models import Base, Chatbot, ChatAccessRule, ForwardLog, UserSession, SystemConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def migrate_chatbots(sqlite_db, mysql_session, dry_run: bool):
    """迁移 chatbots 表"""
    logger.info("迁移 chatbots 表...")
    
    cursor = await sqlite_db.execute("SELECT * FROM chatbots")
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    count = 0
    for row in rows:
        data = dict(zip(columns, row))
        
        # 处理时间字段
        for field in ['created_at', 'updated_at']:
            if data.get(field):
                try:
                    data[field] = datetime.fromisoformat(data[field].replace('Z', '+00:00'))
                except:
                    data[field] = datetime.now()
        
        # 处理布尔字段
        data['enabled'] = bool(data.get('enabled', 1))
        
        if dry_run:
            logger.info(f"  [DRY-RUN] 插入 chatbot: {data['name']} ({data['bot_key'][:8]}...)")
        else:
            bot = Chatbot(**data)
            mysql_session.add(bot)
            count += 1
    
    if not dry_run:
        await mysql_session.commit()
        
    logger.info(f"  迁移 {count} 条 chatbots 记录")
    return count


async def migrate_chat_access_rules(sqlite_db, mysql_session, dry_run: bool):
    """迁移 chat_access_rules 表"""
    logger.info("迁移 chat_access_rules 表...")
    
    cursor = await sqlite_db.execute("SELECT * FROM chat_access_rules")
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    count = 0
    for row in rows:
        data = dict(zip(columns, row))
        
        # 处理时间字段
        if data.get('created_at'):
            try:
                data['created_at'] = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
            except:
                data['created_at'] = datetime.now()
        
        if dry_run:
            logger.info(f"  [DRY-RUN] 插入 access_rule: chatbot_id={data['chatbot_id']}, chat_id={data['chat_id']}")
        else:
            rule = ChatAccessRule(**data)
            mysql_session.add(rule)
            count += 1
    
    if not dry_run:
        await mysql_session.commit()
        
    logger.info(f"  迁移 {count} 条 chat_access_rules 记录")
    return count


async def migrate_forward_logs(sqlite_db, mysql_session, dry_run: bool):
    """迁移 forward_logs 表"""
    logger.info("迁移 forward_logs 表...")
    
    cursor = await sqlite_db.execute("SELECT * FROM forward_logs")
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    count = 0
    for row in rows:
        data = dict(zip(columns, row))
        
        # 处理时间字段
        for field in ['created_at', 'responded_at']:
            if data.get(field):
                try:
                    data[field] = datetime.fromisoformat(data[field].replace('Z', '+00:00'))
                except:
                    if field == 'created_at':
                        data[field] = datetime.now()
                    else:
                        data[field] = None
        
        if dry_run:
            logger.info(f"  [DRY-RUN] 插入 forward_log: id={data['id']}")
        else:
            log = ForwardLog(**data)
            mysql_session.add(log)
            count += 1
    
    if not dry_run:
        await mysql_session.commit()
        
    logger.info(f"  迁移 {count} 条 forward_logs 记录")
    return count


async def migrate_user_sessions(sqlite_db, mysql_session, dry_run: bool):
    """迁移 user_sessions 表"""
    logger.info("迁移 user_sessions 表...")
    
    cursor = await sqlite_db.execute("SELECT * FROM user_sessions")
    rows = await cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    
    count = 0
    for row in rows:
        data = dict(zip(columns, row))
        
        # 处理时间字段
        for field in ['created_at', 'updated_at']:
            if data.get(field):
                try:
                    data[field] = datetime.fromisoformat(data[field].replace('Z', '+00:00'))
                except:
                    data[field] = datetime.now()
        
        # 处理布尔字段
        data['is_active'] = bool(data.get('is_active', 0))
        
        if dry_run:
            logger.info(f"  [DRY-RUN] 插入 user_session: short_id={data['short_id']}")
        else:
            session = UserSession(**data)
            mysql_session.add(session)
            count += 1
    
    if not dry_run:
        await mysql_session.commit()
        
    logger.info(f"  迁移 {count} 条 user_sessions 记录")
    return count


async def migrate_system_config(sqlite_db, mysql_session, dry_run: bool):
    """迁移 system_config 表"""
    logger.info("迁移 system_config 表...")
    
    try:
        cursor = await sqlite_db.execute("SELECT * FROM system_config")
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        
        count = 0
        for row in rows:
            data = dict(zip(columns, row))
            
            # 处理时间字段
            if data.get('updated_at'):
                try:
                    data['updated_at'] = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
                except:
                    data['updated_at'] = datetime.now()
            
            if dry_run:
                logger.info(f"  [DRY-RUN] 插入 system_config: key={data['key']}")
            else:
                config = SystemConfig(**data)
                mysql_session.add(config)
                count += 1
        
        if not dry_run:
            await mysql_session.commit()
            
        logger.info(f"  迁移 {count} 条 system_config 记录")
        return count
    except Exception as e:
        logger.warning(f"  跳过 system_config 表: {e}")
        return 0


async def main():
    parser = argparse.ArgumentParser(description='迁移 SQLite 数据到 MySQL')
    parser.add_argument('--dry-run', action='store_true', help='只显示将要执行的操作，不实际修改')
    parser.add_argument('--sqlite-path', default=None, help='SQLite 数据库路径')
    parser.add_argument('--mysql-url', default=None, help='MySQL 连接 URL')
    args = parser.parse_args()
    
    # 获取配置
    sqlite_path = args.sqlite_path or os.getenv(
        'SQLITE_PATH', 
        os.path.join(os.path.dirname(__file__), '../../packages/forward-service/data/forward_service.db')
    )
    mysql_url = args.mysql_url or os.getenv(
        'MYSQL_URL',
        'mysql+aiomysql://hil:hil%40mcp2026@9.134.37.237:3306/hil_mcp'  # 密码中的 @ 需要 URL 编码
    )
    
    logger.info("=" * 60)
    logger.info("SQLite 到 MySQL 数据迁移")
    logger.info("=" * 60)
    logger.info(f"SQLite 路径: {sqlite_path}")
    logger.info(f"MySQL URL: {mysql_url.replace('hil@mcp2026', '***')}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("=" * 60)
    
    # 检查 SQLite 文件是否存在
    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite 文件不存在: {sqlite_path}")
        sys.exit(1)
    
    # 创建 MySQL 引擎
    mysql_engine = create_async_engine(mysql_url, echo=False)
    
    # 创建表结构
    logger.info("创建 MySQL 表结构...")
    async with mysql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("  表结构创建完成")
    
    # 创建会话
    async_session = sessionmaker(mysql_engine, class_=AsyncSession, expire_on_commit=False)
    
    # 打开 SQLite 连接
    async with aiosqlite.connect(sqlite_path) as sqlite_db:
        async with async_session() as mysql_session:
            try:
                total = 0
                
                # 迁移各表
                total += await migrate_chatbots(sqlite_db, mysql_session, args.dry_run)
                total += await migrate_chat_access_rules(sqlite_db, mysql_session, args.dry_run)
                total += await migrate_forward_logs(sqlite_db, mysql_session, args.dry_run)
                total += await migrate_user_sessions(sqlite_db, mysql_session, args.dry_run)
                total += await migrate_system_config(sqlite_db, mysql_session, args.dry_run)
                
                logger.info("=" * 60)
                if args.dry_run:
                    logger.info(f"[DRY-RUN] 将迁移 {total} 条记录")
                else:
                    logger.info(f"成功迁移 {total} 条记录!")
                logger.info("=" * 60)
                
            except Exception as e:
                logger.error(f"迁移失败: {e}")
                await mysql_session.rollback()
                raise
    
    # 关闭引擎
    await mysql_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
