# hitl-server — Human-in-the-Loop 服务端

让 AI Agent 在执行关键操作前，先通过微信 / 企业微信向你确认。

AI 把「需要人确认」的请求发给 `hitl-server`，`hitl-server` 把消息推到你的手机
（微信 ClawBot / iLink 或企微 AI 机器人），你回复后 AI 拿到结果继续执行。

```
┌──────────┐  MCP(stdio)  ┌──────────┐  HTTP   ┌────────────┐  长连接   ┌──────────┐
│ AI Agent │ ───────────▶ │ hitl-mcp │ ──────▶ │ hitl-server│ ────────▶ │ 你的手机 │
│ Cursor   │ ◀─────────── │  (npx)   │ ◀────── │  :8081     │ ◀──────── │ 微信/企微 │
└──────────┘              └──────────┘         └────────────┘           └──────────┘
```

## 内置引擎

- **ilink**：iLink 长轮询，对接个人微信 ClawBot。
- **wecom-aibot**：企微 WebSocket，对接企业微信 AI 机器人。

两种部署形态：本地单用户（默认，无需公网服务器）与服务器共享部署（多人共用一个企微 Bot）。

## 安装

```bash
pip install hitl-server
# 或
uvx hitl-server
# 或从源码
uv sync && uv run python -m hitl_server.app
```

## 运行

```bash
hitl-server                         # 前台运行，默认 :8081
ENABLE_ILINK_ENGINE=true hitl-server  # 启用 iLink 引擎
USE_DATABASE=true hitl-server        # 数据库模式（SQLAlchemy）
```

管理台：`http://localhost:8081/console`

## 关键特性

- 多会话并发引用回复匹配：`[#short_id]` 标签 + iLink 出站 `message_id` L0 精确匹配，
  彻底消除并发待回复时的歧义。
- JSON 文件 / 数据库双存储，接口一致（开发用 SQLite，生产用 MySQL）。
- Alembic 管理 schema 迁移。
- 内置 React 管理台（JWT 保护）。

## 文档

- 完整文档：https://github.com/jeffkit/hitl-mcp
- 引擎文档：`docs-site/engines/`
- 数据库迁移：`ALEMBIC_GUIDE.md`

## License

MIT
