"""
HITL Server 入口（支持 `python -m hitl_server` 与 PyInstaller 打包）。

读取环境变量配置（HITL_PORT / ENABLE_*_ENGINE 等），
以 uvicorn 启动。直接传入 ASGI app 对象，避免 frozen 环境下的字符串导入。
"""
import uvicorn

from hitl_server.app import app
from hitl_server.config import config


def main() -> None:
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        reload=False,
        # 禁用 uvicorn 协议级 ping（代理场景下更稳，应用层已有心跳）
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )


if __name__ == "__main__":
    main()
