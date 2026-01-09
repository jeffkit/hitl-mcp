"""
认证功能测试
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestJWTAuthentication:
    """JWT 认证测试"""
    
    def test_create_token(self):
        """测试创建 JWT Token"""
        from hil_server.handlers.admin import create_token
        
        with patch('hil_server.handlers.admin.config') as mock_config:
            mock_config.admin_token_secret = "test-secret-key-12345"
            
            token, expires_at = create_token("test_user")
            
            assert token is not None
            assert isinstance(token, str)
            assert len(token) > 0
            assert expires_at > datetime.utcnow()
    
    def test_verify_token_valid(self):
        """测试验证有效的 Token"""
        from hil_server.handlers.admin import create_token, verify_token
        
        with patch('hil_server.handlers.admin.config') as mock_config:
            mock_config.admin_token_secret = "test-secret-key-12345"
            
            token, _ = create_token("test_user")
            username = verify_token(token)
            
            assert username == "test_user"
    
    def test_verify_token_invalid(self):
        """测试验证无效的 Token"""
        from hil_server.handlers.admin import verify_token
        
        with patch('hil_server.handlers.admin.config') as mock_config:
            mock_config.admin_token_secret = "test-secret-key-12345"
            
            result = verify_token("invalid-token")
            
            assert result is None
    
    def test_verify_token_expired(self):
        """测试验证过期的 Token"""
        import jwt
        from hil_server.handlers.admin import verify_token, JWT_ALGORITHM
        
        with patch('hil_server.handlers.admin.config') as mock_config:
            mock_config.admin_token_secret = "test-secret-key-12345"
            
            # 创建一个已过期的 Token
            payload = {
                "sub": "test_user",
                "exp": datetime.utcnow() - timedelta(hours=1),  # 已过期
                "iat": datetime.utcnow() - timedelta(hours=25)
            }
            expired_token = jwt.encode(payload, mock_config.admin_token_secret, algorithm=JWT_ALGORITHM)
            
            result = verify_token(expired_token)
            
            assert result is None


class TestPasswordHashing:
    """密码哈希测试"""
    
    def test_password_hashing(self):
        """测试密码哈希一致性"""
        import hashlib
        
        password = "test_password"
        hash1 = hashlib.sha256(password.encode()).hexdigest()
        hash2 = hashlib.sha256(password.encode()).hexdigest()
        
        assert hash1 == hash2
    
    def test_different_passwords_different_hashes(self):
        """测试不同密码产生不同哈希"""
        import hashlib
        
        password1 = "password1"
        password2 = "password2"
        
        hash1 = hashlib.sha256(password1.encode()).hexdigest()
        hash2 = hashlib.sha256(password2.encode()).hexdigest()
        
        assert hash1 != hash2


class TestForwardRule:
    """ForwardRule 模型测试"""
    
    def test_forward_rule_creation(self):
        """测试 ForwardRule 创建"""
        from hil_server.handlers.forward_client import ForwardRule
        
        rule = ForwardRule(
            chat_id="test-chat",
            target_url="https://api.example.com/agent",
            api_key="test-key",
            timeout=60
        )
        
        assert rule.chat_id == "test-chat"
        assert rule.target_url == "https://api.example.com/agent"
        assert rule.api_key == "test-key"
        assert rule.timeout == 60
    
    def test_forward_rule_default_values(self):
        """测试 ForwardRule 默认值"""
        from hil_server.handlers.forward_client import ForwardRule
        
        rule = ForwardRule(
            chat_id="test-chat",
            target_url="https://api.example.com/agent"
        )
        
        assert rule.api_key == ""
        assert rule.timeout == 60
    
    def test_forward_rule_model_dump(self):
        """测试 ForwardRule 序列化"""
        from hil_server.handlers.forward_client import ForwardRule
        
        rule = ForwardRule(
            chat_id="test-chat",
            target_url="https://api.example.com/agent",
            api_key="test-key"
        )
        
        data = rule.model_dump()
        
        assert data["chat_id"] == "test-chat"
        assert data["target_url"] == "https://api.example.com/agent"
        assert data["api_key"] == "test-key"
