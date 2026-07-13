"""wecom-aibot 引擎引用回复提取 + 多会话匹配测试。

wecom-aibot 与 ilink 走同一个 storage.handle_callback，多会话错配已在
storage 层统一修复（无 short_id 时拒绝而非 FIFO）。这里覆盖：
  1. 引用回复：企微 AI Bot 把被引用内容以「...」嵌入正文开头，_QUOTE_RE 提取
     出 quote，storage 从中取出 [#short_id] 精确匹配。
  2. 无引用：不产生 quote。
  3. 多会话引用回复：精确匹配被引用的会话，而非最早会话。
  4. 多会话无引用：storage 拒绝匹配（ambiguous_session + prompt_user）。
"""
import pytest

from hitl_server.engines.wecom_aibot import WecomAibotEngine, _QUOTE_RE, _format_message_with_header
from hitl_server.storage import RelayStorage


def _make_engine() -> WecomAibotEngine:
    """轻量构造引擎（不连 WS）：仅用于 _on_msg_callback 的引用提取与回调转发。"""
    return WecomAibotEngine(
        bot_key="wecom-aibot-test",
        bot_id="bid",
        bot_secret="bsec",
    )


def _quote_callback(short_id: str, project: str, message: str, reply: str, userid: str = "u1") -> dict:
    """构造企微 AI Bot 引用回复的回调消息（外层 msg，含 body）。"""
    quoted = _format_message_with_header(message, short_id, project, wait_reply=True)
    content = f"「{quoted}」\n{reply}"
    return {"body": {
        "chattype": "single",
        "from": {"userid": userid, "name": ""},
        "msgtype": "text",
        "text": {"content": content},
    }}


class TestQuoteRegex:
    def test_extracts_quoted_block(self):
        m = _QUOTE_RE.match("「[#abc12345 项目]\n正文\n\n> 请引用回复此消息」\n是的")
        assert m is not None
        assert "[#abc12345" in m.group(1)
        assert "是的" not in m.group(1)

    def test_no_match_without_quote_block(self):
        assert _QUOTE_RE.match("普通回复") is None


async def _capture(engine: WecomAibotEngine, sink: list[dict]) -> None:
    async def cb(data: dict) -> None:
        sink.append(data)
    engine.on_user_message = cb  # type: ignore[assignment]


class TestOnMsgCallbackQuoteExtraction:
    @pytest.mark.asyncio
    async def test_quote_reply_populates_quote_field(self):
        engine = _make_engine()
        captured: list[dict] = []
        await _capture(engine, captured)

        await engine._on_msg_callback(_quote_callback("abc12345", "项目", "请确认", "是的"))

        assert len(captured) == 1
        data = captured[0]
        assert data["chatid"] == "u1"
        assert "[#abc12345" in data["quote"]["text"]["content"]
        assert data["text"]["content"] == "是的"

    @pytest.mark.asyncio
    async def test_plain_reply_has_no_quote(self):
        engine = _make_engine()
        captured: list[dict] = []
        await _capture(engine, captured)

        msg = {"body": {
            "chattype": "single",
            "from": {"userid": "u1", "name": ""},
            "msgtype": "text",
            "text": {"content": "普通回复"},
        }}
        await engine._on_msg_callback(msg)

        assert "quote" not in captured[0]


class TestWecomAibotStorageMatching:
    """端到端：wecom-aibot 引用提取 → storage.handle_callback 匹配。"""

    @pytest.fixture
    def storage(self):
        return RelayStorage(use_database=False)

    @pytest.mark.asyncio
    async def test_quote_reply_matches_target_session_not_earliest(self, storage):
        """同一 chat_id 两个会话，引用回复后者应精确匹配后者。"""
        chat_id = "u1"
        s1 = await storage.create_session(chat_id=chat_id, message="老消息")
        s2 = await storage.create_session(chat_id=chat_id, message="新消息")

        engine = _make_engine()
        engine.on_user_message = storage.handle_callback  # type: ignore[assignment]

        # 用户引用 s2 的消息回复
        await engine._on_msg_callback(_quote_callback(s2.short_id, "项目", "新消息", "好的", userid=chat_id))

        assert (await storage.get_session(s2.session_id)).status == "replied"
        assert (await storage.get_session(s1.session_id)).status == "waiting"

    @pytest.mark.asyncio
    async def test_plain_reply_on_multiple_sessions_rejected(self, storage):
        """同一 chat_id 多个会话且无引用 → storage 拒绝匹配（不再 FIFO 错配）。"""
        chat_id = "u1"
        s1 = await storage.create_session(chat_id=chat_id, message="老消息")
        s2 = await storage.create_session(chat_id=chat_id, message="新消息")

        # wecom-aibot 对无引用消息转出的 callback_data（无 quote / short_id）
        callback_data = {
            "chatid": chat_id,
            "chattype": "single",
            "msgtype": "text",
            "text": {"content": "普通回复"},
            "from": {"userid": chat_id, "name": ""},
        }
        r = await storage.handle_callback(callback_data)
        assert r["success"] is False
        assert r["error"] == "ambiguous_session"
        assert r["prompt_user"] is True
        assert set(r["waiting_short_ids"]) == {s1.short_id, s2.short_id}
