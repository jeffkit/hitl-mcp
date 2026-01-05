"""
DevCloud Worker 主程序（简化版）

纯代理模式：
- 接收 Relay 的消息发送请求 → 调用 fly-pigeon
- 接收飞鸽回调 → 转发给 Relay

运行方式:
    python -m devcloud_worker.worker
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import websockets
from fastapi import FastAPI, Request, Header

from .config import config
from .sender import handle_send_message, handle_upload_image, handle_send_hint
from .callback_handler import callback_handler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket 客户端"""
    
    def __init__(self):
        self._ws = None
        self._running = False
        self._reconnect_delay = config.reconnect_delay
        self._send_lock = asyncio.Lock()  # 发送锁，避免并发发送冲突
    
    @property
    def is_connected(self) -> bool:
        if self._ws is None:
            return False
        # 兼容新旧版本的 websockets 库
        if hasattr(self._ws, 'open'):
            return self._ws.open
        elif hasattr(self._ws, 'state'):
            from websockets.protocol import State
            return self._ws.state == State.OPEN
        return False
    
    async def connect(self) -> None:
        """连接到 HIL Server"""
        params = {
            "worker_id": config.worker_id,
            "token": config.hil_token
        }
        url = f"{config.hil_url}?{urlencode(params)}"
        
        logger.info(f"连接到 HIL Server: {url}")
        
        # 禁用 websockets 库的内置 ping/pong 机制
        # 因为 HIL Server 端使用 FastAPI WebSocket，有自己的心跳逻辑
        # websockets 的 ping 和 FastAPI 的心跳不兼容，会导致 keepalive ping timeout
        self._ws = await websockets.connect(
            url,
            ping_interval=None,   # 禁用自动 ping
            ping_timeout=None,    # 禁用 ping 超时检测
            close_timeout=10,     # 关闭连接超时
        )
        
        logger.info("WebSocket 连接成功")
        self._reconnect_delay = config.reconnect_delay
    
    async def disconnect(self) -> None:
        """断开连接"""
        if self._ws:
            await self._ws.close()
            self._ws = None
    
    async def send(self, message: dict) -> None:
        """发送消息（线程安全）"""
        if self._ws:
            async with self._send_lock:
                try:
                    await self._ws.send(json.dumps(message))
                except Exception as e:
                    logger.warning(f"发送消息失败: {e}")
    
    async def send_response(
        self,
        request_id: str,
        success: bool,
        data: dict | None = None,
        error: str | None = None
    ) -> None:
        """发送响应"""
        response = {
            "type": "response",
            "id": request_id,
            "success": success,
            "data": data or {},
            "error": error
        }
        await self.send(response)
    
    async def forward_callback(self, callback_data: dict) -> None:
        """转发飞鸽回调到 Relay"""
        message = {
            "type": "callback",
            "event": "wecom_callback",
            "data": {
                "callback_data": callback_data
            }
        }
        await self.send(message)
        logger.info("已转发回调到 Relay")
    
    async def handle_request(self, message: dict) -> None:
        """处理来自 Relay 的请求"""
        request_id = message.get("id")
        action = message.get("action")
        payload = message.get("payload", {})
        
        logger.info(f"收到请求: id={request_id}, action={action}")
        
        try:
            if action == "send_message":
                result = await handle_send_message(payload)
                success = result.get("success", False)
                if success:
                    await self.send_response(request_id, True, result)
                else:
                    await self.send_response(request_id, False, error=result.get("error"))
                
            elif action == "upload_image":
                result = await handle_upload_image(payload)
                await self.send_response(request_id, True, result)
            
            elif action == "send_hint":
                # 发送提示消息（如 Chat ID 提示）
                result = await handle_send_hint(payload)
                await self.send_response(request_id, result.get("success", True), result)
                
            else:
                await self.send_response(
                    request_id, False,
                    error=f"Unknown action: {action}"
                )
                
        except Exception as e:
            logger.error(f"处理请求失败: {e}", exc_info=True)
            await self.send_response(request_id, False, error=str(e))
    
    async def run(self) -> None:
        """运行 Worker"""
        self._running = True
        # 用于跟踪正在处理的请求任务
        self._pending_tasks: set[asyncio.Task] = set()
        
        while self._running:
            try:
                await self.connect()
                
                # 接收消息循环
                async for data in self._ws:
                    try:
                        message = json.loads(data)
                        msg_type = message.get("type")
                        
                        if msg_type == "ping":
                            await self.send({"type": "pong"})
                        elif msg_type == "request":
                            # 使用 create_task 并发处理请求，避免阻塞消息接收
                            task = asyncio.create_task(self.handle_request(message))
                            self._pending_tasks.add(task)
                            # 任务完成后自动从集合中移除
                            task.add_done_callback(lambda t: self._pending_tasks.discard(t))
                        else:
                            logger.warning(f"未知消息类型: {msg_type}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"无效的 JSON: {data[:100]}")
                    except Exception as e:
                        logger.error(f"处理消息失败: {e}", exc_info=True)
                
            except websockets.ConnectionClosed:
                logger.warning("WebSocket 连接已关闭")
            except Exception as e:
                logger.error(f"WebSocket 错误: {e}", exc_info=True)
            finally:
                self._ws = None
                # 等待所有正在处理的请求完成
                if self._pending_tasks:
                    logger.info(f"等待 {len(self._pending_tasks)} 个请求完成...")
                    await asyncio.gather(*self._pending_tasks, return_exceptions=True)
                    self._pending_tasks.clear()
            
            if self._running:
                logger.info(f"将在 {self._reconnect_delay} 秒后重连...")
                await asyncio.sleep(self._reconnect_delay)
                # 指数退避
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    config.max_reconnect_delay
                )
    
    def stop(self) -> None:
        """停止 Worker"""
        self._running = False


# 全局 WebSocket 客户端
ws_client = WebSocketClient()


# ============== 回调 HTTP 服务 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info(f"DevCloud Worker 启动, 回调端口: {config.callback_port}")
    
    # 设置回调转发函数
    async def forward_to_relay(callback_data: dict):
        if ws_client.is_connected:
            await ws_client.forward_callback(callback_data)
        else:
            logger.warning("WebSocket 未连接，无法转发回调")
    
    callback_handler.set_forward_callback(forward_to_relay)
    
    # 启动 WebSocket 客户端
    ws_task = asyncio.create_task(ws_client.run())
    
    yield
    
    # 停止
    ws_client.stop()
    ws_task.cancel()
    
    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    
    logger.info("DevCloud Worker 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="DevCloud Worker",
    description="DevCloud Worker - fly-pigeon 代理",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "DevCloud Worker",
        "version": "2.0.0",
        "mode": "proxy",
        "ws_connected": ws_client.is_connected
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "ws_connected": ws_client.is_connected
    }


@app.post("/callback")
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key")
):
    """
    处理飞鸽传书的回调
    
    接收回调后直接转发给 Relay Server
    """
    # 验证鉴权（可选）
    if config.callback_auth_key and config.callback_auth_value:
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
    
    try:
        data = await request.json()
        logger.info(f"收到飞鸽回调: chatid={data.get('chatid')}, msgtype={data.get('msgtype')}")
        
        result = await callback_handler.handle_callback(data)
        return result
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        return {"errcode": -1, "errmsg": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "devcloud_worker.worker:app",
        host="0.0.0.0",
        port=config.callback_port,
        reload=False
    )
