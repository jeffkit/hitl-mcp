"""
config_v2.py 单元测试

测试 ConfigV2, BotConfig, ForwardConfig, AccessControl 的所有功能
"""
import pytest
import json
import tempfile
import os
from pathlib import Path

# 添加项目路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from forward_service.config_v2 import (
    ForwardConfig,
    AccessControl,
    BotConfig,
    ConfigV2
)


class TestForwardConfig:
    """ForwardConfig 测试"""
    
    def test_create_forward_config(self):
        """测试创建 ForwardConfig"""
        config = ForwardConfig(
            url_template="https://api.com/a2a/{agent_id}/msg",
            agent_id="agent-001",
            api_key="sk-test",
            timeout=30
        )
        
        assert config.url_template == "https://api.com/a2a/{agent_id}/msg"
        assert config.agent_id == "agent-001"
        assert config.api_key == "sk-test"
        assert config.timeout == 30
    
    def test_get_url_with_agent_id(self):
        """测试 URL 生成（带 agent_id）"""
        config = ForwardConfig(
            url_template="https://api.com/a2a/{agent_id}/msg",
            agent_id="agent-A"
        )
        
        url = config.get_url()
        assert url == "https://api.com/a2a/agent-A/msg"
    
    def test_get_url_without_agent_id(self):
        """测试 URL 生成（不带 agent_id）"""
        config = ForwardConfig(
            url_template="https://api.com/handle"
        )
        
        url = config.get_url()
        assert url == "https://api.com/handle"
    
    def test_to_dict(self):
        """测试转换为字典"""
        config = ForwardConfig(
            url_template="https://api.com/handle",
            agent_id="agent-001",
            api_key="sk-test",
            timeout=45
        )
        
        data = config.to_dict()
        assert data == {
            "url_template": "https://api.com/handle",
            "agent_id": "agent-001",
            "api_key": "sk-test",
            "timeout": 45
        }
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "url_template": "https://api.com/handle",
            "agent_id": "agent-002",
            "api_key": "sk-test2",
            "timeout": 50
        }
        
        config = ForwardConfig.from_dict(data)
        assert config.url_template == "https://api.com/handle"
        assert config.agent_id == "agent-002"
        assert config.api_key == "sk-test2"
        assert config.timeout == 50


class TestAccessControl:
    """AccessControl 测试"""
    
    def test_allow_all_mode(self):
        """测试 allow_all 模式"""
        ac = AccessControl(mode="allow_all")
        
        allowed, reason = ac.check_access("any_user")
        assert allowed is True
        assert reason == ""
    
    def test_whitelist_mode_allowed(self):
        """测试 whitelist 模式 - 在白名单中"""
        ac = AccessControl(
            mode="whitelist",
            whitelist=["user1", "user2"]
        )
        
        allowed, reason = ac.check_access("user1")
        assert allowed is True
        assert reason == ""
    
    def test_whitelist_mode_denied(self):
        """测试 whitelist 模式 - 不在白名单中"""
        ac = AccessControl(
            mode="whitelist",
            whitelist=["user1", "user2"]
        )
        
        allowed, reason = ac.check_access("user3")
        assert allowed is False
        assert "不在白名单中" in reason
    
    def test_blacklist_mode_allowed(self):
        """测试 blacklist 模式 - 不在黑名单中"""
        ac = AccessControl(
            mode="blacklist",
            blacklist=["bad_user"]
        )
        
        allowed, reason = ac.check_access("good_user")
        assert allowed is True
        assert reason == ""
    
    def test_blacklist_mode_denied(self):
        """测试 blacklist 模式 - 在黑名单中"""
        ac = AccessControl(
            mode="blacklist",
            blacklist=["bad_user"]
        )
        
        allowed, reason = ac.check_access("bad_user")
        assert allowed is False
        assert "黑名单" in reason
    
    def test_to_dict(self):
        """测试转换为字典"""
        ac = AccessControl(
            mode="whitelist",
            whitelist=["user1"],
            blacklist=[]
        )
        
        data = ac.to_dict()
        assert data == {
            "mode": "whitelist",
            "whitelist": ["user1"],
            "blacklist": []
        }
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "mode": "blacklist",
            "whitelist": [],
            "blacklist": ["bad_user"]
        }
        
        ac = AccessControl.from_dict(data)
        assert ac.mode == "blacklist"
        assert ac.whitelist == []
        assert ac.blacklist == ["bad_user"]


class TestBotConfig:
    """BotConfig 测试"""
    
    def test_create_bot_config(self):
        """测试创建 BotConfig"""
        bot = BotConfig(
            bot_key="test_key",
            name="Test Bot",
            description="Test description",
            forward_config=ForwardConfig(url_template="https://api.com"),
            access_control=AccessControl(mode="allow_all"),
            enabled=True
        )
        
        assert bot.bot_key == "test_key"
        assert bot.name == "Test Bot"
        assert bot.description == "Test description"
        assert bot.enabled is True
    
    def test_to_dict(self):
        """测试转换为字典"""
        bot = BotConfig(
            bot_key="test_key",
            name="Test Bot"
        )
        
        data = bot.to_dict()
        assert "bot_key" in data
        assert "name" in data
        assert "forward_config" in data
        assert "access_control" in data
        assert "enabled" in data
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "bot_key": "test_key",
            "name": "Test Bot",
            "description": "Test",
            "forward_config": {
                "url_template": "https://api.com",
                "agent_id": "",
                "api_key": "",
                "timeout": 60
            },
            "access_control": {
                "mode": "allow_all",
                "whitelist": [],
                "blacklist": []
            },
            "enabled": True
        }
        
        bot = BotConfig.from_dict(data)
        assert bot.bot_key == "test_key"
        assert bot.name == "Test Bot"
        assert bot.forward_config.url_template == "https://api.com"


class TestConfigV2:
    """ConfigV2 测试"""
    
    @pytest.fixture
    def temp_config_file(self):
        """创建临时配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_data = {
                "default_bot_key": "bot1",
                "bots": {
                    "bot1": {
                        "bot_key": "bot1",
                        "name": "Bot 1",
                        "description": "Test bot 1",
                        "forward_config": {
                            "url_template": "https://api1.com",
                            "agent_id": "",
                            "api_key": "",
                            "timeout": 60
                        },
                        "access_control": {
                            "mode": "allow_all",
                            "whitelist": [],
                            "blacklist": []
                        },
                        "enabled": True
                    },
                    "bot2": {
                        "bot_key": "bot2",
                        "name": "Bot 2",
                        "description": "Test bot 2",
                        "forward_config": {
                            "url_template": "https://api2.com",
                            "agent_id": "agent-A",
                            "api_key": "sk-test",
                            "timeout": 30
                        },
                        "access_control": {
                            "mode": "whitelist",
                            "whitelist": ["user1"],
                            "blacklist": []
                        },
                        "enabled": True
                    }
                }
            }
            json.dump(config_data, f)
            temp_path = f.name
        
        yield temp_path
        
        # 清理
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    def test_extract_bot_key_from_webhook_url(self):
        """测试从 webhook_url 提取 bot_key"""
        config = ConfigV2()
        
        # 标准格式
        url = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=18c6cb5d-611c-4829-ad86-e5b9d46729c0"
        bot_key = config.extract_bot_key_from_webhook_url(url)
        assert bot_key == "18c6cb5d-611c-4829-ad86-e5b9d46729c0"
        
        # 带额外参数
        url = "http://example.com/webhook?foo=bar&key=test_key&baz=qux"
        bot_key = config.extract_bot_key_from_webhook_url(url)
        assert bot_key == "test_key"
        
        # 无 key 参数
        url = "http://example.com/webhook?foo=bar"
        bot_key = config.extract_bot_key_from_webhook_url(url)
        assert bot_key is None
    
    def test_get_bot(self, temp_config_file):
        """测试获取 Bot 配置"""
        # 临时修改配置文件路径
        config = ConfigV2()
        config._ConfigV2__post_init = lambda: None
        config.bots = {
            "bot1": BotConfig(bot_key="bot1", name="Bot 1"),
            "bot2": BotConfig(bot_key="bot2", name="Bot 2")
        }
        
        # 存在的 Bot
        bot = config.get_bot("bot1")
        assert bot is not None
        assert bot.name == "Bot 1"
        
        # 不存在的 Bot
        bot = config.get_bot("bot3")
        assert bot is None
    
    def test_get_bot_or_default(self):
        """测试获取 Bot 或默认 Bot"""
        config = ConfigV2()
        config.default_bot_key = "default"
        config.bots = {
            "default": BotConfig(bot_key="default", name="Default Bot"),
            "bot1": BotConfig(bot_key="bot1", name="Bot 1")
        }
        
        # 存在的 Bot
        bot = config.get_bot_or_default("bot1")
        assert bot.name == "Bot 1"
        
        # 不存在的 Bot，返回默认
        bot = config.get_bot_or_default("bot2")
        assert bot.name == "Default Bot"
        
        # None，返回默认
        bot = config.get_bot_or_default(None)
        assert bot.name == "Default Bot"
    
    def test_check_access(self):
        """测试访问控制检查"""
        config = ConfigV2()
        
        # allow_all
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(mode="allow_all")
        )
        allowed, reason = config.check_access(bot, "any_user")
        assert allowed is True
        
        # 禁用的 Bot
        bot.enabled = False
        allowed, reason = config.check_access(bot, "any_user")
        assert allowed is False
        assert "禁用" in reason
    
    def test_validate(self):
        """测试配置验证"""
        config = ConfigV2()
        
        # 无 Bot 配置
        config.bots = {}
        errors = config.validate()
        assert len(errors) > 0
        assert any("至少需要配置一个 Bot" in e for e in errors)
        
        # 有效配置
        config.default_bot_key = "bot1"
        config.bots = {
            "bot1": BotConfig(
                bot_key="bot1",
                name="Bot 1",
                forward_config=ForwardConfig(url_template="https://api.com")
            )
        }
        errors = config.validate()
        assert len(errors) == 0
        
        # 默认 Bot Key 不存在
        config.default_bot_key = "bot2"
        errors = config.validate()
        assert len(errors) > 0
        assert any("不存在于 bots 配置中" in e for e in errors)
    
    def test_get_config_dict(self):
        """测试获取配置字典"""
        config = ConfigV2()
        config.default_bot_key = "bot1"
        config.bots = {
            "bot1": BotConfig(bot_key="bot1", name="Bot 1")
        }
        
        data = config.get_config_dict()
        assert "default_bot_key" in data
        assert "bots" in data
        assert data["default_bot_key"] == "bot1"
        assert "bot1" in data["bots"]
    
    def test_update_from_dict(self):
        """测试从字典更新配置"""
        config = ConfigV2()
        config.bots = {}
        
        new_data = {
            "default_bot_key": "new_bot",
            "bots": {
                "new_bot": {
                    "bot_key": "new_bot",
                    "name": "New Bot",
                    "description": "",
                    "forward_config": {
                        "url_template": "https://newapi.com",
                        "agent_id": "",
                        "api_key": "",
                        "timeout": 60
                    },
                    "access_control": {
                        "mode": "allow_all",
                        "whitelist": [],
                        "blacklist": []
                    },
                    "enabled": True
                }
            }
        }
        
        # Mock save_config
        config.save_config = lambda: {"success": True}
        
        result = config.update_from_dict(new_data)
        assert result["success"] is True
        assert config.default_bot_key == "new_bot"
        assert "new_bot" in config.bots
        assert config.bots["new_bot"].name == "New Bot"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
