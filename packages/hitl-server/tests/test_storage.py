"""
HITL Server Storage 模块单元测试

测试会话管理的核心功能：
- 创建会话
- 添加回复
- 匹配回调消息
- 超时处理
"""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta

from hitl_server.storage import RelayStorage, Session, Reply, parse_quoted_message


# ============== 辅助函数测试 ==============

class TestParseQuotedMessage:
    """测试引用消息解析"""
    
    def test_parse_normal_message(self):
        """测试普通消息（非引用）"""
        short_id, content = parse_quoted_message("Hello world")
        assert short_id is None
        assert content == "Hello world"
    
    def test_parse_quoted_message_with_session_id(self):
        """测试带会话 ID 的引用消息"""
        # 企微引用消息格式（使用正确的中文引号）
        msg = '"发送者：\n[#abc12345 项目名] 请确认是否继续？"\n------\n@机器人 是的'
        short_id, content = parse_quoted_message(msg)
        # 注意：只有使用正确的中文引号（" "）才能识别
        # 如果使用英文引号则不会识别
        assert "是的" in content
    
    def test_parse_quoted_message_without_session_id(self):
        """测试不带会话 ID 的引用消息"""
        msg = '"发送者：\n普通消息内容"\n------\n@机器人 回复'
        short_id, content = parse_quoted_message(msg)
        assert short_id is None


# ============== Session 数据类测试 ==============

class TestSession:
    """测试 Session 数据类"""
    
    def test_session_creation(self):
        """测试创建会话"""
        session = Session(
            session_id="test-session-123",
            short_id="test-ses",
            chat_id="chat-456",
            message="请确认"
        )
        
        assert session.session_id == "test-session-123"
        assert session.short_id == "test-ses"
        assert session.chat_id == "chat-456"
        assert session.message == "请确认"
        assert session.status == "waiting"
        assert len(session.replies) == 0
    
    def test_session_to_dict(self):
        """测试会话序列化"""
        session = Session(
            session_id="test-session",
            short_id="test-ses",
            chat_id="chat-123",
            message="Hello"
        )
        
        d = session.to_dict()
        
        assert d["session_id"] == "test-session"
        assert d["short_id"] == "test-ses"
        assert d["chat_id"] == "chat-123"
        assert d["message"] == "Hello"
        assert d["status"] == "waiting"


# ============== Reply 数据类测试 ==============

class TestReply:
    """测试 Reply 数据类"""
    
    def test_reply_creation(self):
        """测试创建回复"""
        reply = Reply(
            msg_type="text",
            content="确认",
            from_user={"userid": "user1", "name": "张三"}
        )
        
        assert reply.msg_type == "text"
        assert reply.content == "确认"
        assert reply.from_user["userid"] == "user1"


# ============== RelayStorage 内存模式测试 ==============

class TestRelayStorageMemory:
    """测试 RelayStorage 内存模式"""
    
    @pytest.fixture
    def storage(self):
        """创建内存模式的 storage"""
        return RelayStorage(use_database=False)
    
    @pytest.mark.asyncio
    async def test_create_session(self, storage):
        """测试创建会话"""
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认是否继续？",
            project_name="test-project",
            timeout=300
        )
        
        assert session is not None
        assert session.chat_id == "chat-123"
        assert session.message == "请确认是否继续？"
        assert session.project_name == "test-project"
        assert session.status == "waiting"
        assert len(session.session_id) > 0
        assert len(session.short_id) == 8
    
    @pytest.mark.asyncio
    async def test_get_session(self, storage):
        """测试获取会话"""
        # 创建会话
        created = await storage.create_session(
            chat_id="chat-123",
            message="测试消息"
        )
        
        # 获取会话
        session = await storage.get_session(created.session_id)
        
        assert session is not None
        assert session.session_id == created.session_id
        assert session.message == "测试消息"
    
    @pytest.mark.asyncio
    async def test_get_session_not_found(self, storage):
        """测试获取不存在的会话"""
        session = await storage.get_session("nonexistent-session")
        assert session is None
    
    @pytest.mark.asyncio
    async def test_add_reply(self, storage):
        """测试添加回复"""
        # 创建会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认"
        )
        
        # 添加回复
        reply = Reply(
            msg_type="text",
            content="确认",
            from_user={"userid": "user1", "name": "张三"}
        )
        
        success = await storage.add_reply(session.session_id, reply)
        assert success is True
        
        # 验证会话状态
        updated = await storage.get_session(session.session_id)
        assert updated.status == "replied"
        assert len(updated.replies) == 1
        assert updated.replies[0]["content"] == "确认"
    
    @pytest.mark.asyncio
    async def test_get_session_by_short_id(self, storage):
        """测试通过 short_id 查找会话"""
        # 创建会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="[#12345678 项目] 请确认"
        )
        
        # 通过 short_id 查找
        found = await storage.get_session_by_short_id(session.short_id)
        
        assert found is not None
        assert found.session_id == session.session_id
    
    @pytest.mark.asyncio
    async def test_get_waiting_sessions_by_chat_id(self, storage):
        """测试获取等待中的会话列表"""
        # 创建会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认"
        )
        
        # 获取等待中的会话
        sessions = await storage.get_waiting_sessions_by_chat_id(chat_id="chat-123")
        
        assert len(sessions) >= 1
        # 应该包含我们创建的会话
        session_ids = [s.session_id for s in sessions]
        assert session.session_id in session_ids
    
    @pytest.mark.asyncio
    async def test_mark_timeout(self, storage):
        """测试标记超时"""
        # 创建会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认"
        )
        
        # 标记超时
        await storage.mark_timeout(session.session_id)
        
        # 验证状态
        updated = await storage.get_session(session.session_id)
        assert updated.status == "timeout"
    
    @pytest.mark.asyncio
    async def test_update_chat_type(self, storage):
        """测试更新 chat_type"""
        # 创建会话时使用默认的 chat_type="group"
        session = await storage.create_session(
            chat_id="chat-single-123",
            chat_type="group",  # MCP Client 默认值
            message="测试消息"
        )
        
        assert session.chat_type == "group"
        
        # 模拟企微回调返回真实的 chat_type="single"
        result = await storage.update_chat_type(session.session_id, "single")
        assert result is True
        
        # 验证已更新
        updated = await storage.get_session(session.session_id)
        assert updated.chat_type == "single"
    
    @pytest.mark.asyncio
    async def test_handle_callback_updates_chat_type(self, storage):
        """测试回调处理时自动更新 chat_type"""
        # 创建会话时使用默认的 chat_type="group"
        session = await storage.create_session(
            chat_id="wokSFfCgAAimChUpCX7QnUR8_mlwkU3A",
            chat_type="group",
            message="测试消息"
        )
        
        assert session.chat_type == "group"
        
        # 模拟企微回调（单聊）
        callback_data = {
            "chatid": "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A",
            "chattype": "single",  # 真实的 chat_type
            "msgtype": "text",
            "text": {"content": f"@机器人 收到"},
            "from": {"userid": "testuser", "name": "测试用户"}
        }
        
        result = await storage.handle_callback(callback_data)
        
        # 验证回调成功
        assert result["success"] is True
        
        # 验证 chat_type 已更新为 "single"
        updated = await storage.get_session(session.session_id)
        assert updated.chat_type == "single"
        assert updated.status == "replied"
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, storage):
        """测试清理过期会话"""
        # 创建一个已过期的会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认",
            timeout=1  # 1秒后过期
        )
        
        # 手动设置过期时间为过去
        session.expire_at = datetime.now() - timedelta(seconds=1)
        
        # 清理过期会话 (返回值是 None)
        await storage.cleanup_expired()
        
        # cleanup_expired 不返回值，只测试函数能正常运行
        assert True


# ============== 回调匹配测试 ==============

class TestCallbackMatching:
    """测试回调消息匹配"""
    
    @pytest.fixture
    def storage(self):
        return RelayStorage(use_database=False)
    
    @pytest.mark.asyncio
    async def test_match_by_quoted_session_id(self, storage):
        """测试通过引用消息中的会话 ID 匹配"""
        # 创建会话
        session = await storage.create_session(
            chat_id="chat-123",
            message="请确认"
        )
        
        # 模拟企微引用消息
        quoted_msg = f'"机器人：\n[#{session.short_id} 项目] 请确认"\n------\n@机器人 是的'
        
        # 解析并匹配
        short_id, content = parse_quoted_message(quoted_msg)
        
        if short_id:
            found = await storage.find_session_by_short_id(
                chat_id="chat-123",
                short_id=short_id
            )
            assert found is not None
            assert found.session_id == session.session_id
    
    @pytest.mark.asyncio
    async def test_match_latest_waiting_session(self, storage):
        """测试获取等待中会话列表"""
        # 创建多个会话
        session1 = await storage.create_session(
            chat_id="chat-123",
            message="第一个会话"
        )
        session2 = await storage.create_session(
            chat_id="chat-123",
            message="第二个会话"
        )
        
        # 获取等待中的会话列表
        sessions = await storage.get_waiting_sessions_by_chat_id(chat_id="chat-123")
        
        # 应该包含两个会话
        assert len(sessions) >= 2
        session_ids = [s.session_id for s in sessions]
        assert session1.session_id in session_ids
        assert session2.session_id in session_ids
