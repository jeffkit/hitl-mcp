"""
callback.py 集成测试

使用 Mock 模拟外部依赖，完整测试 handle_callback 函数的各种场景
"""
import pytest
import pytest_asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

from forward_service.config import BotConfig, ForwardConfig, AccessControl
from forward_service.services.forwarder import AgentResult


class MockRequest:
    """模拟 FastAPI Request 对象"""
    
    def __init__(self, data: dict):
        self._data = data
    
    async def json(self):
        return self._data


def create_callback_data(
    chat_id: str = "test_chat_123",
    msg_type: str = "text",
    content: str = "hello world",
    user_id: str = "user_123",
    user_name: str = "Test User",
    webhook_url: str = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test_bot_key",
    image_url: str = None
) -> dict:
    """创建测试用的回调数据"""
    data = {
        "chatid": chat_id,
        "chattype": "group",
        "msgtype": msg_type,
        "from": {
            "userid": user_id,
            "name": user_name,
            "alias": ""
        },
        "webhook_url": webhook_url,
    }
    
    if msg_type == "text":
        data["text"] = {"content": f"@Bot {content}"}
    elif msg_type == "image":
        data["image"] = {"image_url": image_url or "https://example.com/image.png"}
    elif msg_type == "mixed":
        data["mixed_message"] = {
            "msg_item": [
                {"msg_type": "text", "text": {"content": f"@Bot {content}"}},
                {"msg_type": "image", "image": {"image_url": image_url or "https://example.com/image.png"}}
            ]
        }
    
    return data


def create_mock_bot(
    bot_key: str = "test_bot_key",
    name: str = "Test Bot",
    enabled: bool = True,
    access_mode: str = "allow_all",
    url: str = "https://api.test.com/webhook"
) -> BotConfig:
    """创建测试用的 Bot 配置"""
    return BotConfig(
        bot_key=bot_key,
        name=name,
        forward_config=ForwardConfig(
            url_template=url,
            api_key="sk-test",
            timeout=60
        ),
        access_control=AccessControl(mode=access_mode),
        enabled=enabled
    )


class TestHandleCallbackAuth:
    """测试回调鉴权"""

    @pytest.mark.asyncio
    async def test_auth_success(self, mock_db_manager):
        """测试鉴权成功"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = "x-api-key"
            mock_config.callback_auth_value = "secret123"
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=None)

            request = MockRequest(create_callback_data())
            result = await handle_callback(request, x_api_key="secret123")

            # 应该继续处理（虽然没有 Bot 会返回错误）
            assert result["errcode"] == 0

    @pytest.mark.asyncio
    async def test_auth_failure(self, mock_db_manager):
        """测试鉴权失败"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = "x-api-key"
            mock_config.callback_auth_value = "secret123"

            request = MockRequest(create_callback_data())
            result = await handle_callback(request, x_api_key="wrong_key")

            assert result["errcode"] == 401
            assert "Unauthorized" in result["errmsg"]


class TestHandleCallbackEvents:
    """测试事件类型处理"""

    @pytest.mark.asyncio
    async def test_ignore_event_type(self, mock_db_manager):
        """测试忽略 event 类型消息"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None

            data = create_callback_data(msg_type="event")
            request = MockRequest(data)
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"

    @pytest.mark.asyncio
    async def test_ignore_enter_chat(self, mock_db_manager):
        """测试忽略 enter_chat 类型消息"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None

            data = create_callback_data(msg_type="enter_chat")
            request = MockRequest(data)
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"


class TestHandleCallbackBotConfig:
    """测试 Bot 配置获取"""

    @pytest.mark.asyncio
    async def test_no_bot_config(self, mock_db_manager):
        """测试没有 Bot 配置时的处理"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="unknown_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "no bot config" in result["errmsg"]
            mock_send.assert_called_once()


class TestHandleCallbackAccessControl:
    """测试访问控制"""

    @pytest.mark.asyncio
    async def test_access_denied(self, mock_db_manager):
        """测试访问被拒绝"""
        from forward_service.routes.callback import handle_callback

        mock_bot = create_mock_bot(access_mode="whitelist")

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.get_bot_from_db = AsyncMock(return_value=None)  # 无备选 Bot
            mock_config.check_access = MagicMock(return_value=(False, "没有权限"))
            mock_config.default_bot_key = "test_key"  # 同一个 Bot，不回退
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "access denied" in result["errmsg"]


class TestHandleCallbackEmptyContent:
    """测试空内容处理"""

    @pytest.mark.asyncio
    async def test_empty_content(self, mock_db_manager):
        """测试空消息内容"""
        from forward_service.routes.callback import handle_callback

        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = (None, None)  # 空内容

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "empty content" in result["errmsg"]


class TestHandleCallbackProjectCommands:
    """测试项目命令处理"""

    @pytest.mark.asyncio
    async def test_add_project_command(self, mock_db_manager):
        """测试 /add-project 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        # 初始化 session manager
        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/add-project test https://api.test.com", None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/add-project test https://api.test.com"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "project command handled" in result["errmsg"]
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_projects_command(self, mock_db_manager):
        """测试 /list-projects 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/list-projects", None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/list-projects"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_send.assert_called_once()


class TestHandleCallbackSlashCommands:
    """测试 Slash 命令处理"""

    @pytest.mark.asyncio
    async def test_reset_command(self, mock_db_manager):
        """测试 /reset 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/reset", None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/reset"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "slash command handled" in result["errmsg"]

    @pytest.mark.asyncio
    async def test_sess_command(self, mock_db_manager):
        """测试 /sess 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/sess", None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/sess"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "slash command handled" in result["errmsg"]


class TestHandleCallbackForward:
    """测试消息转发"""

    @pytest.mark.asyncio
    async def test_forward_success(self, mock_db_manager):
        """测试成功转发消息"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        mock_result = AgentResult(
            reply="Hello from Agent!",
            msg_type="text",
            session_id="session_123456789",
            project_id=None
        )

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_user_project') as mock_forward, \
             patch('forward_service.routes.callback.add_request_log') as mock_add_log, \
             patch('forward_service.routes.callback.update_request_log') as mock_update_log, \
             patch('forward_service.routes.callback.add_pending_request') as mock_add_pending, \
             patch('forward_service.routes.callback.remove_pending_request') as mock_remove_pending, \
             patch('forward_service.routes.callback.is_session_processing') as mock_is_processing, \
             patch('forward_service.routes.callback.add_processing_session') as mock_add_processing, \
             patch('forward_service.routes.callback.remove_processing_session') as mock_remove_processing:
            
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.timeout = 60
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("Hello", None)
            mock_forward.return_value = mock_result
            mock_send.return_value = {"success": True}
            mock_add_log.return_value = 1
            mock_is_processing.return_value = None
            mock_add_processing.return_value = True

            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"
            mock_forward.assert_called_once()
            mock_send.assert_called()

    @pytest.mark.asyncio
    async def test_forward_failure(self, mock_db_manager):
        """测试转发失败"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_user_project') as mock_forward, \
             patch('forward_service.routes.callback.add_request_log') as mock_add_log, \
             patch('forward_service.routes.callback.update_request_log') as mock_update_log, \
             patch('forward_service.routes.callback.add_pending_request') as mock_add_pending, \
             patch('forward_service.routes.callback.remove_pending_request') as mock_remove_pending, \
             patch('forward_service.routes.callback.is_session_processing') as mock_is_processing, \
             patch('forward_service.routes.callback.add_processing_session') as mock_add_processing, \
             patch('forward_service.routes.callback.remove_processing_session') as mock_remove_processing:
            
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.timeout = 60
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("Hello", None)
            mock_forward.return_value = None  # 转发失败
            mock_send.return_value = {"success": True}
            mock_add_log.return_value = 1
            mock_is_processing.return_value = None
            mock_add_processing.return_value = True

            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "forward failed" in result["errmsg"]


class TestHandleCallbackConcurrency:
    """测试并发控制"""

    @pytest.mark.asyncio
    async def test_session_already_processing(self, mock_db_manager):
        """测试会话正在处理中的情况"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.is_session_processing') as mock_is_processing:
            
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("Hello", None)
            mock_send.return_value = {"success": True}
            
            # 模拟会话正在处理中
            mock_is_processing.return_value = {
                "message": "Previous message",
                "elapsed_seconds": 5
            }

            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "session busy" in result["errmsg"]


class TestHandleCallbackExceptions:
    """测试异常处理"""

    @pytest.mark.asyncio
    async def test_json_parse_error(self, mock_db_manager):
        """测试 JSON 解析错误"""
        from forward_service.routes.callback import handle_callback

        class BadRequest:
            async def json(self):
                raise ValueError("Invalid JSON")

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None

            request = BadRequest()
            result = await handle_callback(request)

            assert result["errcode"] == -1

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, mock_db_manager):
        """测试意外异常"""
        from forward_service.routes.callback import handle_callback

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(side_effect=Exception("Unexpected error"))

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == -1
            assert "Unexpected error" in result["errmsg"]


class TestHandleCallbackAdminCommands:
    """测试管理员命令处理"""

    @pytest.mark.asyncio
    async def test_ping_command_as_admin(self, mock_db_manager):
        """测试管理员执行 /ping 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/ping", None)
            mock_send.return_value = {"success": True}
            mock_check_admin.return_value = True

            request = MockRequest(create_callback_data(content="/ping"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "slash command handled" in result["errmsg"]
            # 应该发送包含 pong 的消息
            mock_send.assert_called()

    @pytest.mark.asyncio
    async def test_ping_command_as_non_admin(self, mock_db_manager):
        """测试非管理员执行 /ping 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/ping", None)
            mock_send.return_value = {"success": True}
            mock_check_admin.return_value = False

            request = MockRequest(create_callback_data(content="/ping"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "permission denied" in result["errmsg"]

    @pytest.mark.asyncio
    async def test_status_command(self, mock_db_manager):
        """测试 /status 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin, \
             patch('forward_service.routes.callback.get_system_status') as mock_status:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/status", None)
            mock_send.return_value = {"success": True}
            mock_check_admin.return_value = True
            mock_status.return_value = "🟢 System OK"

            request = MockRequest(create_callback_data(content="/status"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_command(self, mock_db_manager):
        """测试 /help 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin, \
             patch('forward_service.routes.callback.get_admin_help') as mock_help:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/help", None)
            mock_send.return_value = {"success": True}
            mock_check_admin.return_value = True
            mock_help.return_value = "📖 Help..."

            request = MockRequest(create_callback_data(content="/help"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_help.assert_called_once()

    @pytest.mark.asyncio
    async def test_bots_command(self, mock_db_manager):
        """测试 /bots 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin, \
             patch('forward_service.routes.callback.get_bots_list') as mock_bots:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/bots", None)
            mock_send.return_value = {"success": True}
            mock_check_admin.return_value = True
            mock_bots.return_value = "🤖 Bot list..."

            request = MockRequest(create_callback_data(content="/bots"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_bots.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_command_with_extra_message(self, mock_db_manager):
        """测试 /change 命令带附加消息"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager, SessionManager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        mock_result = AgentResult(reply="Response", msg_type="text", session_id="new_sess")

        # 先创建一个会话
        session_manager = SessionManager(mock_db_manager)
        await session_manager.record_session(
            user_id="user_123",
            chat_id="test_chat_123",
            bot_key="test_bot_key",
            session_id="session_abc12345",
            last_message="Previous"
        )

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_user_project') as mock_forward, \
             patch('forward_service.routes.callback.add_request_log') as mock_add_log, \
             patch('forward_service.routes.callback.update_request_log') as mock_update_log, \
             patch('forward_service.routes.callback.add_pending_request'), \
             patch('forward_service.routes.callback.remove_pending_request'), \
             patch('forward_service.routes.callback.is_session_processing') as mock_is_processing, \
             patch('forward_service.routes.callback.add_processing_session') as mock_add_processing, \
             patch('forward_service.routes.callback.remove_processing_session'):
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.timeout = 60
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_bot_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ("/c abc12345 继续对话", None)
            mock_send.return_value = {"success": True}
            mock_forward.return_value = mock_result
            mock_add_log.return_value = 1
            mock_is_processing.return_value = None
            mock_add_processing.return_value = True

            request = MockRequest(create_callback_data(content="/c abc12345 继续对话"))
            result = await handle_callback(request)

            assert result["errcode"] == 0


class TestHandleCallbackAccessControlFallback:
    """测试访问控制回退逻辑"""

    @pytest.mark.asyncio
    async def test_fallback_to_default_bot(self, mock_db_manager):
        """测试当前 Bot 被拒绝后回退到默认 Bot"""
        from forward_service.routes.callback import handle_callback

        mock_bot = create_mock_bot(bot_key="custom_key", access_mode="whitelist")
        mock_default_bot = create_mock_bot(bot_key="default_key", access_mode="allow_all")

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract:
            mock_config.callback_auth_key = None
            mock_config.callback_auth_value = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="custom_key")
            mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)
            mock_config.get_bot_from_db = AsyncMock(return_value=mock_default_bot)
            mock_config.default_bot_key = "default_key"
            
            # 第一次拒绝，第二次允许（回退到默认 Bot）
            mock_config.check_access = MagicMock(side_effect=[
                (False, "没有权限"),
                (True, "")
            ])
            mock_extract.return_value = (None, None)  # 空内容，快速结束

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            # 由于空内容，会返回 empty content
            assert result["errcode"] == 0
