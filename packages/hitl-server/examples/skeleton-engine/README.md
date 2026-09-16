# skeleton-engine — HITL Server 外置引擎示例

最小可运行的外置渠道插件：不改 HITL Server 任何核心代码，靠 entry point
组 `hitl_server.engines` 注册 `skeleton` 渠道（echo 语义，把收到的消息原样
当作用户回复回写会话）。

## 试用

```bash
cd packages/hitl-server
uv pip install -e examples/skeleton-engine

uv run uvicorn hitl_server.app:app --port 8081 &
curl -s localhost:8081/admin/api/engines/registry | jq   # 可见 skeleton
curl -s -X POST localhost:8081/admin/api/engines/skeleton/start \
  -H 'Content-Type: application/json' -d '{"greet": "demo"}'

curl -s -X POST localhost:8081/api/send -H 'Content-Type: application/json' \
  -d '{"message": "hello", "upstream": "skeleton", "bot_key": "skeleton-1"}'
```

MCP 侧（无需任何 TS shim）：

```bash
hitl-mcp --engine skeleton --service-url http://localhost:8081
```

接口说明见 `docs/engine-plugins.md`。
