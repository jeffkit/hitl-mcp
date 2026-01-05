"""
Forward Service 配置管理

环境变量:
    FORWARD_BOT_KEY: 企微机器人 Webhook Key（必填）
    FORWARD_URL: 默认转发目标 URL（可选，兜底配置）
    FORWARD_RULES: JSON 格式的 chat_id 配置（支持复杂配置）
    FORWARD_PORT: 服务端口（默认 8083）
    FORWARD_TIMEOUT: 转发请求超时时间（默认 60 秒）

FORWARD_RULES 格式示例:
{
    "chat_id_1": {
        "url_template": "https://server/a2a/{agent_id}/messages",
        "agent_id": "agent-001",
        "api_key": "key-001",
        "name": "Agent 1"
    },
    "chat_id_2": "https://simple-url.com/api"  // 简单格式也支持
}
"""
import os
import json
import logging
from dataclasses import dataclass, field
from typing import TypedDict

logger = logging.getLogger(__name__)


# AgentConfig 使用 dict 类型，因为 TypedDict 在 Python 3.10 不支持 NotRequired
# 格式: {"url_template": "...", "agent_id": "...", "api_key": "...", "name": "..."}
# 其中只有 url_template 是必须的
AgentConfig = dict


@dataclass
class Config:
    """配置类"""
    
    # 企微机器人 Webhook Key
    bot_key: str = ""
    
    # 默认转发目标 URL（兜底）
    forward_url: str = ""
    
    # chat_id -> AgentConfig 映射
    # 支持两种格式：
    # 1. 简单格式: {"chat_id": "https://url"}
    # 2. 完整格式: {"chat_id": {"url_template": "...", "agent_id": "...", "api_key": "..."}}
    forward_rules: dict[str, str | AgentConfig] = field(default_factory=dict)
    
    # 服务端口
    port: int = 8083
    
    # 转发请求超时时间（秒）
    timeout: int = 60
    
    # 回调鉴权（可选）
    callback_auth_key: str = ""
    callback_auth_value: str = ""
    
    def __post_init__(self):
        """从环境变量加载配置"""
        self.bot_key = os.getenv("FORWARD_BOT_KEY", self.bot_key)
        self.forward_url = os.getenv("FORWARD_URL", self.forward_url)
        self.port = int(os.getenv("FORWARD_PORT", str(self.port)))
        self.timeout = int(os.getenv("FORWARD_TIMEOUT", str(self.timeout)))
        
        # 回调鉴权
        self.callback_auth_key = os.getenv("CALLBACK_AUTH_KEY", "")
        self.callback_auth_value = os.getenv("CALLBACK_AUTH_VALUE", "")
        
        # 解析转发规则
        rules_str = os.getenv("FORWARD_RULES", "")
        if rules_str:
            try:
                self.forward_rules = json.loads(rules_str)
                logger.info(f"已加载 {len(self.forward_rules)} 条转发规则")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 FORWARD_RULES 失败: {e}")
    
    def get_agent_config(self, chat_id: str) -> AgentConfig | None:
        """
        根据 chat_id 获取 Agent 配置
        
        Args:
            chat_id: 群/私聊 ID
        
        Returns:
            AgentConfig 或 None
        """
        rule = self.forward_rules.get(chat_id)
        
        if rule is None:
            # 没有精确匹配，使用默认 URL
            if self.forward_url:
                return {"url_template": self.forward_url}
            return None
        
        # 简单格式：直接是 URL 字符串
        if isinstance(rule, str):
            return {"url_template": rule}
        
        # 完整格式：字典
        return rule
    
    def get_target_url(self, chat_id: str) -> str | None:
        """
        根据 chat_id 获取目标 URL（构建完整 URL）
        
        Args:
            chat_id: 群/私聊 ID
        
        Returns:
            构建后的 URL 或 None
        """
        agent_config = self.get_agent_config(chat_id)
        if not agent_config:
            return None
        
        url_template = agent_config.get("url_template", "")
        agent_id = agent_config.get("agent_id", "")
        
        # 替换 URL 模板中的占位符
        url = url_template.replace("{agent_id}", agent_id)
        
        return url
    
    def get_api_key(self, chat_id: str) -> str | None:
        """获取指定 chat_id 的 API Key"""
        agent_config = self.get_agent_config(chat_id)
        if agent_config:
            return agent_config.get("api_key")
        return None
    
    def get_all_rules(self) -> dict:
        """获取所有转发规则（用于管理台展示）"""
        result = {}
        for chat_id, rule in self.forward_rules.items():
            if isinstance(rule, str):
                result[chat_id] = {
                    "url_template": rule,
                    "type": "simple"
                }
            else:
                result[chat_id] = {
                    **rule,
                    "type": "full"
                }
        return result
    
    def validate(self) -> list[str]:
        """
        验证配置
        
        Returns:
            错误列表，空列表表示配置有效
        """
        errors = []
        
        if not self.bot_key:
            errors.append("FORWARD_BOT_KEY 未配置")
        
        if not self.forward_url and not self.forward_rules:
            errors.append("FORWARD_URL 或 FORWARD_RULES 至少需要配置一个")
        
        return errors


# 全局配置实例
config = Config()
