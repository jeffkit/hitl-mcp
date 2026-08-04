# hil-mcp 卫生铁律

> 本文件被 pge flow 的 Generator/repair prompt 自动读取并注入（见 pge.flow.js 的 `loadHygiene`）。
> hil-mcp 是多包结构（hitl-server Python 主战场 + mcp-server-ts + console 前端）。

## 数据库与迁移（最高优先级）

- **改 `hitl_server/models.py` 后必须用 Alembic 生成迁移脚本**，不要直接改表结构。
  在 `packages/hitl-server` 下跑 `alembic revision --autogenerate -m "描述"`。
  详见 `packages/hitl-server/ALEMBIC_GUIDE.md`。
- **JSON 与 DB 模式 API 必须一致**：通过 `USE_DATABASE` 切换。改了一侧的数据层行为，
  另一侧也要对齐。开发用 SQLite（`sqlite+aiosqlite:///./data/service.db`），
  生产用 MySQL。
- **异步 SQLAlchemy**：数据库操作走 `aiosqlite`/async driver，不要在异步上下文里用同步 DB 调用。

## MCP 引擎与类型

- **引擎类型固定枚举**：`auto` / `ilink` / `wecom-aibot`（`hil` 已移除，不要重新引入）。
  `worker_type` 字段是引擎类型标识，名称沿用历史，非 Worker 概念。
- **wecom-aibot 支持运行时动态注册**：`/api/engines/wecom-aibot/start`，MCP 启动时自举。

## GitNexus 铁律（编辑安全）

- **编辑任何 symbol 前必须先跑 `impact`**：`impact({target: "symbolName", direction: "upstream"})`，
  报告 blast radius（直接调用方、受影响流程、风险等级）。
- **commit 前必须跑 `detect_changes`**：验证改动只影响预期 symbol 与执行流。
  回归审查用 `detect_changes({scope: "compare", base_ref: "main"})`。
- **HIGH/CRITICAL 风险必须先警告用户**再继续编辑。
- 绝不在没跑 `impact` 的情况下编辑函数/类/方法；绝不忽略 HIGH/CRITICAL 警告；
  绝不在没跑 `detect_changes` 的情况下提交。

## 多包工程规范

- **hitl-server（Python）**：用 `uv` 管理依赖（`uv sync` / `uv run pytest`）。
  pytest-asyncio 的 `asyncio_mode = auto`，异步测试函数自动捕获。
  console 前端 dist 由 PyInstaller force-include 打进 wheel，改前端要重新 `pnpm run build`。
- **mcp-server-ts（TypeScript）**：`tsc` 编译，`pnpm typecheck` 做类型检查。
  ⚠️ `test` script 只跑 `--help`（非真实测试），逻辑验证用 `pnpm test:logic`（tsx test-logic.ts）。
