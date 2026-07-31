"""Discord 内置引擎单元测试。

覆盖：
  1. _to_callback_data：Bot 消息跳过、DM/群聊 chattype、short-id 从引用回复/
     正文提取。
  2. _format_message：short-id 头格式化与 wait_reply 提示。
  3. send_message：httpx.MockTransport 模拟 REST API，校验载荷与 message_reference。
"""
import json

import httpx
import pytest

from hitl_server.engines.discord import (
    DiscordEngine,
    DiscordStore,
    _extract_short_id,
    _format_message,
    _to_callback_data,
)


class TestExtractShortId:
    def test_extracts_short_id(self):
        assert _extract_short_id("[#abc12345 项目] 请确认") == "abc12345"

    def test_no_match(self):
        assert _extract_short_id("普通消息") is None


class TestToCallbackData:
    def test_bot_message_ignored(self):
        event = {"author": {"id": "777", "bot": True, "username": "bot"}, "content": "自动回复"}
        assert _to_callback_data(event) is None

    def test_dm_chat(self):
        event = {
            "id": "m1",
            "channel_id": "123456",
            "guild_id": None,
            "author": {"id": "42", "username": "alice"},
            "content": "你好",
        }
        data = _to_callback_data(event)
        assert data["chatid"] == "123456"
        assert data["chattype"] == "single"
        assert data["text"]["content"] == "你好"
        assert data["from"]["userid"] == "42"

    def test_guild_chat(self):
        event = {
            "channel_id": "987654",
            "guild_id": "111",
            "author": {"id": "42", "username": "alice"},
            "content": "大家好",
        }
        data = _to_callback_data(event)
        assert data["chattype"] == "group"

    def test_short_id_from_referenced_message(self):
        """引用回复优先：从被引用消息 content 中提取 [#short_id]。"""
        event = {
            "channel_id": "123456",
            "author": {"id": "42", "username": "alice"},
            "content": "是的",
            "referenced_message": {
                "id": "m0",
                "content": "[#abc12345 项目]\n请确认是否继续？",
            },
        }
        data = _to_callback_data(event)
        assert data["short_id"] == "abc12345"
        assert data["quote"]["text"]["content"].startswith("[#abc12345")

    def test_short_id_from_current_message_when_no_reply(self):
        event = {
            "channel_id": "123456",
            "author": {"id": "42", "username": "alice"},
            "content": "[#cafef00d]\n完成",
        }
        data = _to_callback_data(event)
        assert data["short_id"] == "cafef00d"

    def test_empty_content_ignored(self):
        event = {"channel_id": "123456", "author": {"id": "42", "username": "alice"}, "content": "  "}
        assert _to_callback_data(event) is None


class TestFormatMessage:
    def test_with_project(self):
        assert _format_message("hi", "abc12345", "proj", True).startswith("[#abc12345 proj]")

    def test_without_project(self):
        assert _format_message("hi", "abc12345", None, False).startswith("[#abc12345]")

    def test_wait_reply_hint(self):
        assert "请引用回复此消息" in _format_message("hi", "", None, True)


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_success_tracks_message_id(self, tmp_path):
        """发送成功回传 chat_id，并记录 message_id 供后续消息引用建线程。"""
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["content"].startswith("[#abc12345 proj]\nhi")
            assert "请引用回复此消息" in body["content"]  # wait_reply=True 追加提示
            assert request.headers["Authorization"] == "Bot t"
            assert "message_reference" not in body
            return httpx.Response(200, json={"id": "m99"})

        store = DiscordStore(str(tmp_path / "dc.json"))
        engine = DiscordEngine(bot_key="discord-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({
                "chat_id": "123456",
                "message": "hi",
                "short_id": "abc12345",
                "project_name": "proj",
                "wait_reply": True,
            })
            assert result == {"success": True, "chat_id": "123456"}
            assert engine._last_sent["123456"] == "m99"
        finally:
            await engine._http.aclose()

    @pytest.mark.asyncio
    async def test_send_references_last_message(self, tmp_path):
        """第二条消息以第一条的 message_id 作为 message_reference（线程回复）。"""
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json={"id": f"m{len(calls)}"})

        store = DiscordStore(str(tmp_path / "dc.json"))
        engine = DiscordEngine(bot_key="discord-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await engine.send_message({"chat_id": "123456", "message": "a", "short_id": "", "wait_reply": True})
            await engine.send_message({"chat_id": "123456", "message": "b", "short_id": "", "wait_reply": True})
            assert calls[1]["message_reference"] == {"message_id": "m1"}
        finally:
            await engine._http.aclose()

    @pytest.mark.asyncio
    async def test_send_missing_chat_id(self, tmp_path):
        store = DiscordStore(str(tmp_path / "dc.json"))
        engine = DiscordEngine(bot_key="discord-1", bot_token="t", store=store)
        result = await engine.send_message({"message": "hi", "short_id": "", "wait_reply": True})
        assert result["success"] is False
        assert "chat_id" in result["error"]

    @pytest.mark.asyncio
    async def test_send_api_error(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="Forbidden")

        store = DiscordStore(str(tmp_path / "dc.json"))
        engine = DiscordEngine(bot_key="discord-1", bot_token="t", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({"chat_id": "123456", "message": "hi", "short_id": "", "wait_reply": True})
            assert result["success"] is False
        finally:
            await engine._http.aclose()
