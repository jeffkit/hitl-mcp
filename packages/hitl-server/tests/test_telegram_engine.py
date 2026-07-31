"""Telegram 内置引擎单元测试。

覆盖：
  1. _to_callback_data：私聊/群聊 chattype、short-id 从引用回复/正文提取、
     非文本消息跳过。
  2. _format_message：short-id 头格式化（带/不带 project_name）与 wait_reply 提示。
  3. send_message：httpx.MockTransport 模拟 Bot API，校验载荷与线程回复追踪。
"""
import json

import httpx
import pytest

from hitl_server.engines.telegram import (
    TelegramEngine,
    TelegramStore,
    _extract_short_id,
    _format_message,
    _to_callback_data,
)


class TestExtractShortId:
    def test_extracts_short_id(self):
        assert _extract_short_id("[#abc12345 项目] 请确认") == "abc12345"

    def test_extracts_hex_only_variants(self):
        assert _extract_short_id("[#deadbeef]\n完成") == "deadbeef"

    def test_no_match(self):
        assert _extract_short_id("普通消息") is None


class TestToCallbackData:
    def test_private_chat(self):
        update = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 42, "username": "alice", "first_name": "Alice"},
                "text": "你好",
            },
        }
        data = _to_callback_data(update)
        assert data["chatid"] == "1001"
        assert data["chattype"] == "single"
        assert data["msgtype"] == "text"
        assert data["text"]["content"] == "你好"
        assert data["from"]["userid"] == "42"
        assert data["from"]["name"] == "alice"

    def test_group_chat(self):
        update = {
            "message": {
                "chat": {"id": -1001, "type": "group"},
                "from": {"id": 42, "username": "alice"},
                "text": "大家好",
            }
        }
        data = _to_callback_data(update)
        assert data["chattype"] == "group"
        assert data["chatid"] == "-1001"

    def test_short_id_from_reply_to_message(self):
        """引用回复优先：从被引用消息文本中提取 [#short_id]（最强匹配）。"""
        update = {
            "message": {
                "message_id": 11,
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 42, "username": "alice"},
                "text": "是的",
                "reply_to_message": {
                    "message_id": 10,
                    "chat": {"id": 1001, "type": "private"},
                    "from": {"id": 7, "username": "bot"},
                    "text": "[#abc12345 项目]\n请确认是否继续？\n\n> 请回复此消息以便系统自动关联",
                },
            }
        }
        data = _to_callback_data(update)
        assert data["short_id"] == "abc12345"
        assert data["quote"]["text"]["content"].startswith("[#abc12345")

    def test_short_id_from_current_message_when_no_reply(self):
        update = {
            "message": {
                "chat": {"id": 1001, "type": "private"},
                "from": {"id": 42},
                "text": "[#cafef00d]\n完成",
            }
        }
        data = _to_callback_data(update)
        assert data["short_id"] == "cafef00d"

    def test_non_text_message_ignored(self):
        update = {"message": {"chat": {"id": 1001, "type": "private"}, "from": {"id": 42}, "text": ""}}
        assert _to_callback_data(update) is None

    def test_channel_post_accepted(self):
        update = {"channel_post": {"chat": {"id": -100, "type": "channel"}, "from": {"id": 9}, "text": "公告"}}
        data = _to_callback_data(update)
        assert data is not None and data["text"]["content"] == "公告"


class TestFormatMessage:
    def test_with_project(self):
        body = _format_message("hi", "abc12345", "proj", True)
        assert body.startswith("[#abc12345 proj]")

    def test_without_project(self):
        assert _format_message("hi", "abc12345", None, False).startswith("[#abc12345]")

    def test_no_short_id(self):
        assert not _format_message("hi", "", None, False).startswith("[#")

    def test_wait_reply_hint(self):
        assert "请回复此消息" in _format_message("hi", "", None, True)


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_success_tracks_message_id(self, tmp_path):
        """发送成功回传 chat_id，并记录 message_id 供后续回复建线程。"""
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["chat_id"] == "1001"
            assert "[#abc12345 proj]" in body["text"]
            assert "reply_to_message_id" not in body  # 首条消息无引用
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

        store = TelegramStore(str(tmp_path / "tg.json"))
        engine = TelegramEngine(bot_key="telegram-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({
                "chat_id": "1001",
                "message": "hi",
                "short_id": "abc12345",
                "project_name": "proj",
                "wait_reply": True,
            })
            assert result == {"success": True, "chat_id": "1001"}
            assert engine._sent_msg_ids["1001"] == 99
        finally:
            await engine._http.aclose()

    @pytest.mark.asyncio
    async def test_send_threads_to_last_message(self, tmp_path):
        """第二条消息以第一条的 message_id 作为 reply_to_message_id（线程回复）。"""
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(calls)}})

        store = TelegramStore(str(tmp_path / "tg.json"))
        engine = TelegramEngine(bot_key="telegram-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await engine.send_message({"chat_id": "1001", "message": "a", "short_id": "", "wait_reply": True})
            await engine.send_message({"chat_id": "1001", "message": "b", "short_id": "", "wait_reply": True})
            assert calls[1].get("reply_to_message_id") == 1
        finally:
            await engine._http.aclose()

    @pytest.mark.asyncio
    async def test_send_missing_chat_id(self, tmp_path):
        store = TelegramStore(str(tmp_path / "tg.json"))
        engine = TelegramEngine(bot_key="telegram-1", bot_token="t", store=store)
        result = await engine.send_message({"message": "hi", "short_id": "", "wait_reply": True})
        assert result["success"] is False
        assert "chat_id" in result["error"]

    @pytest.mark.asyncio
    async def test_send_api_error(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Bad Request")

        store = TelegramStore(str(tmp_path / "tg.json"))
        engine = TelegramEngine(bot_key="telegram-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({"chat_id": "1001", "message": "hi", "short_id": "", "wait_reply": True})
            assert result["success"] is False
        finally:
            await engine._http.aclose()
