"""
管理台 API 处理器（精简版）。

本地 HITL Server 场景下，管理台只做两件事：
1. 引擎管理：扫码启用 iLink、填凭证启用 WeCom AI Bot
2. 会话调试：查看本地 HIL 会话状态

已移除：登录鉴权、Forward Service 代理、Bot 管理、Worker 管理、空闲提示配置等
旧场景（远端 HITL Server + 企微群机器人 + Agent Studio）的功能。
本地服务只绑 127.0.0.1，管理台开箱即用，无需登录。
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..config import config
from ..storage import storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ============== 数据模型 ==============

class WecomAibotEngineStartRequest(BaseModel):
    bot_id: str = ""
    bot_secret: str = ""
    bot_key: str = "wecom-aibot-1"


class IlinkEngineStartRequest(BaseModel):
    bot_key: Optional[str] = None  # 缺省用 config.ilink_bot_key


# ============== 页面路由 ==============

@router.get("")
async def admin_page():
    """管理台入口 - 重定向到 console SPA。"""
    return RedirectResponse(url="/console", status_code=302)


# ============== 内置引擎管理 API ==============

@router.get("/api/engines")
async def list_engines():
    """列出所有已注册内置引擎及其状态。"""
    from ..engines import engine_manager
    return {"engines": engine_manager.status_all()}


@router.post("/api/engines/ilink/start")
async def engines_ilink_start(request: IlinkEngineStartRequest):
    """动态注册并启动 iLink 内置引擎（未在配置中启用时也可由此拉起）。"""
    from ..engines import engine_manager, ILinkEngine

    bot_key = request.bot_key or config.ilink_bot_key
    existing = engine_manager.get_by_bot_key(bot_key)
    if existing:
        await existing.stop()
        engine_manager.remove(bot_key)

    token_store_path = config.ilink_token_store_path or os.path.join(
        os.path.expanduser("~"), ".hil-mcp", "ilink_store.json"
    )
    engine = ILinkEngine(
        bot_key=bot_key,
        base_url=config.ilink_base_url,
        token_store_path=token_store_path,
        poll_timeout=config.ilink_poll_timeout,
    )
    engine.on_user_message = storage.handle_callback
    engine_manager.register(engine)
    await engine.start()
    logger.info(f"管理台启动 iLink 引擎: bot_key={bot_key}")
    return {"success": True, "engine": engine.status()}


@router.get("/api/engines/ilink/qr")
async def engines_ilink_qr(bot_key: str = ""):
    """获取 iLink 登录二维码（扫码后状态通过 /engines/ilink/status 轮询）。"""
    from ..engines import engine_manager
    engine = engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type("ilink")
    if not engine:
        raise HTTPException(status_code=404, detail="iLink 引擎未启动，请先点击「启动引擎」")
    return await engine.get_qr()


@router.get("/api/engines/ilink/status")
async def engines_ilink_status(bot_key: str = ""):
    """查询 iLink 引擎登录状态与已激活用户。"""
    from ..engines import engine_manager
    engine = engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type("ilink")
    if not engine:
        return {
            "worker_type": "ilink",
            "running": False,
            "logged_in": False,
            "login_status": "not_started",
            "activated_users": [],
        }
    return engine.status()


@router.post("/api/engines/wecom-aibot/start")
async def engines_wecom_aibot_start_admin(request: WecomAibotEngineStartRequest):
    """注册并启动 WeCom AI Bot 内置引擎。

    - bot_secret 可留空：此时从持久化 store 按 bot_key 读取已保存的 secret（用于「重启」）。
    - bot_id 也可留空：同样从 store 读取（重启时前端不必回显也能重启）。
    - 若请求带了凭证，则以其为准并落盘（覆盖旧值）。
    """
    from ..engines import engine_manager, WecomAibotEngine, WecomAibotStore

    bot_key = request.bot_key or "wecom-aibot-1"
    existing = engine_manager.get_by_bot_key(bot_key)
    if existing:
        await existing.stop()
        engine_manager.remove(bot_key)

    store_path = config.wecom_aibot_store_path or os.path.join(
        os.path.expanduser("~"), ".hil-mcp", "wecom_aibot_store.json"
    )
    store = WecomAibotStore(store_path)

    bot_id = request.bot_id
    bot_secret = request.bot_secret
    # 请求未带凭证 → 从持久化 store 补齐（重启场景）
    if not bot_id or not bot_secret:
        persisted = store.get_credentials()
        if persisted:
            bot_id = bot_id or persisted["bot_id"]
            bot_secret = bot_secret or persisted["bot_secret"]
            bot_key = bot_key or persisted["bot_key"]
    if not bot_id or not bot_secret:
        return {"success": False, "error": "缺少 Bot ID/Secret，且本地无已保存凭证；请填写后再启动。"}

    # 落盘（请求带凭证时覆盖；重启时也刷新一遍，保持一致）
    store.set_credentials(bot_id, bot_secret, bot_key)

    engine = WecomAibotEngine(
        bot_key=bot_key,
        bot_id=bot_id,
        bot_secret=bot_secret,
        ws_url=config.wecom_aibot_ws_url,
        heartbeat_interval=config.wecom_aibot_heartbeat_interval,
        reconnect_delay=config.wecom_aibot_reconnect_delay,
    )
    engine.on_user_message = storage.handle_callback
    engine_manager.register(engine)
    await engine.start()
    logger.info(f"管理台启动 WeCom AI Bot 引擎: bot_key={bot_key}, bot_id={bot_id}")
    return {"success": True, "engine": engine.status()}


@router.post("/api/engines/wecom-aibot/stop")
async def engines_wecom_aibot_stop_admin(bot_key: str = "wecom-aibot-1"):
    """停止并注销 WeCom AI Bot 引擎（保留持久化凭证，重启后仍会自动恢复）。"""
    from ..engines import engine_manager

    engine = engine_manager.get_by_bot_key(bot_key)
    if engine:
        await engine.stop()
        engine_manager.remove(bot_key)
        logger.info(f"管理台停止 WeCom AI Bot 引擎: bot_key={bot_key}（凭证保留，重启自动恢复）")
        return {"success": True}
    return {"success": False, "error": "引擎未注册"}


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
