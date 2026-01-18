# WS-Tunnel Python SDK

WebSocket 透明反向代理隧道 - Python 服务端和客户端 SDK。

详见上级目录的 [README.md](../README.md)。

## 安装

```bash
pip install -e .
```

## 使用

### 服务端

```python
from fastapi import FastAPI
from tunely import TunnelServer, TunnelServerConfig

app = FastAPI()
tunnel_server = TunnelServer()
app.include_router(tunnel_server.router)

@app.on_event("startup")
async def startup():
    await tunnel_server.initialize()
```

### 客户端

```python
from tunely import TunnelClient

client = TunnelClient(
    server_url="ws://server/ws/tunnel",
    token="tun_xxx",
    target_url="http://localhost:8080"
)
await client.run()
```

### 命令行

```bash
ws-tunnel connect --token tun_xxx --target http://localhost:8080
```
