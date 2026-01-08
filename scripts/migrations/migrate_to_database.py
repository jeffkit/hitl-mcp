"""
数据库迁移工具

将现有的 JSON 配置文件迁移到数据库

功能:
1. 读取 data/forward_bots.json
2. 将配置写入数据库
3. 支持增量迁移 (跳过已存在的记录)

用法:
    python migrate_to_database.py [--force] [--dry-run]

    --force: 强制覆盖已存在的记录
    --dry-run: 仅显示将要执行的迁移，不实际写入数据库
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from forward_service.database import init_database, close_database, get_db_manager
from forward_service.repository import get_chatbot_repository, get_access_rule_repository
from forward_service.models import Chatbot, ChatAccessRule

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============== 配置文件路径 ==============

def get_config_file_path() -> str:
    """获取配置文件路径"""
    config_path = Path(__file__).parent / "data" / "forward_bots.json"
    return str(config_path)


# ============== JSON 配置读取 ==============

def load_json_config(config_file: str) -> dict:
    """
    加载 JSON 配置文件

    Args:
        config_file: 配置文件路径

    Returns:
        配置字典
    """
    if not Path(config_file).exists():
        logger.error(f"配置文件不存在: {config_file}")
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"已加载配置文件: {config_file}")
    return data


# ============== 迁移逻辑 ==============

async def migrate_bot_config(
    session,
    bot_key: str,
    bot_data: dict,
    force: bool = False,
    dry_run: bool = False
) -> Chatbot | None:
    """
    迁移单个 Bot 配置

    Args:
        session: 数据库 Session
        bot_key: Bot Key
        bot_data: Bot 配置数据
        force: 是否强制覆盖已存在的记录
        dry_run: 是否为试运行

    Returns:
        创建或更新的 Chatbot 对象
    """
    bot_repo = get_chatbot_repository(session)
    rule_repo = get_access_rule_repository(session)

    # 检查是否已存在
    existing_bot = await bot_repo.get_by_bot_key(bot_key)

    if existing_bot and not force:
        logger.info(f"  跳过已存在的 Bot: {bot_key} (使用 --force 强制覆盖)")
        return existing_bot

    # 提取配置数据
    forward_config = bot_data.get("forward_config", {})
    access_control = bot_data.get("access_control", {})

    # 创建或更新 Bot
    if existing_bot:
        logger.info(f"  更新 Bot: {bot_key} - {bot_data.get('name')}")
        if not dry_run:
            bot = await bot_repo.update(
                bot_id=existing_bot.id,
                name=bot_data.get("name"),
                description=bot_data.get("description"),
                url_template=forward_config.get("url_template"),
                agent_id=forward_config.get("agent_id"),
                api_key=forward_config.get("api_key"),
                timeout=forward_config.get("timeout"),
                access_mode=access_control.get("mode", "allow_all"),
                enabled=bot_data.get("enabled", True)
            )
        else:
            bot = existing_bot
    else:
        logger.info(f"  创建 Bot: {bot_key} - {bot_data.get('name')}")
        if not dry_run:
            bot = await bot_repo.create(
                bot_key=bot_key,
                name=bot_data.get("name"),
                description=bot_data.get("description"),
                url_template=forward_config.get("url_template"),
                agent_id=forward_config.get("agent_id"),
                api_key=forward_config.get("api_key"),
                timeout=forward_config.get("timeout", 60),
                access_mode=access_control.get("mode", "allow_all"),
                enabled=bot_data.get("enabled", True)
            )
        else:
            bot = None

    # 迁移访问规则 (白名单/黑名单)
    if bot:
        await migrate_access_rules(rule_repo, bot.id, access_control, force, dry_run)

    return bot


async def migrate_access_rules(
    rule_repo,
    chatbot_id: int,
    access_control: dict,
    force: bool = False,
    dry_run: bool = False
):
    """
    迁移访问控制规则

    Args:
        rule_repo: AccessRule Repository
        chatbot_id: Bot ID
        access_control: 访问控制配置
        force: 是否强制覆盖
        dry_run: 是否为试运行
    """
    mode = access_control.get("mode", "allow_all")
    whitelist = access_control.get("whitelist", [])
    blacklist = access_control.get("blacklist", [])

    # 如果强制更新，先清除现有规则
    if force:
        if not dry_run:
            await rule_repo.delete_by_chatbot(chatbot_id)
        logger.info(f"    清除现有访问规则 (force mode)")

    # 迁移白名单
    if whitelist:
        logger.info(f"    迁移白名单: {len(whitelist)} 条")
        if not dry_run:
            for chat_id in whitelist:
                try:
                    await rule_repo.create(chatbot_id, chat_id, "whitelist")
                except Exception as e:
                    logger.warning(f"      跳过重复白名单: {chat_id}")

    # 迁移黑名单
    if blacklist:
        logger.info(f"    迁移黑名单: {len(blacklist)} 条")
        if not dry_run:
            for chat_id in blacklist:
                try:
                    await rule_repo.create(chatbot_id, chat_id, "blacklist")
                except Exception as e:
                    logger.warning(f"      跳过重复黑名单: {chat_id}")


async def migrate_all(
    config_file: str,
    force: bool = False,
    dry_run: bool = False
):
    """
    迁移所有配置

    Args:
        config_file: 配置文件路径
        force: 是否强制覆盖
        dry_run: 是否为试运行
    """
    logger.info("=" * 60)
    logger.info("开始迁移配置到数据库")
    logger.info("=" * 60)

    if dry_run:
        logger.info("【试运行模式】不会实际写入数据库")
    if force:
        logger.info("【强制模式】会覆盖已存在的记录")

    # 加载 JSON 配置
    config_data = load_json_config(config_file)

    default_bot_key = config_data.get("default_bot_key", "")
    bots_data = config_data.get("bots", {})

    logger.info(f"默认 Bot Key: {default_bot_key}")
    logger.info(f"Bot 数量: {len(bots_data)}")

    # 获取数据库 Session
    db = get_db_manager()

    async with db.get_session() as session:
        # 统计
        created_count = 0
        updated_count = 0
        skipped_count = 0

        # 迁移每个 Bot
        for bot_key, bot_data in bots_data.items():
            bot_repo = get_chatbot_repository(session)

            # 检查是否已存在
            existing_bot = await bot_repo.get_by_bot_key(bot_key)

            if existing_bot and not force:
                skipped_count += 1
            elif existing_bot and force:
                updated_count += 1
            else:
                created_count += 1

            # 执行迁移
            await migrate_bot_config(
                session,
                bot_key,
                bot_data,
                force=force,
                dry_run=dry_run
            )

    # 输出统计
    logger.info("=" * 60)
    logger.info("迁移完成:")
    logger.info(f"  创建: {created_count}")
    logger.info(f"  更新: {updated_count}")
    logger.info(f"  跳过: {skipped_count}")
    logger.info("=" * 60)


# ============== 主函数 ==============

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="迁移 JSON 配置到数据库")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已存在的记录"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行，不实际写入数据库"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=get_config_file_path(),
        help=f"配置文件路径 (默认: {get_config_file_path()})"
    )

    args = parser.parse_args()

    # 检查配置文件
    if not Path(args.config).exists():
        logger.error(f"配置文件不存在: {args.config}")
        sys.exit(1)

    # 初始化数据库 (试运行时也初始化，以便验证)
    echo = args.dry_run  # 试运行时打印 SQL
    await init_database(echo=echo)

    try:
        # 执行迁移
        await migrate_all(
            config_file=args.config,
            force=args.force,
            dry_run=args.dry_run
        )
    finally:
        # 关闭数据库
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
