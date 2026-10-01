"""hitl-engine-agently 单元测试。

不依赖真实 agently-cli / hitl-server 存储：
- 子进程封装用 tests/stub_agently_cli.py 桩进程验证（含两阶段发送握手）；
- 引擎行为用进程内 FakeCLI 验证（基线建档 / ACL / 标签匹配 / 回灌结构）。

运行：cd packages/hitl-server && uv run pytest ../hitl-engine-agently/tests/ -v
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from hitl_engine_agently.cli import AgentlyCli, AgentlyCliError, html_to_text  # noqa: E402
from hitl_engine_agently.engine import (  # noqa: E402
    AgentlyMailEngine,
    _extract_short_id,
    _normalize_senders,
    _start,
)

STUB = str(Path(__file__).resolve().parent / "stub_agently_cli.py")

SID = "a1b2c3d4"
MSG_ID = "msg_test_1"


def make_store(tmp_path, bot_key="agently-mail-1"):
    from hitl_engine_agently.store import AgentlyMailStore

    return AgentlyMailStore(str(tmp_path / f"agently_mail_{bot_key}.json"))


def make_engine(tmp_path, fake_cli, recipient="owner@example.com", allowed=None):
    return AgentlyMailEngine(
        bot_key="agently-mail-1",
        cli=fake_cli,
        store=make_store(tmp_path),
        default_recipient=recipient,
        allowed_senders=allowed,
        poll_interval=30,
    )


class FakeCLI:
    """进程内桩：替代 AgentlyCli，脚本化 list/read 输出并记录 send。"""

    def __init__(self):
        self.inbox: list[dict] = []
        self.bodies: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.fail_send: AgentlyCliError | None = None

    async def list_inbox(self, limit=20):
        return list(self.inbox)

    async def read(self, message_id):
        return self.bodies.get(message_id, {"body": "", "body_format": "TEXT"})

    async def send(self, to, subject, body):
        if self.fail_send:
            raise self.fail_send
        self.sent.append({"to": list(to), "subject": subject, "body": body})
        return {}

    async def me(self):
        return {"aliases": [{"email": "kongjie@agent.qq.com", "is_primary": True}]}


# ── cli.py：子进程封装（真实桩进程） ─────────────────────────────────────────

def test_cli_run_parses_envelope(tmp_path):
    cli = AgentlyCli(cli_path=sys.executable, timeout=15)
    # stub 约定：argv = [python, stub.py, <原参数...>, --stub-script, script.json]
    script = tmp_path / "script.json"
    script.write_text(json.dumps([{"args": ["+me"], "stdout": {"ok": True, "data": {"aliases": []}}, "exit": 0}]))
    envelope = asyncio.run(cli.run(STUB, "+me", "--stub-script", str(script)))
    assert envelope["ok"] is True


def test_cli_run_raises_with_code_and_envelope(tmp_path):
    cli = AgentlyCli(cli_path=sys.executable, timeout=15)
    script = tmp_path / "script.json"
    script.write_text(json.dumps([
        {
            "args": ["message", "+list"],
            "stdout": {"ok": False, "error": {"message": "refresh token is invalid"}},
            "exit": 3,
        }
    ]))
    with pytest.raises(AgentlyCliError) as ei:
        asyncio.run(cli.run(STUB, "message", "+list", "--stub-script", str(script)))
    assert ei.value.code == 3
    assert ei.value.envelope["error"]["message"].startswith("refresh")


def test_cli_send_two_phase_handshake(tmp_path):
    """首次发送 exit 8 并返回 ctk_ 令牌 → 自动带 --confirmation-token 重发。"""
    cli = AgentlyCli(cli_path=sys.executable, timeout=15)
    calls: list[list[str]] = []

    # 手写桩脚本：记录 argv 到 calls.json，第一次 exit 8，第二次 exit 0
    stub = tmp_path / "two_phase_stub.py"
    calls_path = str(tmp_path / "calls.json")
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        f"calls_path = r'{calls_path}'\n"
        "try:\n"
        "    calls = json.load(open(calls_path))\n"
        "except Exception:\n"
        "    calls = []\n"
        "calls.append(sys.argv[1:])\n"
        "json.dump(calls, open(calls_path, 'w'))\n"
        "first = not any('--confirmation-token' in a for a in sys.argv[1:])\n"
        "if first:\n"
        "    print(json.dumps({'ok': False, 'error': {'message': '需要确认'}, 'data': {'confirmation_token': 'ctk_test123', 'summary': '发给 a@b.com'}}))\n"
        "    sys.exit(8)\n"
        "print(json.dumps({'ok': True, 'data': {'message_id': 'msg_x'}}))\n"
    )
    stub.chmod(0o755)
    cli.cli_path = str(stub)
    data = asyncio.run(cli.send(to=["a@b.com"], subject="[#a1b2c3d4] HITL 确认请求", body="请确认"))
    assert data == {"message_id": "msg_x"}
    calls = json.load(open(tmp_path / "calls.json"))
    assert len(calls) == 2
    assert "--confirmation-token" in calls[1]
    assert "ctk_test123" in calls[1]


def test_cli_send_confirmation_required_in_envelope(tmp_path):
    """CLI 1.0.5 实测形状：exit 0 + data.confirmation_required → 仍须带 token 重发。

    回归：此前把该响应当作发送成功，导致引擎报成功而邮件未发出。
    """
    stub = tmp_path / "envelope_stub.py"
    calls_path = str(tmp_path / "calls.json")
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        f"calls_path = r'{calls_path}'\n"
        "try:\n"
        "    calls = json.load(open(calls_path))\n"
        "except Exception:\n"
        "    calls = []\n"
        "calls.append(sys.argv[1:])\n"
        "json.dump(calls, open(calls_path, 'w'))\n"
        "first = not any('--confirmation-token' in a for a in sys.argv[1:])\n"
        "if first:\n"
        "    print(json.dumps({'ok': True, 'data': {'confirmation_required': True, "
        "'confirmation_token': 'ctk_env456', 'message': 'This action requires confirmation.'}}))\n"
        "    sys.exit(0)\n"
        "print(json.dumps({'ok': True, 'data': {'message_id': 'msg_y'}}))\n"
    )
    stub.chmod(0o755)
    cli = AgentlyCli(cli_path=str(stub), timeout=15)
    data = asyncio.run(cli.send(to=["a@b.com"], subject="[#a1b2c3d4] t", body="b"))
    assert data == {"message_id": "msg_y"}
    calls = json.load(open(calls_path))
    assert len(calls) == 2
    assert "ctk_env456" in calls[1]


def test_html_to_text_strips_tags_and_entities():
    html = "<style>.x{}</style><p>同意&nbsp;&amp;执行</p><div>第二行</div>"
    text = html_to_text(html)
    assert ".x{}" not in text
    assert "同意 &执行" in text
    assert "第二行" in text


# ── engine.py：行为 ──────────────────────────────────────────────────────────

def test_extract_short_id():
    assert _extract_short_id("Re: [#a1b2c3d4 infra4agent] HITL 确认请求") == "a1b2c3d4"
    assert _extract_short_id("Re: [#a1b2c3d4]") == "a1b2c3d4"
    assert _extract_short_id("普通邮件主题") is None
    assert _extract_short_id("[#too-short]") is None


def test_normalize_senders_defaults_and_dedup():
    assert _normalize_senders(None, "A@x.com") == ["a@x.com"]
    assert _normalize_senders("b@x.com, c@x.com", "a@x.com") == ["b@x.com", "c@x.com", "a@x.com"]


@pytest.mark.asyncio
async def test_baseline_poll_records_without_callback(tmp_path):
    cli = FakeCLI()
    cli.inbox = [{"message_id": MSG_ID, "subject": f"[#{SID} p] 旧邮件", "from": {"email": "owner@example.com"}, "snippet": ""}]
    engine = make_engine(tmp_path, cli)
    got = []
    engine.on_user_message = lambda cb: got.append(cb) or asyncio.sleep(0)
    await engine._poll_once()  # 首轮 = 基线
    assert got == []
    assert MSG_ID in engine._seen


@pytest.mark.asyncio
async def test_matching_reply_triggers_callback(tmp_path):
    cli = FakeCLI()
    engine = make_engine(tmp_path, cli)
    got = []
    engine.on_user_message = lambda cb: got.append(cb) or asyncio.sleep(0)

    cli.inbox = [{"message_id": MSG_ID, "subject": "旧邮件", "from": {"email": "owner@example.com"}, "snippet": ""}]
    await engine._poll_once()  # 建基线

    reply_id = "msg_reply_1"
    cli.inbox = [
        {"message_id": MSG_ID, "subject": "旧邮件", "from": {"email": "owner@example.com"}, "snippet": ""},
        {"message_id": reply_id, "subject": f"Re: [#{SID} p] HITL 确认请求",
         "from": {"email": "Owner@example.com", "name": "主人"}, "snippet": ""},
    ]
    cli.bodies[reply_id] = {"body": "<p>同意，执行吧</p>", "body_format": "HTML"}
    await engine._poll_once()

    assert len(got) == 1
    cb = got[0]
    assert cb["short_id"] == SID
    assert cb["chatid"] == "owner@example.com"
    assert cb["text"]["content"] == "同意，执行吧"
    assert cb["from"]["userid"] == "owner@example.com"


@pytest.mark.asyncio
async def test_non_whitelisted_sender_rejected(tmp_path):
    cli = FakeCLI()
    engine = make_engine(tmp_path, cli, allowed=["owner@example.com"])
    got = []
    engine.on_user_message = lambda cb: got.append(cb) or asyncio.sleep(0)
    cli.inbox = [{"message_id": "m0", "subject": "旧", "from": {"email": "owner@example.com"}}]
    await engine._poll_once()

    cli.inbox = [
        {"message_id": "m0", "subject": "旧", "from": {"email": "owner@example.com"}},
        {"message_id": "m1", "subject": f"[#{SID}] 假装确认",
         "from": {"email": "attacker@evil.com", "name": "攻击者"}, "snippet": ""},
    ]
    await engine._poll_once()
    assert got == []  # 被 ACL 拦下，不回灌


@pytest.mark.asyncio
async def test_unrelated_mail_ignored(tmp_path):
    cli = FakeCLI()
    engine = make_engine(tmp_path, cli)
    got = []
    engine.on_user_message = lambda cb: got.append(cb) or asyncio.sleep(0)
    cli.inbox = [{"message_id": "m0", "subject": "账单", "from": {"email": "owner@example.com"}}]
    await engine._poll_once()
    cli.inbox = [
        {"message_id": "m0", "subject": "账单", "from": {"email": "owner@example.com"}},
        {"message_id": "m1", "subject": "本周天气", "from": {"email": "admin@agent.qq.com"}, "snippet": "广州天气"},
    ]
    await engine._poll_once()
    assert got == []


@pytest.mark.asyncio
async def test_send_message_formats_subject_and_pinned_recipient(tmp_path):
    cli = FakeCLI()
    engine = make_engine(tmp_path, cli, recipient="boss@example.com")
    result = await engine.send_message(
        {"short_id": SID, "message": "要删除生产表，请确认", "project_name": "infra4agent", "chat_id": ""}
    )
    assert result == {"success": True, "chat_id": "boss@example.com"}
    assert len(cli.sent) == 1
    sent = cli.sent[0]
    assert sent["to"] == ["boss@example.com"]
    assert sent["subject"].startswith(f"[#{SID} infra4agent]")
    assert "要删除生产表" in sent["body"]
    assert f"[#{SID}]" in sent["body"]  # 回复指引保留标记


@pytest.mark.asyncio
async def test_send_message_cli_error_surfaced(tmp_path):
    cli = FakeCLI()
    cli.fail_send = AgentlyCliError(3, "refresh token is invalid")
    engine = make_engine(tmp_path, cli)
    result = await engine.send_message({"short_id": SID, "message": "x", "chat_id": "boss@example.com"})
    assert result["success"] is False
    assert "exit=3" in result["error"]
    assert engine._auth_ok is False


def test_descriptor_start_validates_recipient(tmp_path):
    sp = str(tmp_path / "s.json")
    ok = _start(None, {"default_recipient": "boss@example.com", "poll_interval_seconds": 45, "store_path": sp})
    assert isinstance(ok, AgentlyMailEngine)  # 成功路径返回引擎实例，编排交给 admin._start_engine
    assert ok.bot_key == "agently-mail-1"

    bad = _start(None, {"default_recipient": "not-an-email", "store_path": sp})
    assert bad == {"success": False, "error": "default_recipient 必填且需为合法邮箱（审批人地址）"}

    bad2 = _start(None, {"default_recipient": "boss@example.com", "poll_interval_seconds": "abc", "store_path": sp})
    assert bad2["success"] is False


def test_descriptor_start_persists_config(tmp_path):
    store_path = tmp_path / "s.json"
    ok = _start(None, {
        "default_recipient": "boss@example.com",
        "allowed_senders": "boss@example.com, alice@x.com",
        "store_path": str(store_path),
        "bot_key": "agently-mail-t1",
    })
    assert isinstance(ok, AgentlyMailEngine)
    from hitl_engine_agently.store import AgentlyMailStore

    cfg = AgentlyMailStore(str(store_path)).get_config()
    assert isinstance(ok, AgentlyMailEngine)
    assert cfg["default_recipient"] == "boss@example.com"
    assert "alice@x.com" in cfg["allowed_senders"]
