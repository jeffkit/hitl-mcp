"""飞书内置引擎单元测试。

覆盖：
  1. _parse_message_content：text / post 富文本 / 非 JSON content 的文本提取。
  2. _to_callback_data：p2p/群聊 chattype、parent_id → ref_msg_id、short-id 提取。
  3. send_message：httpx.MockTransport 模拟 token 与发消息 API，校验载荷与鉴权头。
"""
import json

import httpx
import pytest

from hitl_server.engines.feishu import (
    FeishuEngine,
    FeishuStore,
    _format_message,
    _parse_message_content,
    _to_callback_data,
)


class TestParseMessageContent:
    def test_text_message(self):
        message = {"msg_type": "text", "body": {"content": '{"text": "你好"}'}}
        assert _parse_message_content(message) == "你好"

    def test_post_rich_text(self):
        message = {
            "msg_type": "post",
            "body": {
                "content": json.dumps({
                    "zh_cn": {
                        "content": [
                            [{"tag": "text", "text": "第一段"}],
                            [{"tag": "text", "text": "第二段"}],
                        ]
                    }
                })
            },
        }
        assert _parse_message_content(message) == "第一段 第二段"

    def test_non_json_content_returned_raw(self):
        message = {"msg_type": "unknown", "body": {"content": "raw string"}}
        assert _parse_message_content(message) == "raw string"


class TestToCallbackData:
    def test_p2p_chat(self):
        event = {
            "message": {
                "chat_id": "oc_123",
                "chat_type": "p2p",
                "msg_type": "text",
                "body": {"content": '{"text": "你好"}'},
            }
        }
        sender = {"sender_id": {"open_id": "ou_42"}}
        data = _to_callback_data(event, sender)
        assert data["chatid"] == "ou_42"
        assert data["chattype"] == "single"
        assert data["text"]["content"] == "你好"
        assert data["from"]["userid"] == "ou_42"

    def test_group_chat(self):
        event = {
            "message": {
                "chat_id": "oc_grp",
                "chat_type": "group",
                "msg_type": "text",
                "body": {"content": '{"text": "大家好"}'},
            }
        }
        sender = {"sender_id": {"open_id": "ou_42"}}
        data = _to_callback_data(event, sender)
        assert data["chattype"] == "group"

    def test_short_id_from_current_message(self):
        event = {
            "message": {
                "chat_id": "oc_123",
                "chat_type": "p2p",
                "msg_type": "text",
                "body": {"content": '{"text": "[#abc12345 项目]\n完成"}'},
            }
        }
        sender = {"sender_id": {"open_id": "ou_42"}}
        data = _to_callback_data(event, sender)
        assert data["short_id"] == "abc12345"

    def test_thread_reply_sets_ref_msg_id(self):
        """线程回复（parent_id）作为 ref_msg_id 交给 storage 做 L0 精确匹配。"""
        event = {
            "message": {
                "chat_id": "oc_123",
                "chat_type": "p2p",
                "parent_id": "om_thread_parent",
                "msg_type": "text",
                "body": {"content": '{"text": "是的"}'},
            }
        }
        sender = {"sender_id": {"open_id": "ou_42"}}
        data = _to_callback_data(event, sender)
        assert data["ref_msg_id"] == "om_thread_parent"

    def test_empty_content_ignored(self):
        event = {"message": {"chat_id": "oc_1", "chat_type": "p2p", "msg_type": "text", "body": {"content": '{"text": "  "}'}}}
        sender = {"sender_id": {"open_id": "ou_42"}}
        assert _to_callback_data(event, sender) is None


class TestFormatMessage:
    def test_with_project(self):
        assert _format_message("hi", "abc12345", "proj", True).startswith("[#abc12345 proj]")

    def test_without_project(self):
        assert _format_message("hi", "abc12345", None, False).startswith("[#abc12345]")

    def test_wait_reply_hint(self):
        assert "请回复此消息" in _format_message("hi", "", None, True)


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_success(self, tmp_path):
        """发送成功回传 chat_id；token 请求带 App 凭证，发消息带 Bearer 鉴权。"""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/v3/app_access_token/internal"):
                body = json.loads(request.content)
                assert body == {"app_id": "cli_x", "app_secret": "sec"}
                return httpx.Response(200, json={"code": 0, "app_access_token": "tok", "expire": 7200})
            if request.url.path.endswith("/im/v1/messages"):
                sent = json.loads(request.content)
                assert request.headers["Authorization"] == "Bearer tok"
                assert sent["receive_id"] == "ou_42"
                assert "[#abc12345 proj]" in json.loads(sent["content"])["text"]
                return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_99"}})
            return httpx.Response(500)

        store = FeishuStore(str(tmp_path / "fs.json"))
        engine = FeishuEngine(bot_key="feishu-1", app_id="cli_x", app_secret="sec", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({
                "chat_id": "ou_42",
                "message": "hi",
                "short_id": "abc12345",
                "project_name": "proj",
                "wait_reply": True,
            })
            assert result == {"success": True, "chat_id": "ou_42"}
        finally:
            await engine._http.aclose()

    @pytest.mark.asyncio
    async def test_send_missing_chat_id(self, tmp_path):
        store = FeishuStore(str(tmp_path / "fs.json"))
        engine = FeishuEngine(bot_key="feishu-1", app_id="cli_x", app_secret="sec", store=store)
        result = await engine.send_message({"message": "hi", "short_id": "", "wait_reply": True})
        assert result["success"] is False
        assert "chat_id" in result["error"]

    @pytest.mark.asyncio
    async def test_send_token_error(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 99991663, "msg": "invalid app secret"})

        store = FeishuStore(str(tmp_path / "fs.json"))
        engine = FeishuEngine(bot_key="feishu-1", app_id="cli_x", app_secret="bad", store=store)
        engine._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await engine.send_message({"chat_id": "ou_42", "message": "hi", "short_id": "", "wait_reply": True})
            assert result["success"] is False
        finally:
            await engine._http.aclose()
