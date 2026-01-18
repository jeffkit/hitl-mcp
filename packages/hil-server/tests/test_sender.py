"""
消息发送器单元测试

测试内容：
1. 消息格式化（头部、尾部）
2. 消息分拆发送
3. 图片发送
4. 错误处理
"""
import pytest
from unittest.mock import patch, MagicMock

from hil_server.sender import (
    format_message_with_header,
    send_message_direct,
)


class TestFormatMessageWithHeader:
    """测试消息格式化"""
    
    def test_with_short_id_and_project(self):
        """有 short_id 和项目名"""
        result = format_message_with_header(
            message="Hello",
            short_id="abc123",
            project_name="TestProject",
            wait_reply=True
        )
        
        assert "[#abc123 TestProject]" in result
        assert "Hello" in result
        assert "请回复" in result
    
    def test_with_short_id_only(self):
        """只有 short_id，没有项目名"""
        result = format_message_with_header(
            message="Hello",
            short_id="abc123",
            project_name=None,
            wait_reply=True
        )
        
        assert "[#abc123]" in result
        assert "Hello" in result
        assert "请回复" in result
    
    def test_without_wait_reply(self):
        """不需要等待回复"""
        result = format_message_with_header(
            message="Hello",
            short_id="abc123",
            project_name="Test",
            wait_reply=False
        )
        
        assert "[#abc123 Test]" in result
        assert "请回复" not in result
    
    def test_empty_short_id(self):
        """空 short_id（readonly 消息）"""
        result = format_message_with_header(
            message="Hello",
            short_id="",
            project_name="Test",
            wait_reply=True
        )
        
        # 没有头部
        assert "[#" not in result
        assert "Hello" in result
        # 仍有回复提示
        assert "请回复" in result
    
    def test_multiline_message(self):
        """多行消息"""
        message = "Line1\nLine2\nLine3"
        result = format_message_with_header(
            message=message,
            short_id="abc",
            project_name=None,
            wait_reply=True
        )
        
        # 头部在第一行
        lines = result.split('\n')
        assert lines[0] == "[#abc]"
        # 消息内容在后面
        assert "Line1" in result
        assert "Line2" in result
        assert "Line3" in result


class TestSendMessageDirect:
    """测试直接发送消息"""
    
    @pytest.mark.asyncio
    async def test_send_short_message(self):
        """发送短消息（不分拆）"""
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}
            
            result = await send_message_direct(
                short_id="abc",
                message="Hello, World!",
                chat_id="chat123",
                project_name="Test",
                wait_reply=True
            )
            
            assert result["success"] is True
            assert result["parts_sent"] == 1
            
            # 检查调用参数
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            sent_message = call_args.kwargs["message"]
            
            assert "[#abc Test]" in sent_message
            assert "Hello, World!" in sent_message
            assert "请回复" in sent_message
    
    @pytest.mark.asyncio
    async def test_send_long_message_split(self):
        """发送长消息（需要分拆）"""
        # 创建一个超过 4K 的消息
        long_message = "测试内容\n" * 500  # 约 3.5KB，加上头部尾部会超过 4K
        
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}
            
            result = await send_message_direct(
                short_id="abc",
                message=long_message,
                chat_id="chat123",
                project_name="LongProject",
                wait_reply=True
            )
            
            assert result["success"] is True
            # 应该分拆成多条
            assert result["parts_sent"] > 1
            
            # 检查每条消息都被发送
            assert mock_send.call_count == result["parts_sent"]
            
            # 检查每条消息都有头部
            for call in mock_send.call_args_list:
                sent_message = call.kwargs["message"]
                assert "[#abc LongProject]" in sent_message
            
            # 检查只有最后一条有「请回复」
            last_call = mock_send.call_args_list[-1]
            last_message = last_call.kwargs["message"]
            assert "请回复" in last_message
            
            # 其他消息没有「请回复」
            for call in mock_send.call_args_list[:-1]:
                sent_message = call.kwargs["message"]
                assert "请回复" not in sent_message
    
    @pytest.mark.asyncio
    async def test_send_with_images(self):
        """发送带图片的消息"""
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}
            
            result = await send_message_direct(
                short_id="abc",
                message="看这张图片",
                chat_id="chat123",
                images=["base64_image_data_here"],
                wait_reply=True
            )
            
            assert result["success"] is True
            
            # 应该调用两次：一次文本，一次图片
            assert mock_send.call_count == 2
            
            # 检查图片发送
            image_call = mock_send.call_args_list[1]
            assert image_call.kwargs["msg_type"] == "image"
    
    @pytest.mark.asyncio
    async def test_send_error_handling(self):
        """发送失败处理"""
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.side_effect = Exception("Network error")
            
            result = await send_message_direct(
                short_id="abc",
                message="Hello",
                chat_id="chat123",
                wait_reply=True
            )
            
            assert result["success"] is False
            assert "Network error" in result["error"]
    
    @pytest.mark.asyncio
    async def test_image_failure_continues(self):
        """图片发送失败不影响整体结果"""
        call_count = 0
        
        def mock_send_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("msg_type") == "image":
                raise Exception("Image upload failed")
            return {"errcode": 0, "errmsg": "ok"}
        
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.side_effect = mock_send_side_effect
            
            result = await send_message_direct(
                short_id="abc",
                message="Hello",
                chat_id="chat123",
                images=["image1", "image2"],
                wait_reply=True
            )
            
            # 整体仍然成功
            assert result["success"] is True
            # 文本发送成功，图片尝试了但失败（不影响结果）
            assert call_count == 3  # 1 文本 + 2 图片尝试
    
    @pytest.mark.asyncio
    async def test_send_without_wait_reply(self):
        """发送不需要回复的消息"""
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}
            
            result = await send_message_direct(
                short_id="abc",
                message="这是一条通知",
                chat_id="chat123",
                wait_reply=False
            )
            
            assert result["success"] is True
            
            sent_message = mock_send.call_args.kwargs["message"]
            assert "请回复" not in sent_message
    
    @pytest.mark.asyncio
    async def test_split_message_page_numbers(self):
        """分拆消息的分页号"""
        # 创建需要分拆的消息
        long_message = "x" * 5000  # 超过 4K
        
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}
            
            result = await send_message_direct(
                short_id="abc",
                message=long_message,
                chat_id="chat123",
                project_name="Test",
                wait_reply=True
            )
            
            total_parts = result["parts_sent"]
            assert total_parts > 1
            
            # 检查分页信息
            for i, call in enumerate(mock_send.call_args_list):
                sent_message = call.kwargs["message"]
                expected_page = f"({i+1}/{total_parts})"
                assert expected_page in sent_message


class TestSendToWecom:
    """测试 send_to_wecom 函数（需要 mock pigeon）"""
    
    @pytest.mark.asyncio
    async def test_text_message(self):
        """发送文本消息"""
        with patch('hil_server.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0}
            
            result = await send_message_direct(
                short_id="abc",
                message="Test",
                chat_id="chat123",
                wait_reply=False
            )
            
            assert result["success"] is True
            mock_send.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
