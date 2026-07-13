"""
iLink 引用回复提取逻辑单元测试

测试目标：
- _extract_ref_msg_id：从 iLink 消息中提取 ref_msg.message_item.msg_id
- _extract_ref_create_time_ms：提取被引用消息时间戳（L1 匹配）
- _extract_ref_text：提取被引用消息文本（L2 匹配，有时缺失）
- _extract_quoted_text：优先 L2 文本，回退旧 refer_item 格式
- _to_callback_data：callback 数据包含 ref_text（L2）和 ref_create_time_ms（L1）

基于实际抓取的 iLink 消息结构（2026-07-12）。
"""
import pytest
from hitl_server.engines.ilink import (
    _extract_ref_msg_id,
    _extract_ref_create_time_ms,
    _extract_ref_text,
    _extract_quoted_text,
    _to_callback_data,
    UserMessage,
)


# ── 真实抓获的消息结构 ────────────────────────────────────────────────────────

# 普通消息（无引用）
PLAIN_MSG = {
    "seq": 869,
    "message_id": 7482081111111111111,
    "from_user_id": "o9cq80_ZyXuz1vAtG-TMbQjwQPW8@im.wechat",
    "to_user_id": "154e144959c6@im.bot",
    "message_type": 1,
    "item_list": [
        {
            "type": 1,
            "text_item": {"text": "你好"},
            "button_item_list": [],
            "create_time_ms": 1783867000000,
            "is_completed": True,
            "msg_id": "v1:11111111111111111",
            "update_time_ms": 1783867000000,
        }
    ],
    "context_token": "vctx_xxx",
}

# 引用回复消息（真实结构，ref_msg 在 item_list 每个 item 里）
QUOTE_MSG = {
    "seq": 870,
    "message_id": 7482081428794536200,
    "from_user_id": "o9cq80_ZyXuz1vAtG-TMbQjwQPW8@im.wechat",
    "to_user_id": "154e144959c6@im.bot",
    "message_type": 1,
    "item_list": [
        {
            "type": 1,
            "text_item": {"text": "发公网"},
            "button_item_list": [],
            "create_time_ms": 1783867222879,
            "is_completed": True,
            "msg_id": "v1:12645617370845745868",
            "ref_msg": {
                "message_item": {
                    "button_item_list": [],
                    "create_time_ms": 1783867069000,
                    "is_completed": True,
                    "msg_id": "7482080782393609608",
                    "type": 0,
                    "update_time_ms": 1783867069000,
                }
            },
            "update_time_ms": 1783867222879,
        }
    ],
    "context_token": "vctx_xxx",
}

# 引用消息：ref_msg.message_item.msg_id 为整数类型（防御性测试）
QUOTE_MSG_INT_MSGID = {
    "item_list": [
        {
            "type": 1,
            "text_item": {"text": "回复"},
            "ref_msg": {
                "message_item": {
                    "msg_id": 7482080782393609608,  # 整数
                }
            },
        }
    ],
}

# 引用回复消息：ref_msg.message_item 含 text_item（L2 场景，iLink 不稳定下发）
QUOTE_MSG_WITH_TEXT = {
    "seq": 871,
    "from_user_id": "o9cq80_ZyXuz1vAtG-TMbQjwQPW8@im.wechat",
    "item_list": [
        {
            "type": 1,
            "text_item": {"text": "好的"},
            "ref_msg": {
                "message_item": {
                    "create_time_ms": 1783867599000,
                    "msg_id": "7482083004179339144",
                    "type": 0,
                    # L2 字段：被引用消息的文本内容（包含 [#short_id]）
                    "text_item": {"text": "[#a1b2c3d4 myproject]\n请确认部署到生产环境\n\n> 请引用回复此消息"},
                }
            },
        }
    ],
    "context_token": "vctx_xxx",
}

# 没有 item_list 的消息
EMPTY_MSG = {}


# ── _extract_ref_msg_id 测试 ──────────────────────────────────────────────────

class TestExtractRefMsgId:
    """测试从 iLink 消息中提取被引用消息的 msg_id"""

    def test_plain_message_returns_empty(self):
        """普通消息没有 ref_msg，返回空字符串"""
        assert _extract_ref_msg_id(PLAIN_MSG) == ""

    def test_quote_message_returns_msg_id(self):
        """引用回复消息能正确提取 ref_msg.message_item.msg_id"""
        result = _extract_ref_msg_id(QUOTE_MSG)
        assert result == "7482080782393609608"

    def test_int_msg_id_converted_to_str(self):
        """msg_id 为整数时，转换为字符串"""
        result = _extract_ref_msg_id(QUOTE_MSG_INT_MSGID)
        assert result == "7482080782393609608"

    def test_empty_message_returns_empty(self):
        """空消息返回空字符串"""
        assert _extract_ref_msg_id(EMPTY_MSG) == ""

    def test_missing_ref_msg_returns_empty(self):
        """item 存在但没有 ref_msg，返回空字符串"""
        msg = {"item_list": [{"type": 1, "text_item": {"text": "hi"}}]}
        assert _extract_ref_msg_id(msg) == ""

    def test_empty_ref_msg_returns_empty(self):
        """ref_msg 为空 dict，返回空字符串"""
        msg = {"item_list": [{"ref_msg": {}}]}
        assert _extract_ref_msg_id(msg) == ""

    def test_ref_msg_missing_message_item_returns_empty(self):
        """ref_msg 有内容但没有 message_item，返回空字符串"""
        msg = {"item_list": [{"ref_msg": {"other_field": "value"}}]}
        assert _extract_ref_msg_id(msg) == ""


# ── _extract_quoted_text 测试（旧字段备用） ───────────────────────────────────

class TestExtractQuotedText:
    """验证 _extract_quoted_text 在真实 iLink 结构下返回空（iLink 不传文本）"""

    def test_real_quote_msg_no_refer_item(self):
        """真实 iLink 引用消息没有 refer_item，_extract_quoted_text 返回空"""
        result = _extract_quoted_text(QUOTE_MSG)
        assert result == ""

    def test_plain_msg_returns_empty(self):
        """普通消息不含引用，返回空"""
        assert _extract_quoted_text(PLAIN_MSG) == ""

    def test_hypothetical_refer_item_content(self):
        """假设性：如果有 refer_item.content，能正确提取"""
        msg = {
            "item_list": [
                {
                    "refer_item": {
                        "content": "[#abc12345] 请确认",
                        "displayname": "ClawBot",
                    }
                }
            ]
        }
        result = _extract_quoted_text(msg)
        assert result == "[#abc12345] 请确认"

    def test_hypothetical_refer_item_displayname_last(self):
        """displayname 应排在 content/text/item_list 之后"""
        msg = {
            "item_list": [
                {
                    "refer_item": {
                        "displayname": "ClawBot",
                        # 没有 content / text / 嵌套 item_list
                    }
                }
            ]
        }
        result = _extract_quoted_text(msg)
        assert result == "ClawBot"


# ── _to_callback_data 测试 ────────────────────────────────────────────────────

class TestToCallbackData:
    """验证 callback 数据正确携带 ref_msg_id"""

    def test_plain_msg_no_ref_msg_id(self):
        """普通消息的 callback 不含 ref_msg_id"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="你好",
            raw=PLAIN_MSG,
        )
        data = _to_callback_data(user_msg)
        assert "ref_msg_id" not in data
        assert data["chatid"] == "user@im.wechat"
        assert data["msgtype"] == "text"

    def test_quote_msg_has_ref_create_time_ms(self):
        """引用回复的 callback 包含 ref_create_time_ms（sendmessage 响应为空，用时间戳近似匹配）"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="发公网",
            raw=QUOTE_MSG,
        )
        data = _to_callback_data(user_msg)
        assert data.get("ref_create_time_ms") == 1783867069000

    def test_quote_msg_no_quote_field(self):
        """iLink 引用回复没有 quote 字段（旧文本提取失败，改用时间戳匹配）"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="发公网",
            raw=QUOTE_MSG,
        )
        data = _to_callback_data(user_msg)
        # iLink 不传被引用消息文本，所以不应有 quote 字段
        assert "quote" not in data


# ── _extract_ref_create_time_ms 测试 ─────────────────────────────────────────

class TestExtractRefCreateTimeMs:
    """测试从 iLink 消息中提取被引用消息的创建时间戳"""

    def test_quote_msg_returns_create_time(self):
        assert _extract_ref_create_time_ms(QUOTE_MSG) == 1783867069000

    def test_plain_msg_returns_zero(self):
        assert _extract_ref_create_time_ms(PLAIN_MSG) == 0

    def test_empty_msg_returns_zero(self):
        assert _extract_ref_create_time_ms({}) == 0

    def test_quote_msg_with_text_returns_create_time(self):
        """有 text_item 的引用消息同样能提取时间戳（L1 和 L2 同时可用）"""
        assert _extract_ref_create_time_ms(QUOTE_MSG_WITH_TEXT) == 1783867599000


# ── _extract_ref_text 测试（L2）────────────────────────────────────────────

class TestExtractRefText:
    """测试从 ref_msg.message_item.text_item.text 提取被引用消息文本（L2）"""

    def test_quote_with_text_item_returns_text(self):
        """有 text_item 时能提取出完整的被引用消息文本"""
        result = _extract_ref_text(QUOTE_MSG_WITH_TEXT)
        assert result == "[#a1b2c3d4 myproject]\n请确认部署到生产环境\n\n> 请引用回复此消息"

    def test_quote_without_text_item_returns_empty(self):
        """无 text_item 时返回空（需回退到 L1 时间戳匹配）"""
        assert _extract_ref_text(QUOTE_MSG) == ""

    def test_plain_msg_returns_empty(self):
        assert _extract_ref_text(PLAIN_MSG) == ""

    def test_empty_msg_returns_empty(self):
        assert _extract_ref_text({}) == ""

    def test_empty_text_item_returns_empty(self):
        """text_item 存在但 text 为空时，视为无文本"""
        msg = {
            "item_list": [{
                "ref_msg": {"message_item": {"text_item": {"text": ""}}}
            }]
        }
        assert _extract_ref_text(msg) == ""


# ── _extract_quoted_text 更新测试 ─────────────────────────────────────────

class TestExtractQuotedText:
    """验证 _extract_quoted_text 优先使用 L2 (ref_msg.text_item)，回退 refer_item"""

    def test_quote_with_text_item_returns_text(self):
        """L2 可用时，_extract_quoted_text 返回 ref_msg.message_item.text_item.text"""
        result = _extract_quoted_text(QUOTE_MSG_WITH_TEXT)
        assert "[#a1b2c3d4" in result

    def test_real_quote_msg_no_text_item_returns_empty(self):
        """真实 iLink 引用消息无 text_item，L2 缺失，返回空（L1 时间戳匹配接管）"""
        result = _extract_quoted_text(QUOTE_MSG)
        assert result == ""

    def test_plain_msg_returns_empty(self):
        """普通消息不含引用，返回空"""
        assert _extract_quoted_text(PLAIN_MSG) == ""

    def test_hypothetical_refer_item_content(self):
        """旧格式兜底：如果有 refer_item.content，仍能正确提取"""
        msg = {
            "item_list": [
                {
                    "refer_item": {
                        "content": "[#abc12345] 请确认",
                        "displayname": "ClawBot",
                    }
                }
            ]
        }
        result = _extract_quoted_text(msg)
        assert result == "[#abc12345] 请确认"

    def test_hypothetical_refer_item_displayname_last(self):
        """displayname 排在所有正文字段之后"""
        msg = {
            "item_list": [
                {
                    "refer_item": {
                        "displayname": "ClawBot",
                    }
                }
            ]
        }
        result = _extract_quoted_text(msg)
        assert result == "ClawBot"


# ── _to_callback_data L2 测试 ────────────────────────────────────────────────

class TestToCallbackDataL2:
    """验证 callback 数据在 L2 可用时携带 ref_text"""

    def test_quote_with_text_item_has_ref_text(self):
        """有 text_item 时，callback 包含 ref_text 字段"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="好的",
            raw=QUOTE_MSG_WITH_TEXT,
        )
        data = _to_callback_data(user_msg)
        assert "ref_text" in data
        assert "[#a1b2c3d4" in data["ref_text"]

    def test_quote_with_text_item_still_has_ref_create_time_ms(self):
        """有 text_item 时，L1 时间戳也同样携带（两层都提供，storage 按优先级选用）"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="好的",
            raw=QUOTE_MSG_WITH_TEXT,
        )
        data = _to_callback_data(user_msg)
        assert data.get("ref_create_time_ms") == 1783867599000

    def test_quote_without_text_item_no_ref_text(self):
        """无 text_item 时，callback 不含 ref_text，只有 ref_create_time_ms"""
        user_msg = UserMessage(
            from_user_id="user@im.wechat",
            context_token="vctx_xxx",
            text="发公网",
            raw=QUOTE_MSG,
        )
        data = _to_callback_data(user_msg)
        assert "ref_text" not in data
        assert data.get("ref_create_time_ms") == 1783867069000
