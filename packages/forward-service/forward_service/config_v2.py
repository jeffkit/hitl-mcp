"""
Forward Service 配置管理 V2 - 多 Bot 支持

支持多个 chatbot 同时接入，每个 bot 有独立的配置和访问控制。

配置文件格式（data/forward_bots.json）:
{
    "default_bot_key": "default_webhook_key",
    "bots": {
        "default_webhook_key": {
            "bot_key": "default_webhook_key",
            "name": "默认机器人",
            "description": "兜底机器人",
            "forward_config": {
                "url_template": "https://api.com/handle",
                "agent_id": "",
                "api_key": "",
                "timeout": 60
            },
            "access_control": {
                "mode": "allow_all",  // allow_all | whitelist | blacklist
                "whitelist": [],
                "blacklist": []
            },
            "enabled": true
        },
        "another_webhook_key": {...}
    }
}
"""
import os
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


# 类型定义
AccessMode = Literal["allow_all", "whitelist", "blacklist"]


@dataclass
class ForwardConfig:
    """转发配置"""
    url_template: str
    agent_id: str = ""
    api_key: str = ""
    timeout: int = 60
    
    def to_dict(self) -> dict:
        return {
            "url_template": self.url_template,
            "agent_id": self.agent_id,
            "api_key": self.api_key,
            "timeout": self.timeout
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ForwardConfig":
        return cls(
            url_template=data.get("url_template", ""),
            agent_id=data.get("agent_id", ""),
            api_key=data.get("api_key", ""),
            timeout=data.get("timeout", 60)
        )
    
    def get_url(self) -> str:
        """获取完整 URL（替换占位符）"""
        return self.url_template.replace("{agent_id}", self.agent_id)


@dataclass
class AccessControl:
    """访问控制配置"""
    mode: AccessMode = "allow_all"
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "whitelist": self.whitelist,
            "blacklist": self.blacklist
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AccessControl":
        return cls(
            mode=data.get("mode", "allow_all"),
            whitelist=data.get("whitelist", []),
            blacklist=data.get("blacklist", [])
        )
    
    def check_access(self, user_id: str) -> tuple[bool, str]:
        """
        检查用户是否有权限访问
        
        Args:
            user_id: 用户 ID
        
        Returns:
            (allowed, reason) - allowed 为 True 表示允许访问
        """
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


@dataclass
class BotConfig:
    """Bot 配置"""
    bot_key: str
    name: str = "未命名 Bot"
    description: str = ""
    forward_config: ForwardConfig = field(default_factory=lambda: ForwardConfig(url_template=""))
    access_control: AccessControl = field(default_factory=AccessControl)
    enabled: bool = True
    
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
    def from_dict(cls, data: dict) -> "BotConfig":
        return cls(
            bot_key=data.get("bot_key", ""),
            name=data.get("name", "未命名 Bot"),
            description=data.get("description", ""),
            forward_config=ForwardConfig.from_dict(data.get("forward_config", {})),
            access_control=AccessControl.from_dict(data.get("access_control", {})),
            enabled=data.get("enabled", True)
        )


@dataclass
class ConfigV2:
    """配置类 V2 - 多 Bot 支持"""
    
    # 默认 bot key（兜底）
    default_bot_key: str = ""
    
    # bot_key -> BotConfig 映射
    bots: dict[str, BotConfig] = field(default_factory=dict)
    
    # 服务端口
    port: int = 8083
    
    # 全局超时时间（默认值）
    timeout: int = 60
    
    # 回调鉴权（可选）
    callback_auth_key: str = ""
    callback_auth_value: str = ""
    
    def __post_init__(self):
        """加载配置"""
        # 1. 从 data/forward_bots.json 加载 Bot 配置
        self._load_bots_config()
        
        # 2. 环境变量覆盖
        if os.getenv("FORWARD_PORT"):
            self.port = int(os.getenv("FORWARD_PORT"))
        if os.getenv("FORWARD_TIMEOUT"):
            self.timeout = int(os.getenv("FORWARD_TIMEOUT"))
        
        self.callback_auth_key = os.getenv("CALLBACK_AUTH_KEY", self.callback_auth_key)
        self.callback_auth_value = os.getenv("CALLBACK_AUTH_VALUE", self.callback_auth_value)
        
        # 3. 兼容性：如果还没有配置文件，尝试从旧配置迁移
        if not self.bots:
            logger.info("未找到 Bot 配置，尝试从旧配置迁移...")
            self._migrate_from_old_config()
    
    def _get_bots_config_path(self) -> str:
        """获取 Bots 配置文件路径"""
        return os.path.join(os.path.dirname(__file__), "..", "data", "forward_bots.json")
    
    def _load_bots_config(self):
        """加载 Bots 配置"""
        config_path = self._get_bots_config_path()
        
        if not os.path.exists(config_path):
            logger.info(f"Bot 配置文件不存在: {config_path}")
            return
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.default_bot_key = data.get("default_bot_key", "")
            
            bots_data = data.get("bots", {})
            for bot_key, bot_dict in bots_data.items():
                try:
                    self.bots[bot_key] = BotConfig.from_dict(bot_dict)
                except Exception as e:
                    logger.error(f"加载 bot {bot_key} 失败: {e}")
            
            logger.info(f"从 {config_path} 加载了 {len(self.bots)} 个 Bot 配置")
            logger.info(f"默认 Bot Key: {self.default_bot_key}")
        
        except Exception as e:
            logger.error(f"加载 Bot 配置文件失败: {e}")
    
    def _migrate_from_old_config(self):
        """从旧配置迁移到新配置"""
        try:
            # 从环境变量或旧配置文件读取
            old_bot_key = os.getenv("FORWARD_BOT_KEY", "")
            old_forward_url = os.getenv("FORWARD_URL", "")
            
            if not old_bot_key and not old_forward_url:
                logger.warning("无旧配置可迁移")
                return
            
            # 设置默认 bot_key
            if not old_bot_key:
                old_bot_key = "default_migrated_key"
            
            self.default_bot_key = old_bot_key
            
            # 创建默认 Bot
            default_bot = BotConfig(
                bot_key=old_bot_key,
                name="默认机器人（从旧配置迁移）",
                description="自动从旧配置迁移",
                forward_config=ForwardConfig(
                    url_template=old_forward_url
                ),
                access_control=AccessControl(mode="allow_all"),
                enabled=True
            )
            
            self.bots[old_bot_key] = default_bot
            
            logger.info(f"已从旧配置迁移：bot_key={old_bot_key}, url={old_forward_url}")
            
            # 保存迁移后的配置
            self.save_config()
            
        except Exception as e:
            logger.error(f"配置迁移失败: {e}")
    
    def save_config(self) -> dict:
        """保存配置到文件"""
        config_path = self._get_bots_config_path()
        
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            
            data = {
                "default_bot_key": self.default_bot_key,
                "bots": {
                    bot_key: bot.to_dict()
                    for bot_key, bot in self.bots.items()
                }
            }
            
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"配置已保存到 {config_path}")
            return {"success": True, "message": "配置已保存"}
        
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return {"success": False, "error": str(e)}
    
    def reload_config(self) -> dict:
        """重新加载配置"""
        try:
            self.bots.clear()
            self._load_bots_config()
            return {"success": True, "message": "配置已重新加载"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def extract_bot_key_from_webhook_url(self, webhook_url: str) -> str | None:
        """
        从 webhook_url 提取 bot_key
        
        Args:
            webhook_url: 例如 "http://...send?key=18c6cb5d-..."
        
        Returns:
            bot_key 或 None
        """
        match = re.search(r'[?&]key=([^&]+)', webhook_url)
        if match:
            return match.group(1)
        return None
    
    def get_bot(self, bot_key: str) -> BotConfig | None:
        """
        根据 bot_key 获取 Bot 配置
        
        Args:
            bot_key: Bot Key
        
        Returns:
            BotConfig 或 None
        """
        return self.bots.get(bot_key)
    
    def get_bot_or_default(self, bot_key: str | None) -> BotConfig | None:
        """
        获取 Bot 配置，如果找不到则返回默认 Bot
        
        Args:
            bot_key: Bot Key
        
        Returns:
            BotConfig 或 None
        """
        if bot_key and bot_key in self.bots:
            return self.bots[bot_key]
        
        # 回退到默认 Bot
        if self.default_bot_key and self.default_bot_key in self.bots:
            logger.info(f"Bot {bot_key} 不存在，使用默认 Bot: {self.default_bot_key}")
            return self.bots[self.default_bot_key]
        
        return None
    
    def check_access(self, bot: BotConfig, user_id: str) -> tuple[bool, str]:
        """
        检查用户是否有权限访问 Bot
        
        Args:
            bot: Bot 配置
            user_id: 用户 ID
        
        Returns:
            (allowed, reason)
        """
        if not bot.enabled:
            return False, "Bot 已禁用"
        
        return bot.access_control.check_access(user_id)
    
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
    
    def update_from_dict(self, data: dict) -> dict:
        """
        从字典更新配置
        
        Args:
            data: 配置数据
        
        Returns:
            操作结果
        """
        try:
            # 验证格式
            if "default_bot_key" not in data or "bots" not in data:
                return {"success": False, "error": "配置格式错误：缺少 default_bot_key 或 bots"}
            
            # 更新默认 bot_key
            self.default_bot_key = data["default_bot_key"]
            
            # 更新 bots
            new_bots = {}
            for bot_key, bot_dict in data["bots"].items():
                try:
                    new_bots[bot_key] = BotConfig.from_dict(bot_dict)
                except Exception as e:
                    return {"success": False, "error": f"解析 bot {bot_key} 失败: {e}"}
            
            self.bots = new_bots
            
            # 保存到文件
            save_result = self.save_config()
            if not save_result.get("success"):
                return save_result
            
            return {"success": True, "message": "配置已更新"}
        
        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return {"success": False, "error": str(e)}
    
    def validate(self) -> list[str]:
        """
        验证配置
        
        Returns:
            错误列表，空列表表示配置有效
        """
        errors = []
        
        if not self.bots:
            errors.append("至少需要配置一个 Bot")
        
        if self.default_bot_key and self.default_bot_key not in self.bots:
            errors.append(f"默认 Bot Key '{self.default_bot_key}' 不存在于 bots 配置中")
        
        for bot_key, bot in self.bots.items():
            if not bot.forward_config.url_template:
                errors.append(f"Bot '{bot_key}' 的 forward_config.url_template 未配置")
        
        return errors


# 全局配置实例
config_v2 = ConfigV2()
