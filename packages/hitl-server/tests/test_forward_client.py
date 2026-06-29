"""
Forward Client 测试
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx


class TestForwardClient:
    """Forward Client 功能测试"""
    
    @pytest.mark.asyncio
    async def test_get_forward_service_status_no_url(self):
        """测试没有配置 URL 时获取状态"""
        from hitl_server.handlers.forward_client import get_forward_service_status
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config:
            mock_config.forward_service_url = None
            
            result = await get_forward_service_status()
            
            assert "error" in result
            assert "not configured" in result["error"]
    
    @pytest.mark.asyncio
    async def test_get_forward_service_status_direct_mode(self):
        """测试 Direct 模式获取状态"""
        from hitl_server.handlers.forward_client import get_forward_service_status
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy", "bots_count": 3}
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await get_forward_service_status()
            
            assert result["status"] == "healthy"
            assert result["bots_count"] == 3
            assert result["_source"] == "direct_http"
    
    @pytest.mark.asyncio
    async def test_get_forward_service_status_http_error(self):
        """测试 HTTP 错误响应"""
        from hitl_server.handlers.forward_client import get_forward_service_status
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await get_forward_service_status()
            
            assert "error" in result
            assert "500" in result["error"]


class TestForwardServiceLogs:
    """Forward Service 日志测试"""
    
    @pytest.mark.asyncio
    async def test_get_forward_service_logs_success(self):
        """测试成功获取日志"""
        from hitl_server.handlers.forward_client import get_forward_service_logs
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "logs": [
                {"id": 1, "status": "success"},
                {"id": 2, "status": "error"}
            ]
        }
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await get_forward_service_logs(limit=20)
            
            assert result["success"] is True
            assert len(result["logs"]) == 2


class TestForwardServiceRules:
    """Forward Service 规则测试"""
    
    @pytest.mark.asyncio
    async def test_add_forward_rule_no_url(self):
        """测试没有配置 URL 时添加规则"""
        from hitl_server.handlers.forward_client import add_forward_rule, ForwardRule
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config:
            mock_config.forward_service_url = None
            
            rule = ForwardRule(
                chat_id="test-chat",
                target_url="https://api.example.com/agent"
            )
            
            result = await add_forward_rule(rule)
            
            assert "error" in result
            assert "not configured" in result["error"]
    
    @pytest.mark.asyncio
    async def test_update_forward_rule_success(self):
        """测试成功更新规则"""
        from hitl_server.handlers.forward_client import update_forward_rule, ForwardRule
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.put = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            rule = ForwardRule(
                chat_id="test-chat",
                target_url="https://api.example.com/agent"
            )
            
            result = await update_forward_rule("test-chat", rule)
            
            assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_delete_forward_rule_success(self):
        """测试成功删除规则"""
        from hitl_server.handlers.forward_client import delete_forward_rule
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await delete_forward_rule("test-chat")
            
            assert result["success"] is True


class TestForwardServiceConfig:
    """Forward Service 配置测试"""
    
    @pytest.mark.asyncio
    async def test_get_forward_service_config_success(self):
        """测试成功获取配置"""
        from hitl_server.handlers.forward_client import get_forward_service_config
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "default_bot_key": "test-key",
            "bots": {}
        }
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await get_forward_service_config()
            
            assert result["default_bot_key"] == "test-key"
    
    @pytest.mark.asyncio
    async def test_reload_forward_service_config_success(self):
        """测试成功重新加载配置"""
        from hitl_server.handlers.forward_client import reload_forward_service_config
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "message": "配置已重新加载"}
        
        with patch('hitl_server.handlers.forward_client.config') as mock_config, \
             patch('hitl_server.handlers.forward_client.httpx.AsyncClient') as mock_client_class:
            
            mock_config.forward_service_url = "http://localhost:8083"
            mock_config.is_direct_mode = True
            
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client
            
            result = await reload_forward_service_config()
            
            assert result["success"] is True
