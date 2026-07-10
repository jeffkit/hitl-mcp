"""iLink 引擎引用回复提取测试。

覆盖 _extract_short_id_from_refer：iLink 的 refer_item 字段名因版本而异，
提取逻辑需对整个子树做 JSON 序列化后正则搜索 [#short_id]，不依赖具体字段名。
"""
from hitl_server.engines.ilink import _extract_short_id_from_refer, _to_callback_data


class TestExtractShortIdFromRefer:
    def test_extracts_from_content_field(self):
        msg = {"item_list": [{"refer_item": {"content": "[#abc12345 项目] 请确认"}}]}
        assert _extract_short_id_from_refer(msg) == "abc12345"

    def test_extracts_from_unknown_field_via_subtree_search(self):
        """字段名不在已知列表（content/displayname/text）时，仍能从子树命中。"""
        msg = {
            "item_list": [
                {"refer_item": {"display_content": "[#deadbeef] hello", "type": 49}}
            ]
        }
        assert _extract_short_id_from_refer(msg) == "deadbeef"

    def test_extracts_from_nested_text_item(self):
        msg = {
            "item_list": [
                {"refer_item": {"item_list": [{"text_item": {"text": "[#feedface 项目X]\n正文"}}]}}
            ]
        }
        assert _extract_short_id_from_refer(msg) == "feedface"

    def test_returns_none_when_no_refer_item(self):
        msg = {"item_list": [{"text_item": {"text": "普通消息"}}]}
        assert _extract_short_id_from_refer(msg) is None

    def test_returns_none_when_no_short_id_in_refer(self):
        msg = {"item_list": [{"refer_item": {"content": "被引用的消息没有 short_id"}}]}
        assert _extract_short_id_from_refer(msg) is None

    def test_skips_non_refer_items(self):
        msg = {
            "item_list": [
                {"text_item": {"text": "[#abc12345] 不应被这条命中"}},
                {"refer_item": {"content": "[#cafef00d 项目] 真正被引用的"}},
            ]
        }
        assert _extract_short_id_from_refer(msg) == "cafef00d"


class TestToCallbackDataShortId:
    def test_short_id_field_populated_on_quote_reply(self):
        msg = {
            "from_user_id": "wx_user_1",
            "context_token": "ctx",
            "text": "是的",
            "raw": {
                "item_list": [
                    {"text_item": {"text": "是的"}},
                    {"refer_item": {"content": "[#abc12345 项目] 请确认是否继续？\n\n> 请引用回复此消息"}},
                ],
            },
        }
        from hitl_server.engines.ilink import UserMessage

        data = _to_callback_data(UserMessage("wx_user_1", "ctx", "是的", msg["raw"]))
        assert data["short_id"] == "abc12345"
        assert data["quote"]["text"]["content"].startswith("[#abc12345")
