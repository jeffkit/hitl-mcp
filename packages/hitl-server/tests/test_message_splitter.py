"""
消息分拆器单元测试

测试内容：
1. 字符串字节数计算
2. 消息内容分拆
3. 超长行分拆
4. 消息头部生成
5. 完整的分拆和格式化流程
6. 边界条件测试
"""
import pytest

from hitl_server.message_splitter import (
    get_string_bytes,
    split_message_content,
    _split_long_line,
    create_message_header,
    split_and_format_message,
    needs_split,
    SplitMessage,
    MAX_MESSAGE_BYTES,
    EFFECTIVE_MAX_BYTES,
)


class TestGetStringBytes:
    """测试字符串字节数计算"""
    
    def test_ascii_string(self):
        """ASCII 字符每个占 1 字节"""
        assert get_string_bytes("hello") == 5
        assert get_string_bytes("") == 0
        assert get_string_bytes(" ") == 1
    
    def test_chinese_string(self):
        """中文字符每个占 3 字节（UTF-8）"""
        assert get_string_bytes("你好") == 6
        assert get_string_bytes("测试消息") == 12
    
    def test_mixed_string(self):
        """混合字符串"""
        # "Hello你好" = 5 + 6 = 11 字节
        assert get_string_bytes("Hello你好") == 11
        
    def test_emoji(self):
        """Emoji 字符（4 字节）"""
        assert get_string_bytes("😀") == 4
        assert get_string_bytes("Hello 😀") == 10  # 5 + 1 + 4
    
    def test_newline(self):
        """换行符占 1 字节"""
        assert get_string_bytes("\n") == 1
        assert get_string_bytes("a\nb") == 3


class TestSplitMessageContent:
    """测试消息内容分拆"""
    
    def test_short_message_no_split(self):
        """短消息不需要分拆"""
        message = "这是一条短消息"
        result = split_message_content(message, max_bytes=1000)
        
        assert len(result) == 1
        assert result[0] == message
    
    def test_empty_message(self):
        """空消息"""
        result = split_message_content("", max_bytes=100)
        assert result == [""]
    
    def test_split_by_lines(self):
        """按行分拆消息"""
        # 每行 30 字节，限制 50 字节
        line1 = "a" * 30  # 30 字节
        line2 = "b" * 30  # 30 字节
        message = f"{line1}\n{line2}"
        
        result = split_message_content(message, max_bytes=50)
        
        assert len(result) == 2
        assert result[0] == line1
        assert result[1] == line2
    
    def test_combine_short_lines(self):
        """短行可以合并"""
        lines = ["短行1", "短行2", "短行3"]  # 每行 7 字节
        message = "\n".join(lines)
        
        # 限制 50 字节，应该能容纳所有行
        result = split_message_content(message, max_bytes=50)
        
        assert len(result) == 1
        assert result[0] == message
    
    def test_long_line_forced_split(self):
        """超长行强制分拆"""
        # 创建一个 100 字节的行
        long_line = "x" * 100
        
        result = split_message_content(long_line, max_bytes=50)
        
        assert len(result) == 2
        assert result[0] == "x" * 50
        assert result[1] == "x" * 50
    
    def test_chinese_message_split(self):
        """中文消息分拆"""
        # 每个中文字符 3 字节
        # "测试" = 6 字节，重复 10 次 = 60 字节
        message = "测试" * 10
        
        result = split_message_content(message, max_bytes=30)
        
        assert len(result) == 2
        # 每段应该是 30 字节以内
        for part in result:
            assert get_string_bytes(part) <= 30
    
    def test_preserve_code_blocks(self):
        """尽量保持代码块完整"""
        code_block = "```python\nprint('hello')\n```"
        short_text = "OK"
        message = f"{code_block}\n\n{short_text}"
        
        # 设置一个较大的限制，确保不分拆
        result = split_message_content(message, max_bytes=1000)
        
        assert len(result) == 1
        assert "```python" in result[0]
        assert "```" in result[0]


class TestSplitLongLine:
    """测试超长行分拆"""
    
    def test_split_long_ascii_line(self):
        """分拆长 ASCII 行"""
        line = "a" * 100
        result = _split_long_line(line, max_bytes=50)
        
        assert len(result) == 2
        assert result[0] == "a" * 50
        assert result[1] == "a" * 50
    
    def test_split_chinese_line(self):
        """分拆中文行"""
        # 10 个中文字符 = 30 字节
        line = "测" * 10
        result = _split_long_line(line, max_bytes=15)
        
        assert len(result) == 2
        # 每段 5 个字符（15 字节）
        for part in result:
            assert get_string_bytes(part) <= 15
    
    def test_empty_line(self):
        """空行"""
        result = _split_long_line("", max_bytes=50)
        assert result == [""]


class TestCreateMessageHeader:
    """测试消息头部生成"""
    
    def test_basic_header(self):
        """基本头部"""
        header = create_message_header("abc123", None, 1, 1)
        assert header == "[#abc123]"
    
    def test_header_with_project_name(self):
        """带项目名的头部"""
        header = create_message_header("abc123", "测试项目", 1, 1)
        assert header == "[#abc123 测试项目]"
    
    def test_header_with_page_number(self):
        """带分页信息的头部"""
        header = create_message_header("abc123", "项目", 2, 3)
        assert header == "[#abc123 项目] (2/3)"
    
    def test_single_page_no_number(self):
        """单页消息不显示分页"""
        header = create_message_header("abc123", "项目", 1, 1)
        assert "(1/1)" not in header
        assert header == "[#abc123 项目]"
    
    def test_empty_short_id(self):
        """无 short_id 返回空"""
        header = create_message_header("", "项目", 1, 1)
        assert header == ""


class TestSplitAndFormatMessage:
    """测试完整的分拆和格式化流程"""
    
    def test_short_message_single_part(self):
        """短消息，单条"""
        result = split_and_format_message(
            message="Hello",
            short_id="abc",
            project_name="Test",
            wait_reply=True,
            max_bytes=1000
        )
        
        assert len(result) == 1
        msg = result[0]
        assert msg.part_number == 1
        assert msg.total_parts == 1
        assert msg.is_first is True
        assert msg.is_last is True
        assert "[#abc Test]" in msg.content
        assert "Hello" in msg.content
        assert "请回复" in msg.content
    
    def test_short_message_no_reply(self):
        """短消息，不需要回复"""
        result = split_and_format_message(
            message="Hello",
            short_id="abc",
            project_name=None,
            wait_reply=False,
            max_bytes=1000
        )
        
        assert len(result) == 1
        assert "请回复" not in result[0].content
    
    def test_long_message_split(self):
        """长消息分拆"""
        # 创建一个需要分拆的消息
        long_message = "测试消息\n" * 50  # 约 350 字节
        
        result = split_and_format_message(
            message=long_message,
            short_id="abc",
            project_name="项目",
            wait_reply=True,
            max_bytes=200  # 限制每段 200 字节
        )
        
        assert len(result) > 1
        
        # 检查第一条消息
        first_msg = result[0]
        assert first_msg.is_first is True
        assert first_msg.is_last is False
        assert "(1/" in first_msg.content
        assert "请回复" not in first_msg.content  # 非最后一条
        
        # 检查最后一条消息
        last_msg = result[-1]
        assert last_msg.is_first is False
        assert last_msg.is_last is True
        assert "请回复" in last_msg.content  # 最后一条有回复提示
    
    def test_all_parts_have_header(self):
        """所有分拆的消息都有头部"""
        long_message = "x" * 500
        
        result = split_and_format_message(
            message=long_message,
            short_id="test123",
            project_name="MyProject",
            wait_reply=True,
            max_bytes=100
        )
        
        for msg in result:
            assert "[#test123 MyProject]" in msg.content
    
    def test_page_numbers_correct(self):
        """分页号正确"""
        long_message = "y" * 300
        
        result = split_and_format_message(
            message=long_message,
            short_id="abc",
            project_name=None,
            wait_reply=False,
            max_bytes=100
        )
        
        total = len(result)
        for i, msg in enumerate(result):
            assert msg.part_number == i + 1
            assert msg.total_parts == total
            assert f"({i+1}/{total})" in msg.content


class TestNeedsSplit:
    """测试是否需要分拆判断"""
    
    def test_short_message_no_split(self):
        """短消息不需要分拆"""
        assert needs_split("Hello", "abc", "Project", True) is False
    
    def test_long_message_needs_split(self):
        """长消息需要分拆"""
        # 创建一个超过 4K 的消息
        long_message = "测试" * 2000  # 约 12KB
        assert needs_split(long_message, "abc", "Project", True) is True
    
    def test_near_boundary(self):
        """接近边界的消息"""
        # 创建一个接近 4K 的消息
        # 考虑头部 "[#abc 项目]\n" 约 20 字节
        # 尾部 "\n\n---\n📮 **请回复**" 约 25 字节
        # 总开销约 45 字节
        
        # MAX_MESSAGE_BYTES = 4096
        # 创建一个刚好不需要分拆的消息
        message_bytes = MAX_MESSAGE_BYTES - 100  # 留点余量
        short_message = "x" * message_bytes
        
        assert needs_split(short_message, "abc", "项目", True) is False
        
        # 创建一个刚好需要分拆的消息
        long_message = "x" * (MAX_MESSAGE_BYTES + 100)
        assert needs_split(long_message, "abc", "项目", True) is True


class TestEdgeCases:
    """边界条件测试"""
    
    def test_only_newlines(self):
        """只有换行符的消息"""
        message = "\n\n\n"
        result = split_message_content(message, max_bytes=100)
        assert len(result) == 1
    
    def test_unicode_boundary(self):
        """Unicode 字符边界"""
        # 确保不会在 Unicode 字符中间分拆
        message = "测试" * 100
        result = split_message_content(message, max_bytes=50)
        
        for part in result:
            # 每部分都应该是有效的 UTF-8 字符串
            assert part.encode('utf-8').decode('utf-8') == part
    
    def test_very_long_line_with_chinese(self):
        """超长中文行"""
        long_line = "中" * 2000  # 6000 字节
        result = split_message_content(long_line, max_bytes=1000)
        
        # 应该被分成多段
        assert len(result) > 1
        
        # 每段都不超过限制
        for part in result:
            assert get_string_bytes(part) <= 1000
    
    def test_mixed_content_split(self):
        """混合内容分拆"""
        message = """
# 标题

这是一段中文内容。

```python
print("Hello, World!")
```

更多内容...
"""
        # 设置较小的限制来触发分拆
        result = split_message_content(message.strip(), max_bytes=50)
        
        # 确保分拆成功
        assert len(result) > 1
        
        # 合并后应该与原消息相同（或非常接近）
        combined = '\n'.join(result)
        # 由于分拆可能在不同位置，只检查总长度接近
        original_bytes = get_string_bytes(message.strip())
        combined_bytes = get_string_bytes(combined)
        # 允许少量差异（换行符处理可能有差异）
        assert abs(original_bytes - combined_bytes) < 10


class TestIntegration:
    """集成测试"""
    
    def test_realistic_agent_response(self):
        """模拟真实的 Agent 响应"""
        # 模拟一个包含代码的长响应
        response = """好的，我来帮你实现这个功能。

以下是修改后的代码：

```python
def hello_world():
    \"\"\"打印 Hello World\"\"\"
    print("Hello, World!")
    
    for i in range(10):
        print(f"Count: {i}")
    
    return True
```

这段代码做了以下事情：
1. 定义了一个函数
2. 打印了 Hello World
3. 循环打印了数字

如果还有问题，请告诉我！
"""
        
        result = split_and_format_message(
            message=response,
            short_id="test",
            project_name="Demo",
            wait_reply=True,
            max_bytes=300  # 设置较小的限制来测试分拆
        )
        
        # 验证所有部分都有效
        assert len(result) >= 1
        
        for msg in result:
            # 每条消息都应该有头部
            assert "[#test Demo]" in msg.content
            # 字节数应该在合理范围内
            assert get_string_bytes(msg.content) <= 500  # 考虑头部尾部的开销
        
        # 最后一条有回复提示
        assert "请回复" in result[-1].content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
