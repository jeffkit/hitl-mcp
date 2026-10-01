"""hitl-engine-agently — HITL Server 外置引擎：Agently Mail（QQ Agent 邮箱）渠道。

安装本包后，entry point 组 ``hitl_server.engines`` 会把 ``descriptor``
注册进引擎注册表，管理台 / 通用 API / MCP GenericEngine 即可通过
``agently-mail`` 渠道收发人工确认。

- 下行：``/api/send`` → ``agently-cli message +send``（主题带 ``[#short_id]`` 标签；
  CLI 服务端要求两阶段确认，封装内自动补 ``--confirmation-token`` 完成发送）。
- 上行：后台轮询 ``agently-cli message +list`` / ``+read``，按发件人 ACL +
  ``[#short_id]`` 标签匹配回复，转 fly-pigeon 兼容结构交 ``storage.handle_callback``。

依赖：``agently-cli``（``@tencent-qqmail/agently-cli``）在 PATH 上，
且已 ``agently-cli auth login`` 完成一次 OAuth（凭据存 macOS 钥匙串）。
"""
from .engine import AgentlyMailEngine, WORKER_TYPE, descriptor

__all__ = ["AgentlyMailEngine", "WORKER_TYPE", "descriptor"]
