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
    
    # 配置文件路径
    config_file: str = ""
    
    def __post_init__(self):
        """加载配置（优先级：JSON 配置文件 > 环境变量 > 默认值）"""
        # 1. 先从 JSON 配置文件加载
        self._load_config_file()
        
        # 2. 环境变量可覆盖配置文件的值
        if os.getenv("FORWARD_BOT_KEY"):
            self.bot_key = os.getenv("FORWARD_BOT_KEY")
        if os.getenv("FORWARD_URL"):
            self.forward_url = os.getenv("FORWARD_URL")
        if os.getenv("FORWARD_PORT"):
            self.port = int(os.getenv("FORWARD_PORT"))
        if os.getenv("FORWARD_TIMEOUT"):
            self.timeout = int(os.getenv("FORWARD_TIMEOUT"))
        
        # 回调鉴权
        self.callback_auth_key = os.getenv("CALLBACK_AUTH_KEY", self.callback_auth_key)
        self.callback_auth_value = os.getenv("CALLBACK_AUTH_VALUE", self.callback_auth_value)
        
        # 解析环境变量中的转发规则（会与配置文件规则合并）
        rules_str = os.getenv("FORWARD_RULES", "")
        if rules_str:
            try:
                env_rules = json.loads(rules_str)
                self.forward_rules.update(env_rules)
                logger.info(f"从环境变量加载了 {len(env_rules)} 条转发规则")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 FORWARD_RULES 失败: {e}")
        
        # 从 data/forward_rules.json 加载规则（补充）
        self._load_rules()
    
    def _get_config_file_path(self) -> str:
        """获取主配置文件路径"""
        # 支持通过环境变量指定配置文件
        if os.getenv("FORWARD_CONFIG_FILE"):
            return os.getenv("FORWARD_CONFIG_FILE")
        # 默认在项目根目录
        return os.path.join(os.path.dirname(__file__), "..", "forward_config.json")
    
    def _load_config_file(self):
        """从 JSON 配置文件加载"""
        config_file = self._get_config_file_path()
        
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                self.bot_key = data.get("bot_key", self.bot_key)
                self.forward_url = data.get("default_url", self.forward_url)
                self.port = data.get("port", self.port)
                self.timeout = data.get("timeout", self.timeout)
                self.forward_rules = data.get("rules", self.forward_rules)
                self.config_file = config_file
                
                logger.info(f"从 {config_file} 加载配置: bot_key={self.bot_key[:8]}..., rules={len(self.forward_rules)}")
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
        else:
            logger.info(f"配置文件不存在: {config_file}，使用环境变量配置")
    
    def save_config(self):
        """保存配置到 JSON 文件"""
        config_file = self._get_config_file_path()
        
        try:
            data = {
                "bot_key": self.bot_key,
                "port": self.port,
                "timeout": self.timeout,
                "default_url": self.forward_url,
                "rules": self.forward_rules,
                "description": "Forward Service - 反向消息流"
            }
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"配置已保存到 {config_file}")
            return {"success": True, "message": "配置已保存"}
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return {"success": False, "error": str(e)}
    
    def reload_config(self):
        """重新加载配置"""
        self._load_config_file()
        self._load_rules()
        return {"success": True, "message": "配置已重新加载"}
    
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
    
    # ============== 规则管理方法（支持持久化） ==============
    
    def _get_rules_file_path(self) -> str:
        """获取规则文件路径"""
        return os.path.join(os.path.dirname(__file__), "..", "data", "forward_rules.json")
    
    def _save_rules(self):
        """保存规则到文件"""
        rules_file = self._get_rules_file_path()
        os.makedirs(os.path.dirname(rules_file), exist_ok=True)
        
        try:
            with open(rules_file, "w", encoding="utf-8") as f:
                json.dump(self.forward_rules, f, ensure_ascii=False, indent=2)
            logger.info(f"规则已保存到 {rules_file}")
        except Exception as e:
            logger.error(f"保存规则失败: {e}")
    
    def _load_rules(self):
        """从文件加载规则"""
        rules_file = self._get_rules_file_path()
        
        if os.path.exists(rules_file):
            try:
                with open(rules_file, "r", encoding="utf-8") as f:
                    file_rules = json.load(f)
                    # 合并文件规则（文件规则优先级低于环境变量）
                    for chat_id, rule in file_rules.items():
                        if chat_id not in self.forward_rules:
                            self.forward_rules[chat_id] = rule
                    logger.info(f"从 {rules_file} 加载了 {len(file_rules)} 条规则")
            except Exception as e:
                logger.error(f"加载规则文件失败: {e}")
    
    def add_rule(self, chat_id: str, rule: dict) -> dict:
        """添加或更新转发规则"""
        self.forward_rules[chat_id] = rule
        self._save_rules()
        return {"success": True, "message": f"规则已添加: {chat_id}"}
    
    def update_rule(self, chat_id: str, rule: dict) -> dict:
        """更新转发规则"""
        if chat_id not in self.forward_rules:
            return {"success": False, "error": f"规则不存在: {chat_id}"}
        
        self.forward_rules[chat_id] = rule
        self._save_rules()
        return {"success": True, "message": f"规则已更新: {chat_id}"}
    
    def delete_rule(self, chat_id: str) -> dict:
        """删除转发规则"""
        if chat_id not in self.forward_rules:
            return {"success": False, "error": f"规则不存在: {chat_id}"}
        
        del self.forward_rules[chat_id]
        self._save_rules()
        return {"success": True, "message": f"规则已删除: {chat_id}"}
    
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
