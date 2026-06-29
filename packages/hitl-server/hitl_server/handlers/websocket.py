"""
WebSocket 处理器

处理 DevCloud Worker 的 WebSocket 连接
"""
import logging
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..config import config
from ..ws_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    worker_id: str = Query(..., description="Worker ID"),
    token: str = Query("", description="鉴权 Token")
):
    """
    WebSocket 连接入口
    
    Worker 通过此接口连接到 Relay Server
    """
    # 验证 Token（如果配置了）
    if config.worker_token and token != config.worker_token:
        logger.warning(f"Worker 鉴权失败: worker_id={worker_id}")
        await websocket.close(code=4001, reason="Authentication failed")
        return
    
    # 接受连接
    await websocket.accept()
    logger.info(f"Worker 连接已接受: {worker_id}")
    
    # 注册 Worker
    connection = await ws_manager.register_worker(worker_id, websocket)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                await ws_manager.handle_message(worker_id, message)
            except json.JSONDecodeError:
                logger.warning(f"无效的 JSON 消息: {data[:100]}")
            except Exception as e:
                logger.error(f"处理消息失败: {e}", exc_info=True)
                
    except WebSocketDisconnect:
        logger.info(f"Worker 断开连接: {worker_id}")
    except Exception as e:
        logger.error(f"WebSocket 错误: {worker_id}, {e}", exc_info=True)
    finally:
        await ws_manager.unregister_worker(worker_id)
