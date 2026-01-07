"""
Forward Service 配置管理 - 数据库版本

与 config_v2.py 接口完全兼容,但使用数据库存储而不是 JSON 文件。

主要差异:
- 配置存储在数据库中,而不是 JSON 文件
- 支持动态更新,无需重启服务
- 与 config_v2.py 接口兼容,可以无缝切换

使用方式:
    # 使用数据库配置
    from forward_service.config_db import ConfigDB
    config = ConfigDB()
"""
import logging
import re
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .database import get_db_manager
from .models import Chatbot
from .repository import get_chatbot_repository, get_access_rule_repository

logger = logging.getLogger(__name__)


# ============== 数据类定义 (与 config_v2 兼容) ==============

class ForwardConfig:
    """转发配置 (与 config_v2.ForwardConfig 兼容)"""
    def __init__(
        self,
        url_template: str,
        agent_id: str = "",
        api_key: str = "",
        timeout: int = 60
    ):
        self.url_template = url_template
        self.agent_id = agent_id
        self.api_key = api_key
        self.timeout = timeout

    def to_dict(self) -> dict:
        return {
            "url_template": self.url_template,
            "agent_id": self.agent_id,
            "api_key": self.api_key,
            "timeout": self.timeout
        }

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "ForwardConfig":
        """从 Chatbot 模型创建 ForwardConfig"""
        return cls(
            url_template=bot.url_template,
            agent_id=bot.agent_id or "",
            api_key=bot.api_key or "",
            timeout=bot.timeout
        )

    def get_url(self) -> str:
        """获取完整 URL（替换占位符）"""
        return self.url_template.replace("{agent_id}", self.agent_id)


class AccessControl:
    """访问控制配置 (与 config_v2.AccessControl 兼容)"""
    def __init__(
        self,
        mode: str = "allow_all",
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None
    ):
        self.mode = mode
        self.whitelist = whitelist or []
        self.blacklist = blacklist or []

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "whitelist": self.whitelist,
            "blacklist": self.blacklist
        }

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "AccessControl":
        """从 Chatbot 模型创建 AccessControl (需要预加载 access_rules)"""
        whitelist = []
        blacklist = []

        for rule in bot.access_rules:
            if rule.rule_type == "whitelist":
                whitelist.append(rule.chat_id)
            elif rule.rule_type == "blacklist":
                blacklist.append(rule.chat_id)

        return cls(
            mode=bot.access_mode,
            whitelist=whitelist,
            blacklist=blacklist
        )

    def check_access(self, user_id: str) -> tuple[bool, str]:
        """检查用户是否有权限访问"""
        if self.mode == "allow_all":
            return True, ""

        elif self.mode == "whitelist":
            if user_id in self.whitelist:
                return True, ""
            return False, "您不在白名单中，无权访问此 Bot"

        elif self.mode == "blacklist":
            if user_id in self.blacklist:
                return False, "您已被加入黑名单，无法访问此 Bot"
            return True, ""

        return False, "未知的访问控制模式"


class BotConfig:
    """Bot 配置 (与 config_v2.BotConfig 兼容)"""
    def __init__(
        self,
        bot_key: str,
        name: str = "未命名 Bot",
        description: str = "",
        forward_config: ForwardConfig | None = None,
        access_control: AccessControl | None = None,
        enabled: bool = True,
        _bot: Chatbot | None = None  # 内部使用,保留对数据库模型的引用
    ):
        self.bot_key = bot_key
        self.name = name
        self.description = description
        self.forward_config = forward_config or ForwardConfig(url_template="")
        self.access_control = access_control or AccessControl()
        self.enabled = enabled
        self._bot = _bot  # 保留数据库模型引用

    def to_dict(self) -> dict:
        return {
            "bot_key": self.bot_key,
            "name": self.name,
            "description": self.description,
            "forward_config": self.forward_config.to_dict(),
            "access_control": self.access_control.to_dict(),
            "enabled": self.enabled
        }

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "BotConfig":
        """从 Chatbot 数据库模型创建 BotConfig"""
        return cls(
            bot_key=bot.bot_key,
            name=bot.name,
            description=bot.description or "",
            forward_config=ForwardConfig.from_bot(bot),
            access_control=AccessControl.from_bot(bot),
            enabled=bot.enabled,
            _bot=bot  # 保留数据库模型引用
        )


# ============== 数据库配置类 ==============

class ConfigDB:
    """
    数据库配置类 (与 ConfigV2 接口兼容)

    从数据库加载配置,而不是 JSON 文件。

    环境变量:
        DATABASE_URL: 数据库连接 URL
        DEFAULT_BOT_KEY: 默认 Bot Key
    """

    def __init__(self):
        """初始化配置"""
        self.default_bot_key: str = ""
        self.bots: dict[str, BotConfig] = {}
        self.port: int = 8083
        self.timeout: int = 60
        self.callback_auth_key: str = ""
        self.callback_auth_value: str = ""

    async def initialize(self):
        """初始化配置 - 从数据库加载"""
        import os

        # 从环境变量加载基本配置
        if os.getenv("FORWARD_PORT"):
            self.port = int(os.getenv("FORWARD_PORT"))
        if os.getenv("FORWARD_TIMEOUT"):
            self.timeout = int(os.getenv("FORWARD_TIMEOUT"))
        self.callback_auth_key = os.getenv("CALLBACK_AUTH_KEY", "")
        self.callback_auth_value = os.getenv("CALLBACK_AUTH_VALUE", "")

        # 设置默认 bot_key
        self.default_bot_key = os.getenv("DEFAULT_BOT_KEY", "")

        # 从数据库加载所有 Bot 配置
        await self._load_bots_from_db()

        logger.info(f"从数据库加载了 {len(self.bots)} 个 Bot 配置")
        logger.info(f"默认 Bot Key: {self.default_bot_key}")

    async def _load_bots_from_db(self):
        """从数据库加载所有 Bot 配置"""
        db = get_db_manager()

        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)

            # 获取所有 Bot (包括已禁用的)
            bots = await bot_repo.get_all(enabled_only=False)

            # 转换为 BotConfig 对象
            for bot in bots:
                # 预加载 access_rules
                await session.refresh(bot, attribute_names=["access_rules"])

                bot_config = BotConfig.from_bot(bot)
                self.bots[bot.bot_key] = bot_config

                # 设置默认 bot_key (如果还没设置)
                if not self.default_bot_key and bot.enabled:
                    self.default_bot_key = bot.bot_key

    def extract_bot_key_from_webhook_url(self, webhook_url: str) -> Optional[str]:
        """从 webhook_url 提取 bot_key"""
        match = re.search(r'[?&]key=([^&]+)', webhook_url)
        if match:
            return match.group(1)
        return None

    def get_bot(self, bot_key: str) -> Optional[BotConfig]:
        """根据 bot_key 获取 Bot 配置"""
        return self.bots.get(bot_key)

    def get_bot_or_default(self, bot_key: str | None) -> Optional[BotConfig]:
        """获取 Bot 配置，如果找不到则返回默认 Bot"""
        if bot_key and bot_key in self.bots:
            return self.bots[bot_key]

        # 回退到默认 Bot
        if self.default_bot_key and self.default_bot_key in self.bots:
            logger.info(f"Bot {bot_key} 不存在，使用默认 Bot: {self.default_bot_key}")
            return self.bots[self.default_bot_key]

        return None

    def check_access(self, bot: BotConfig, user_id: str) -> tuple[bool, str]:
        """检查用户是否有权限访问 Bot"""
        if not bot.enabled:
            return False, "Bot 已禁用"

        return bot.access_control.check_access(user_id)

    async def reload_config(self) -> dict:
        """重新加载配置 (从数据库)"""
        try:
            self.bots.clear()
            await self._load_bots_from_db()
            return {"success": True, "message": "配置已重新加载"}
        except Exception as e:
            logger.error(f"重新加载配置失败: {e}")
            return {"success": False, "error": str(e)}

    def get_all_bots(self) -> dict[str, dict]:
        """获取所有 Bot 配置（用于管理台）"""
        return {
            bot_key: bot.to_dict()
            for bot_key, bot in self.bots.items()
        }

    def get_config_dict(self) -> dict:
        """获取完整配置（JSON 格式）"""
        return {
            "default_bot_key": self.default_bot_key,
            "bots": self.get_all_bots()
        }

    async def update_from_dict(self, data: dict) -> dict:
        """
        从字典更新配置 (写入数据库)

        注意: 这是全量更新,会覆盖现有配置
        """
        try:
            # 验证格式
            if "default_bot_key" not in data or "bots" not in data:
                return {"success": False, "error": "配置格式错误：缺少 default_bot_key 或 bots"}

            db = get_db_manager()

            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)
                rule_repo = get_access_rule_repository(session)

                # 更新默认 bot_key
                self.default_bot_key = data["default_bot_key"]

                # 获取数据库中现有的所有 Bot
                existing_bots = await bot_repo.get_all(enabled_only=False)
                existing_bot_keys = {bot.bot_key for bot in existing_bots}
                new_bot_keys = set(data["bots"].keys())

                # 删除不再存在的 Bot
                bot_keys_to_delete = existing_bot_keys - new_bot_keys
                for bot_key in bot_keys_to_delete:
                    bot = await bot_repo.get_by_bot_key(bot_key)
                    if bot:
                        await bot_repo.delete(bot.id)
                        logger.info(f"删除 Bot: {bot_key}")

                # 更新或创建 Bot
                for bot_key, bot_dict in data["bots"].items():
                    forward_config = bot_dict.get("forward_config", {})
                    access_control = bot_dict.get("access_control", {})

                    # 检查是否已存在
                    existing_bot = await bot_repo.get_by_bot_key(bot_key)

                    if existing_bot:
                        # 更新现有 Bot
                        await bot_repo.update(
                            bot_id=existing_bot.id,
                            name=bot_dict.get("name"),
                            description=bot_dict.get("description"),
                            url_template=forward_config.get("url_template"),
                            agent_id=forward_config.get("agent_id"),
                            api_key=forward_config.get("api_key"),
                            timeout=forward_config.get("timeout"),
                            access_mode=access_control.get("mode", "allow_all"),
                            enabled=bot_dict.get("enabled", True)
                        )

                        # 更新访问规则
                        whitelist = access_control.get("whitelist", [])
                        blacklist = access_control.get("blacklist", [])

                        if whitelist or blacklist:
                            # 清除旧规则并设置新规则
                            await rule_repo.delete_by_chatbot(existing_bot.id)

                            for chat_id in whitelist:
                                await rule_repo.create(existing_bot.id, chat_id, "whitelist")

                            for chat_id in blacklist:
                                await rule_repo.create(existing_bot.id, chat_id, "blacklist")

                        logger.info(f"更新 Bot: {bot_key}")
                    else:
                        # 创建新 Bot
                        bot = await bot_repo.create(
                            bot_key=bot_key,
                            name=bot_dict.get("name"),
                            description=bot_dict.get("description"),
                            url_template=forward_config.get("url_template"),
                            agent_id=forward_config.get("agent_id"),
                            api_key=forward_config.get("api_key"),
                            timeout=forward_config.get("timeout", 60),
                            access_mode=access_control.get("mode", "allow_all"),
                            enabled=bot_dict.get("enabled", True)
                        )

                        # 添加访问规则
                        whitelist = access_control.get("whitelist", [])
                        blacklist = access_control.get("blacklist", [])

                        for chat_id in whitelist:
                            await rule_repo.create(bot.id, chat_id, "whitelist")

                        for chat_id in blacklist:
                            await rule_repo.create(bot.id, chat_id, "blacklist")

                        logger.info(f"创建 Bot: {bot_key}")

            # 重新加载配置到内存
            await self.reload_config()

            return {"success": True, "message": "配置已更新"}

        except Exception as e:
            logger.error(f"更新配置失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def validate(self) -> list[str]:
        """验证配置"""
        errors = []

        if not self.bots:
            errors.append("至少需要配置一个 Bot")

        if self.default_bot_key and self.default_bot_key not in self.bots:
            errors.append(f"默认 Bot Key '{self.default_bot_key}' 不存在于 bots 配置中")

        for bot_key, bot in self.bots.items():
            if not bot.forward_config.url_template:
                errors.append(f"Bot '{bot_key}' 的 forward_config.url_template 未配置")

        return errors


# ============== 全局配置实例 ==============

config_db = ConfigDB()
