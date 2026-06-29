"""
空闲状态提示消息配置管理

支持：
1. JSON 配置文件存储
2. 全局默认配置
3. 按 chat_id 自定义配置
4. 热更新（每次读取时从文件加载）
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_FILE = Path(__file__).parent.parent / "data" / "idle_hint_config.json"

# 默认消息模板
DEFAULT_MESSAGE_TEMPLATE = """👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{chat_type}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {chat_type}
🕐 **时间**: {timestamp}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```"""


class IdleHintConfigManager:
    """空闲提示消息配置管理器"""
    
    def __init__(self, config_file: Path = DEFAULT_CONFIG_FILE):
        self.config_file = config_file
        self._ensure_config_dir()
        self._ensure_default_config()
    
    def _ensure_config_dir(self):
        """确保配置文件目录存在"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _ensure_default_config(self):
        """确保配置文件存在，如果不存在则创建默认配置"""
        if not self.config_file.exists():
            default_config = {
                "default": {
                    "template": DEFAULT_MESSAGE_TEMPLATE,
                    "enabled": True,
                    "updated_at": datetime.now().isoformat(),
                    "updated_by": "system"
                },
                "chat_configs": {},
                "version": "1.0"
            }
            self._save_config(default_config)
            logger.info(f"已创建默认配置文件: {self.config_file}")
    
    def _load_config(self) -> dict:
        """从文件加载配置（每次调用时重新读取，支持热更新）"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.debug(f"已加载配置文件: {self.config_file}")
                return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}", exc_info=True)
            # 返回默认配置
            return {
                "default": {
                    "template": DEFAULT_MESSAGE_TEMPLATE,
                    "enabled": True
                },
                "chat_configs": {}
            }
    
    def _save_config(self, config: dict):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存配置文件: {self.config_file}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}", exc_info=True)
            raise
    
    def get_message_template(self, chat_id: str) -> Optional[str]:
        """
        获取指定 chat_id 的消息模板
        
        优先级：
        1. chat_id 特定配置
        2. 全局默认配置
        
        Returns:
            消息模板字符串，如果禁用则返回 None
        """
        config = self._load_config()
        
        # 优先查找 chat_id 特定配置
        chat_configs = config.get("chat_configs", {})
        if chat_id in chat_configs:
            chat_config = chat_configs[chat_id]
            if not chat_config.get("enabled", True):
                logger.debug(f"Chat {chat_id} 的提示消息已禁用")
                return None
            template = chat_config.get("template")
            if template:
                logger.debug(f"使用 chat_id 特定配置: {chat_id}")
                return template
        
        # 使用全局默认配置
        default_config = config.get("default", {})
        if not default_config.get("enabled", True):
            logger.debug("全局提示消息已禁用")
            return None
        
        template = default_config.get("template", DEFAULT_MESSAGE_TEMPLATE)
        logger.debug(f"使用全局默认配置")
        return template
    
    def format_message(
        self,
        chat_id: str,
        user_name: str,
        chat_type: str,
        timestamp: Optional[str] = None
    ) -> Optional[str]:
        """
        获取并格式化消息模板
        
        Args:
            chat_id: Chat ID
            user_name: 用户名
            chat_type: 会话类型（"私聊" 或 "群聊"）
            timestamp: 时间戳，如果为 None 则自动生成
        
        Returns:
            格式化后的消息，如果禁用则返回 None
        """
        template = self.get_message_template(chat_id)
        if template is None:
            return None
        
        if timestamp is None:
            timestamp = datetime.now().strftime("%H:%M:%S")
        
        try:
            message = template.format(
                user_name=user_name,
                chat_id=chat_id,
                chat_type=chat_type,
                timestamp=timestamp
            )
            return message
        except KeyError as e:
            logger.error(f"消息模板格式化失败，缺少变量: {e}")
            # 返回默认模板
            return DEFAULT_MESSAGE_TEMPLATE.format(
                user_name=user_name,
                chat_id=chat_id,
                chat_type=chat_type,
                timestamp=timestamp
            )
        except Exception as e:
            logger.error(f"消息模板格式化失败: {e}", exc_info=True)
            return None
    
    def get_all_configs(self) -> dict:
        """获取所有配置（用于管理台）"""
        config = self._load_config()
        return {
            "default": config.get("default", {}),
            "chat_configs": config.get("chat_configs", {}),
            "version": config.get("version", "1.0"),
            "config_file": str(self.config_file)
        }
    
    def update_default_config(
        self,
        template: str,
        enabled: bool = True,
        updated_by: str = "admin"
    ) -> dict:
        """
        更新全局默认配置
        
        Args:
            template: 消息模板
            enabled: 是否启用
            updated_by: 更新者
        
        Returns:
            更新结果
        """
        config = self._load_config()
        
        config["default"] = {
            "template": template,
            "enabled": enabled,
            "updated_at": datetime.now().isoformat(),
            "updated_by": updated_by
        }
        
        self._save_config(config)
        logger.info(f"已更新全局默认配置: enabled={enabled}, updated_by={updated_by}")
        
        return {
            "success": True,
            "message": "全局默认配置已更新"
        }
    
    def update_chat_config(
        self,
        chat_id: str,
        template: str,
        enabled: bool = True,
        updated_by: str = "admin"
    ) -> dict:
        """
        更新指定 chat_id 的配置
        
        Args:
            chat_id: Chat ID
            template: 消息模板
            enabled: 是否启用
            updated_by: 更新者
        
        Returns:
            更新结果
        """
        config = self._load_config()
        
        if "chat_configs" not in config:
            config["chat_configs"] = {}
        
        config["chat_configs"][chat_id] = {
            "template": template,
            "enabled": enabled,
            "updated_at": datetime.now().isoformat(),
            "updated_by": updated_by
        }
        
        self._save_config(config)
        logger.info(f"已更新 chat_id 配置: {chat_id}, enabled={enabled}, updated_by={updated_by}")
        
        return {
            "success": True,
            "message": f"Chat {chat_id} 的配置已更新"
        }
    
    def delete_chat_config(self, chat_id: str) -> dict:
        """
        删除指定 chat_id 的配置（使用全局默认配置）
        
        Args:
            chat_id: Chat ID
        
        Returns:
            删除结果
        """
        config = self._load_config()
        
        chat_configs = config.get("chat_configs", {})
        if chat_id in chat_configs:
            del chat_configs[chat_id]
            config["chat_configs"] = chat_configs
            self._save_config(config)
            logger.info(f"已删除 chat_id 配置: {chat_id}")
            return {
                "success": True,
                "message": f"Chat {chat_id} 的配置已删除，将使用全局默认配置"
            }
        else:
            return {
                "success": False,
                "error": f"Chat {chat_id} 没有自定义配置"
            }


# 全局配置管理器实例
idle_hint_config = IdleHintConfigManager()
