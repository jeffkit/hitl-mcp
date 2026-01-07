"""
管理 API 单元测试

测试 /admin/config 相关 API
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
import tempfile
import json
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

from forward_service.app import app
from forward_service.config_v2 import config_v2


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def setup_test_config():
    """设置测试配置"""
    # 保存原始配置
    original_bots = config_v2.bots.copy()
    original_default_key = config_v2.default_bot_key
    
    # 设置测试配置
    from forward_service.config_v2 import BotConfig, ForwardConfig, AccessControl
    
    config_v2.default_bot_key = "test_bot"
    config_v2.bots = {
        "test_bot": BotConfig(
            bot_key="test_bot",
            name="Test Bot",
            forward_config=ForwardConfig(url_template="https://test.com"),
            access_control=AccessControl(mode="allow_all")
        )
    }
    
    yield
    
    # 恢复原始配置
    config_v2.bots = original_bots
    config_v2.default_bot_key = original_default_key


class TestAdminConfigAPI:
    """测试 /admin/config API"""
    
    def test_get_config(self, client, setup_test_config):
        """测试获取配置"""
        response = client.get("/admin/config")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "default_bot_key" in data
        assert "bots" in data
        assert data["default_bot_key"] == "test_bot"
        assert "test_bot" in data["bots"]
    
    def test_update_config_success(self, client, setup_test_config):
        """测试更新配置 - 成功"""
        new_config = {
            "default_bot_key": "new_bot",
            "bots": {
                "new_bot": {
                    "bot_key": "new_bot",
                    "name": "New Bot",
                    "description": "Test bot",
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
        config_v2.save_config = lambda: {"success": True}
        
        response = client.put("/admin/config", json=new_config)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_update_config_invalid_format(self, client, setup_test_config):
        """测试更新配置 - 格式错误"""
        invalid_config = {
            "invalid_key": "value"
        }
        
        response = client.put("/admin/config", json=invalid_config)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "错误" in data["error"]
    
    def test_reload_config(self, client, setup_test_config):
        """测试重新加载配置"""
        # Mock reload_config
        config_v2.reload_config = lambda: {"success": True, "message": "配置已重新加载"}
        
        response = client.post("/admin/config/reload")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestAdminStatusAPI:
    """测试 /admin/status API"""
    
    def test_admin_status(self, client, setup_test_config):
        """测试获取服务状态"""
        response = client.get("/admin/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "service" in data
        assert "version" in data
        assert "config" in data
        assert "stats" in data
        assert data["version"] == "2.0.0"


class TestHealthAPI:
    """测试 /health API"""
    
    def test_health_check_healthy(self, client, setup_test_config):
        """测试健康检查 - 健康状态"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert data["status"] == "healthy"
        assert "bots_count" in data
        assert "version" in data
        assert data["version"] == "2.0.0"
    
    def test_health_check_unhealthy(self, client):
        """测试健康检查 - 不健康状态"""
        # 清空 bots 使配置无效
        original_bots = config_v2.bots.copy()
        config_v2.bots = {}
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "unhealthy"
        assert len(data["config_errors"]) > 0
        
        # 恢复配置
        config_v2.bots = original_bots


class TestAdminRulesAPI:
    """测试兼容性 API /admin/rules"""
    
    def test_admin_rules(self, client, setup_test_config):
        """测试获取规则（兼容旧 API）"""
        response = client.get("/admin/rules")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "default_bot_key" in data
        assert "bots" in data
        assert "test_bot" in data["bots"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
