"""
管理台 API 处理器（精简版）。

本地 HITL Server 场景下，管理台只做两件事：
1. 引擎管理：通用 /api/engines/{type}/start|stop 端点 + 渠道 descriptor 注册的
   特有路由（如 ilink 的 qr/status）
2. 会话调试：查看本地 HIL 会话状态

引擎清单来自 engines/registry（内置 + entry point 插件）：新增渠道无需修改
本文件——渠道装配逻辑在各渠道 descriptor 里（见 engines/builtin.py 与
docs/engine-plugins.md）。

已移除：登录鉴权、Forward Service 代理、Bot 管理、Worker 管理、空闲提示配置等
旧场景（远端 HITL Server + 企微群机器人 + Agent Studio）的功能。
本地服务只绑 127.0.0.1，管理台开箱即用，无需登录。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ValidationError

from ..config import config
from ..storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ============== 数据模型（旧端点兼容层） ==============

class WecomAibotEngineStartRequest(BaseModel):
    bot_id: str = ""
    bot_secret: str = ""
    bot_key: str = "wecom-aibot-1"


class IlinkEngineStartRequest(BaseModel):
    bot_key: Optional[str] = None   # 缺省用 config.ilink_bot_key
    base_url: Optional[str] = None  # 缺省用 config.ilink_base_url


class TelegramEngineStartRequest(BaseModel):
    bot_token: str
    bot_key: str = "telegram-1"
    poll_timeout: int = 30


class DiscordEngineStartRequest(BaseModel):
    bot_token: str
    bot_key: str = "discord-1"


class FeishuEngineStartRequest(BaseModel):
    app_id: str
    app_secret: str
    bot_key: str = "feishu-1"


#: 旧渠道端点 → descriptor 名（端点保留以兼容管理台/TS 客户端，实现已通用化）
_LEGACY_START_MODELS: Dict[str, type[BaseModel]] = {
    "ilink": IlinkEngineStartRequest,
    "wecom-aibot": WecomAibotEngineStartRequest,
    "telegram": TelegramEngineStartRequest,
    "discord": DiscordEngineStartRequest,
    "feishu": FeishuEngineStartRequest,
}


def _engine_context():
    from ..engines import EngineContext
    return EngineContext(config=config, storage=storage)


# ============== 页面路由 ==============

@router.get("")
async def admin_page():
    """管理台入口 - 重定向到 console SPA。"""
    return RedirectResponse(url="/console", status_code=302)


# ============== 内置引擎管理 API（通用） ==============

@router.get("/api/engines")
async def list_engines():
    """列出所有已注册内置引擎及其状态。"""
    from ..engines import engine_manager
    return {"engines": engine_manager.status_all()}


@router.get("/api/engines/registry")
async def list_engine_registry():
    """列出注册表中全部可用渠道（内置 + 外置插件）及其凭证字段。"""
    from ..engines import all_descriptors
    return {
        "engines": [
            {
                "name": d.name,
                "title": d.title,
                "credentials": d.credentials,
                "source": d.source,
            }
            for d in all_descriptors()
        ]
    }


async def _start_engine(etype: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """通用动态启动：查 descriptor → 校验参数 → start → 返回状态。"""
    from ..engines import get_descriptor, engine_manager

    descriptor = get_descriptor(etype)
    if not descriptor:
        raise HTTPException(status_code=404, detail=f"未知引擎类型: {etype}")

    if descriptor.request_model:
        try:
            params = descriptor.request_model(**body).model_dump(exclude_unset=True)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
    else:
        params = body

    result = await descriptor.start(_engine_context(), params)
    if isinstance(result, dict) and result.get("success") is False:
        # descriptor 明确报告失败（如缺凭证）；维持旧端点语义原样返回
        return result

    # 通用编排：停旧实例 → 挂回调 → 注册 → 启动
    engine = result
    existing = engine_manager.get_by_bot_key(engine.bot_key)
    if existing:
        await existing.stop()
        engine_manager.remove(engine.bot_key)
    engine.on_user_message = storage.handle_callback
    engine_manager.register(engine)
    await engine.start()
    logger.info(f"管理台启动 {descriptor.title} 引擎: bot_key={engine.bot_key}")
    return {"success": True, "engine": engine.status()}


async def _stop_engine(etype: str, bot_key: str = "") -> Dict[str, Any]:
    from ..engines import engine_manager

    engine = engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type(etype)
    if engine:
        await engine.stop()
        engine_manager.remove(engine.bot_key)
        logger.info(f"管理台停止 {etype} 引擎: bot_key={engine.bot_key}")
        return {"success": True}
    return {"success": False, "error": "引擎未注册"}


@router.post("/api/engines/{etype}/start")
async def engines_start(etype: str, request: Request):
    """通用引擎动态启动端点（任何注册表中的渠道均可用，无需新增端点）。

    请求体为该渠道 descriptor 声明的凭证字段（见 GET /api/engines/registry）。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await _start_engine(etype, body if isinstance(body, dict) else {})


@router.post("/api/engines/{etype}/stop")
async def engines_stop(etype: str, bot_key: str = ""):
    """通用引擎停止端点（保留持久化凭证，重启后可自动恢复的渠道仍会恢复）。"""
    return await _stop_engine(etype, bot_key)


# ============== 旧渠道端点（兼容层，实现已走通用路径） ==============

@router.post("/api/engines/ilink/start")
async def engines_ilink_start(request: IlinkEngineStartRequest):
    """动态注册并启动 iLink 内置引擎（未在配置中启用时也可由此拉起）。"""
    return await _start_engine("ilink", request.model_dump(exclude_none=True))


@router.post("/api/engines/wecom-aibot/start")
async def engines_wecom_aibot_start_admin(request: WecomAibotEngineStartRequest):
    """注册并启动 WeCom AI Bot 内置引擎（bot_secret/bot_id 可留空走持久化恢复）。"""
    return await _start_engine("wecom-aibot", request.model_dump())


@router.post("/api/engines/wecom-aibot/stop")
async def engines_wecom_aibot_stop_admin(bot_key: str = "wecom-aibot-1"):
    """停止并注销 WeCom AI Bot 引擎（保留持久化凭证，重启后仍会自动恢复）。"""
    return await _stop_engine("wecom-aibot", bot_key)


@router.post("/api/engines/telegram/start")
async def engines_telegram_start(request: TelegramEngineStartRequest):
    """注册并启动 Telegram Bot 内置引擎。"""
    return await _start_engine("telegram", request.model_dump())


@router.post("/api/engines/telegram/stop")
async def engines_telegram_stop(bot_key: str = "telegram-1"):
    """停止 Telegram 引擎。"""
    return await _stop_engine("telegram", bot_key)


@router.post("/api/engines/discord/start")
async def engines_discord_start(request: DiscordEngineStartRequest):
    """注册并启动 Discord Gateway 内置引擎。"""
    return await _start_engine("discord", request.model_dump())


@router.post("/api/engines/discord/stop")
async def engines_discord_stop(bot_key: str = "discord-1"):
    """停止 Discord 引擎。"""
    return await _stop_engine("discord", bot_key)


@router.post("/api/engines/feishu/start")
async def engines_feishu_start(request: FeishuEngineStartRequest):
    """注册并启动飞书内置引擎（需 pip install lark-oapi）。"""
    return await _start_engine("feishu", request.model_dump())


@router.post("/api/engines/feishu/stop")
async def engines_feishu_stop(bot_key: str = "feishu-1"):
    """停止飞书引擎（凭证保留，重启后自动恢复）。"""
    return await _stop_engine("feishu", bot_key)


# ============== 渠道 descriptor 特有路由（如 ilink qr/status） ==============

def register_descriptor_routes() -> None:
    """把各渠道 descriptor 的特有路由追加到 admin router（app 启动时调用一次）。"""
    from ..engines import all_descriptors

    for descriptor in all_descriptors():
        if descriptor.extra_routes:
            descriptor.extra_routes(router)


register_descriptor_routes()


# ============== HIL 会话查询 API ==============

@router.get("/api/hil/sessions")
async def get_hil_sessions():
    """获取本地 HITL Server 会话列表（调试用）。"""
    sessions = []
    for session in storage._sessions.values():
        sessions.append({
            "session_id": session.session_id,
            "short_id": session.short_id,
            "chat_id": session.chat_id,
            "chat_type": session.chat_type,
            "message": session.message[:100] + "..." if len(session.message) > 100 else session.message,
            "project_name": session.project_name,
            "status": session.status,
            "replies_count": len(session.replies),
            "created_at": session.created_at.isoformat(),
            "expire_at": session.expire_at.isoformat()
        })
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return {"total": len(sessions), "sessions": sessions[:50]}
