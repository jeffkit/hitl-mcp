# HITL Server 引擎插件开发指南（engine plugins）

新增一个 IM 渠道（或任何人工确认通道）**不需要修改 HITL Server 核心代码**
（`app.py` / `handlers/admin.py` / `engines/__init__.py`）。渠道以
`EngineDescriptor` 为单元注册进引擎注册表：

- **内置渠道**：`hitl_server/engines/builtin.py` 的 `BUILTIN_DESCRIPTORS`
- **外置插件**：打包成独立 wheel，声明 entry point 组
  **`hitl_server.engines`**，安装即生效

## 插件接口

插件契约就是既有的 `BaseEngine`（`hitl_server/engines/base.py`）：

| 成员 | 说明 |
|------|------|
| `worker_type` / `bot_key` | 渠道标识与实例标识（构造参数） |
| `on_user_message` | 回调；收到用户消息后交给 `storage.handle_callback` |
| `async start()` / `async stop()` | 生命周期（长连接、后台轮询） |
| `async send_message(payload) -> dict` | 处理 `/api/send` 下行 |
| `status() -> dict` | 管理台展示状态（至少含 `worker_type` / `bot_key` / `running`） |

在此之上，每个渠道在 descriptor 里提供两个装配钩子（**sync 或 async 函数均可**，核心经 `maybe_await` 统一处理；需要网络探测的插件可用 async）：

```python
from hitl_server.engines.registry import EngineDescriptor, EngineContext

descriptor = EngineDescriptor(
    name="mychannel",                 # worker_type，URL 里的 {type}
    title="我的渠道",
    build_startup=build_startup,      # async (ctx) -> BaseEngine | None（env/持久化自动装配）
    start=start,                      # async (ctx, params) -> BaseEngine | {"success": False, ...}
    request_model=MyStartRequest,     # 可选 pydantic 模型，校验 start 请求体
    credentials=["bot_token"],        # 凭证字段（文档/客户端提示）
    extra_routes=extra_routes,        # 可选：渠道特有路由（如 ilink 的 qr/status）
)
```

`EngineContext` 提供 `config`（HITLConfig）与 `storage`（会话存储）。
通用编排（停旧实例 → 挂 `on_user_message` → 注册 → `start()`）由
`admin.py` 的 `_start_engine` 统一完成，descriptor 的 `start` 只负责
**校验凭证 → 持久化 → 构造引擎实例**。

## 注册方式

### 内置渠道

在 `engines/builtin.py` 实现装配函数并追加到 `BUILTIN_DESCRIPTORS`。

### 外置插件（推荐，业务渠道零侵入）

`pyproject.toml`：

```toml
[project]
name = "hitl-engine-mychannel"
# ...

[project.entry-points."hitl_server.engines"]
mychannel = "hitl_engine_mychannel:descriptor"
```

`pip install` 该包后重启 HITL Server，日志会出现
`已加载外置引擎插件: mychannel (entry-point:...)`。

## 服务端暴露的通用 API

| 端点 | 说明 |
|------|------|
| `GET /admin/api/engines` | 已注册引擎实例及状态 |
| `GET /admin/api/engines/registry` | 注册表中全部渠道（name/title/credentials/source） |
| `POST /admin/api/engines/{type}/start` | 通用动态启动（请求体 = descriptor 凭证字段） |
| `POST /admin/api/engines/{type}/stop` | 通用停止 |
| 渠道 `extra_routes` | 渠道特有路由（如 `/admin/api/engines/ilink/qr`） |

旧的按渠道端点（`/admin/api/engines/telegram/start` 等）保留为兼容层，
内部同样走 descriptor 通用路径。

## MCP 客户端（TypeScript）如何接新渠道

`mcp-server-ts` 提供 `GenericEngine`（`src/engines/generic.ts`）：

- `hitl-mcp --engine mychannel` — 任何注册表中的渠道名都可用；
- `--engine-credentials '{"bot_token": "..."}'` — 启动时向
  `/api/engines/{type}/start` 自动注册（等价于在管理台填写）；
- 发送/收回复走通用的 `/api/send`（`upstream=<type>`）+ `/api/poll`。

只有需要渠道特有能力（如 iLink 扫码图文）时才需要写专用引擎类。

## 示例

完整可运行的 skeleton 插件见
[`examples/skeleton-engine/`](../examples/skeleton-engine/)（含 pyproject、
descriptor、README）。
