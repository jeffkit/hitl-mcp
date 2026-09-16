"""内置渠道的 EngineDescriptor 装配逻辑。

每个 descriptor 把原先散落在 app.py lifespan / admin.py 的渠道专属装配
（env 读取、持久化凭证恢复、管理台动态启动）收敛到渠道自己的注册单元里。
核心（app.py / admin.py）只面向 registry.EngineDescriptor 编排。

新增内置渠道：在本文件追加一个 descriptor，并加进 ``BUILTIN_DESCRIPTORS``。
外置渠道：打包 wheel + entry point 组 ``hitl_server.engines``（无需改本仓）。
"""
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ..config import config
from .manager import engine_manager
from .registry import EngineContext, EngineDescriptor

logger = logging.getLogger(__name__)

DEFAULT_STORE_DIR = os.path.join(os.path.expanduser("~"), ".hil-mcp")


def _store_path(override: Optional[str], filename: str) -> str:
    return override or os.path.join(DEFAULT_STORE_DIR, filename)




# ════════════════════════════ iLink ════════════════════════════

def _ilink_build_startup(ctx: EngineContext):
    if not ctx.config.enable_ilink_engine:
        return None
    from .ilink import ILinkEngine

    engine = ILinkEngine(
        bot_key=ctx.config.ilink_bot_key,
        base_url=ctx.config.ilink_base_url,
        token_store_path=_store_path(ctx.config.ilink_token_store_path, "ilink_store.json"),
        poll_timeout=ctx.config.ilink_poll_timeout,
    )
    logger.info(
        f"  [内置引擎] iLink 已启用: bot_key={ctx.config.ilink_bot_key}, base={ctx.config.ilink_base_url}"
    )
    return engine


def _ilink_start(ctx: EngineContext, params: Dict[str, Any]):
    from .ilink import ILinkEngine

    bot_key = params.get("bot_key") or ctx.config.ilink_bot_key
    engine = ILinkEngine(
        bot_key=bot_key,
        base_url=params.get("base_url") or ctx.config.ilink_base_url,
        token_store_path=_store_path(ctx.config.ilink_token_store_path, "ilink_store.json"),
        poll_timeout=ctx.config.ilink_poll_timeout,
    )
    return engine


def _ilink_extra_routes(router: APIRouter) -> None:
    """iLink 渠道特有路由：扫码登录二维码与登录状态。"""

    @router.get("/api/engines/ilink/qr")
    async def engines_ilink_qr(bot_key: str = ""):
        """获取 iLink 登录二维码（扫码后状态通过 /engines/ilink/status 轮询）。"""
        engine = engine_manager.get_by_bot_key(bot_key) or engine_manager.get_by_type("ilink")
        if not engine:
            raise HTTPException(status_code=404, detail="iLink 引擎未启动，请先点击「启动引擎」")
        return await engine.get_qr()

    @router.get("/api/engines/ilink/status")
    async def engines_ilink_status(bot_key: str = ""):
        """查询 iLink 引擎登录状态与已激活用户。"""
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


ilink_descriptor = EngineDescriptor(
    name="ilink",
    title="iLink（个人微信 ClawBot）",
    build_startup=_ilink_build_startup,
    start=_ilink_start,
    credentials=["bot_key", "base_url"],
    extra_routes=_ilink_extra_routes,
)


# ════════════════════════════ WeCom AI Bot ════════════════════════════

def _wecom_build_startup(ctx: EngineContext):
    """env 凭证优先并落盘；否则从持久化 store 恢复；都没有则等管理台启动。"""
    from .wecom_aibot import WecomAibotEngine, WecomAibotStore

    store = WecomAibotStore(
        _store_path(ctx.config.wecom_aibot_store_path, "wecom_aibot_store.json")
    )
    bot_id = ctx.config.wecom_aibot_bot_id
    bot_secret = ctx.config.wecom_aibot_bot_secret
    bot_key = ctx.config.wecom_aibot_bot_key
    if not bot_id or not bot_secret:
        persisted = store.get_credentials()
        if persisted:
            bot_id = persisted["bot_id"]
            bot_secret = persisted["bot_secret"]
            bot_key = persisted["bot_key"]
            logger.info(f"  [内置引擎] 从持久化恢复 WeCom AI Bot 凭证: bot_key={bot_key}, bot_id={bot_id}")
    if not (bot_id and bot_secret):
        return None
    engine = WecomAibotEngine(
        bot_key=bot_key,
        bot_id=bot_id,
        bot_secret=bot_secret,
        ws_url=ctx.config.wecom_aibot_ws_url,
        heartbeat_interval=ctx.config.wecom_aibot_heartbeat_interval,
        reconnect_delay=ctx.config.wecom_aibot_reconnect_delay,
        shared_mode=ctx.config.shared_mode,
    )
    # 落盘（env 启动时也同步到 store，保证后续重启可自动恢复）
    store.set_credentials(bot_id, bot_secret, bot_key)
    logger.info(f"  [内置引擎] WeCom AI Bot 已启用: bot_key={bot_key}, bot_id={bot_id}")
    return engine


def _wecom_start(ctx: EngineContext, params: Dict[str, Any]):
    """bot_secret/bot_id 可留空：从持久化 store 补齐（「重启」场景）。

    返回值兼容旧管理台语义：失败时返回 {"success": False, "error": ...}。
    """
    from .wecom_aibot import WecomAibotEngine, WecomAibotStore

    bot_key = params.get("bot_key") or ctx.config.wecom_aibot_bot_key or "wecom-aibot-1"
    store = WecomAibotStore(
        _store_path(ctx.config.wecom_aibot_store_path, "wecom_aibot_store.json")
    )
    bot_id = params.get("bot_id") or ""
    bot_secret = params.get("bot_secret") or ""
    if not bot_id or not bot_secret:
        persisted = store.get_credentials()
        if persisted:
            bot_id = bot_id or persisted["bot_id"]
            bot_secret = bot_secret or persisted["bot_secret"]
            bot_key = bot_key or persisted["bot_key"]
    if not bot_id or not bot_secret:
        return {"success": False, "error": "缺少 Bot ID/Secret，且本地无已保存凭证；请填写后再启动。"}

    store.set_credentials(bot_id, bot_secret, bot_key)
    return WecomAibotEngine(
        bot_key=bot_key,
        bot_id=bot_id,
        bot_secret=bot_secret,
        ws_url=ctx.config.wecom_aibot_ws_url,
        heartbeat_interval=ctx.config.wecom_aibot_heartbeat_interval,
        reconnect_delay=ctx.config.wecom_aibot_reconnect_delay,
        shared_mode=ctx.config.shared_mode,
    )


wecom_descriptor = EngineDescriptor(
    name="wecom-aibot",
    title="企业微信 AI Bot",
    build_startup=_wecom_build_startup,
    start=_wecom_start,
    credentials=["bot_id", "bot_secret"],
)


# ════════════════════════════ Telegram ════════════════════════════

def _telegram_build_startup(ctx: EngineContext):
    from .telegram import TelegramEngine, TelegramStore

    store = TelegramStore(_store_path(ctx.config.telegram_store_path, "telegram_store.json"))
    token = ctx.config.telegram_bot_token or store.get_token() or ""
    if not token:
        if ctx.config.enable_telegram_engine:
            logger.warning(
                "  [内置引擎] ENABLE_TELEGRAM_ENGINE=true 但未设置 TELEGRAM_BOT_TOKEN，跳过"
            )
        return None
    if not ctx.config.telegram_bot_token:
        logger.info(f"  [内置引擎] 从持久化恢复 Telegram bot_key={ctx.config.telegram_bot_key}")
    store.set_token(token)
    return TelegramEngine(
        bot_key=ctx.config.telegram_bot_key,
        bot_token=token,
        store=store,
        poll_timeout=ctx.config.telegram_poll_timeout,
    )


def _telegram_start(ctx: EngineContext, params: Dict[str, Any]):
    from .telegram import TelegramEngine, TelegramStore

    bot_key = params.get("bot_key") or ctx.config.telegram_bot_key
    store = TelegramStore(_store_path(ctx.config.telegram_store_path, "telegram_store.json"))
    store.set_token(params["bot_token"])
    return TelegramEngine(
        bot_key=bot_key,
        bot_token=params["bot_token"],
        store=store,
        poll_timeout=params.get("poll_timeout", 30),
    )


telegram_descriptor = EngineDescriptor(
    name="telegram",
    title="Telegram Bot",
    build_startup=_telegram_build_startup,
    start=_telegram_start,
    credentials=["bot_token"],
)


# ════════════════════════════ Discord ════════════════════════════

def _discord_build_startup(ctx: EngineContext):
    from .discord import DiscordEngine, DiscordStore

    store = DiscordStore(_store_path(ctx.config.discord_store_path, "discord_store.json"))
    token = ctx.config.discord_bot_token or store.get_token() or ""
    if not token:
        if ctx.config.enable_discord_engine:
            logger.warning(
                "  [内置引擎] ENABLE_DISCORD_ENGINE=true 但未设置 DISCORD_BOT_TOKEN，跳过"
            )
        return None
    if not ctx.config.discord_bot_token:
        logger.info(f"  [内置引擎] 从持久化恢复 Discord bot_key={ctx.config.discord_bot_key}")
    store.set_token(token)
    return DiscordEngine(
        bot_key=ctx.config.discord_bot_key,
        bot_token=token,
        store=store,
    )


def _discord_start(ctx: EngineContext, params: Dict[str, Any]):
    from .discord import DiscordEngine, DiscordStore

    bot_key = params.get("bot_key") or ctx.config.discord_bot_key
    store = DiscordStore(_store_path(ctx.config.discord_store_path, "discord_store.json"))
    store.set_token(params["bot_token"])
    return DiscordEngine(
        bot_key=bot_key,
        bot_token=params["bot_token"],
        store=store,
    )


discord_descriptor = EngineDescriptor(
    name="discord",
    title="Discord Bot",
    build_startup=_discord_build_startup,
    start=_discord_start,
    credentials=["bot_token"],
)


# ════════════════════════════ 飞书 ════════════════════════════

def _feishu_build_startup(ctx: EngineContext):
    from .feishu import FeishuEngine, FeishuStore

    store = FeishuStore(_store_path(ctx.config.feishu_store_path, "feishu_store.json"))
    app_id = ctx.config.feishu_app_id
    app_secret = ctx.config.feishu_app_secret
    if not app_id or not app_secret:
        persisted = store.get_credentials()
        if persisted:
            app_id = app_id or persisted["app_id"]
            app_secret = app_secret or persisted["app_secret"]
            logger.info(f"  [内置引擎] 从持久化恢复飞书凭证: bot_key={ctx.config.feishu_bot_key}")
    if not (app_id and app_secret):
        if ctx.config.enable_feishu_engine:
            logger.warning(
                "  [内置引擎] ENABLE_FEISHU_ENGINE=true 但未设置 FEISHU_APP_ID/SECRET，跳过"
            )
        return None
    try:
        engine = FeishuEngine(
            bot_key=ctx.config.feishu_bot_key,
            app_id=app_id,
            app_secret=app_secret,
            store=store,
        )
    except Exception as e:
        logger.error(f"  [内置引擎] 飞书启动失败: {e}")
        return None
    store.set_credentials(app_id, app_secret, ctx.config.feishu_bot_key)
    logger.info(
        f"  [内置引擎] 飞书已启用: bot_key={ctx.config.feishu_bot_key}, app_id={app_id}"
    )
    return engine


def _feishu_start(ctx: EngineContext, params: Dict[str, Any]):
    from .feishu import FeishuEngine, FeishuStore

    bot_key = params.get("bot_key") or ctx.config.feishu_bot_key
    store = FeishuStore(_store_path(ctx.config.feishu_store_path, "feishu_store.json"))
    store.set_credentials(params["app_id"], params["app_secret"], bot_key)
    try:
        engine = FeishuEngine(
            bot_key=bot_key,
            app_id=params["app_id"],
            app_secret=params["app_secret"],
            store=store,
        )
    except RuntimeError as e:
        return {"success": False, "error": str(e)}
    return engine


feishu_descriptor = EngineDescriptor(
    name="feishu",
    title="飞书企业自建应用",
    build_startup=_feishu_build_startup,
    start=_feishu_start,
    credentials=["app_id", "app_secret"],
)


#: 内置渠道清单（顺序无关；注册表按名字索引）
BUILTIN_DESCRIPTORS = [
    ilink_descriptor,
    wecom_descriptor,
    telegram_descriptor,
    discord_descriptor,
    feishu_descriptor,
]
