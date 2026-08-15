# dsh-answerer — DeepSeek Harness 微信审批应答器

让 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）的
`approval/request` 审批请求推送到你的微信 / 企微（经 hitl-server），你在手机上
回复 `y` / `n` 决定放行与否。

```
dsh approval seam                hitl-server (:8081)          你的手机
──────────────────               ────────────────────          ────────
ctx.on('approval/request') ──POST /api/send──▶ engine ──▶ 微信消息
       ▲                                                          │
       └─ outcome ◀─GET /api/poll/<id>◀──────────────── 用户回复 y/n│
```

已在 dsh 0.1.0-rc.6 + hitl-server（ilink 引擎，经 ilink-hub 中转）上端到端验证：
真人回复 `y` → `allowed-once` → 沙箱升级放行。

## 安装

```bash
# 1. 插件放到 dsh 可加载的位置（任意路径，绝对路径引用）
mkdir -p ~/.dsh/plugins
cp hitl-approval.mjs ~/.dsh/plugins/

# 2. 准备 patch 层（或直接用 patch.example.yml 改路径）
# 3. 带审批跑任意 dsh profile：
DSH_PERMISSION_MODE=read-only dsh --profile headless \
  --patch ~/.dsh/patches/hitl-approval.yml "<任务>"
#    关键操作 → 手机收到审批 → 回 y 放行 / 回 n 拒绝 / 不回超时拒绝（fail-closed）
```

也可以写进 profile 的 `cordis.patch.yml`（对 web/tui 常驻场景）。

## 结果映射（dsh 词表是封闭且 fail-closed 的）

| 微信回复 | dsh outcome |
|---|---|
| `y` / `yes` / `同意` / `允许` … | `allowed-once`（仅放行本次动作） |
| `n` / `no` / `拒绝` / `取消` … | `rejected` |
| 无法识别的回复 | 视为噪声，继续等待（窗口内） |
| 超时未回复 | `unavailable`（fail-closed，等同拒绝） |
| 请求中途被 abort | `cancelled` |

**送达失败不认领**：hitl-server 不可达 / 引擎未登录 / 无激活收件人时，插件调用
`next()` 把请求交还后续应答器（如 web UI 弹窗）——只有消息真正到达手机后本层
才拥有该请求的决定权。

## 配置

patch config（全部可选），环境变量（`HITL_*`）从启动 shell 覆盖：

| 键 | env | 默认 | 说明 |
|---|---|---|---|
| `serviceUrl` | `HITL_SERVER_URL` | `http://127.0.0.1:8081` | hitl-server 地址 |
| `botKey` | `HITL_BOT_KEY` | 自动解析 | 引擎路由键（缺省从 `/admin/api/engines` 按 ilink→wecom→… 优先级取就绪引擎） |
| `chatId` | **不读 env**（见下） | 引擎激活用户 | 显式收件人；缺省取所选引擎第一个激活用户，避免服务端"最近活跃收件人"回退到过期账号 |
| `apiKey` | `HITL_API_KEY` | 空 | 共享部署时 /api/* 的 Bearer |
| `timeoutSec` | `HITL_TIMEOUT_SECS` | 300 | 等人回复的窗口 |
| `pollIntervalMs` | — | 2000 | 轮询节奏 |
| `projectLabel` | `HITL_PROJECT_LABEL` | `dsh` | 手机上显示的项目前缀 |
| 调试 | `HITL_DEBUG=1` | — | stderr 打印引擎路由 / 完整请求体 / 响应 |

> **chatId 刻意不从环境读**：shell 里历史遗留的 `HITL_CHAT_ID`（本意给别的
> 部署）会把审批静默误路由到未激活收件人（实测报 `用户未激活`）。要固定收件人
> 请写在 patch config 里。

## ilink-hub 路由语义（源码核实 + 实测）

hitl-server 经 ilink-hub 中转时（多后端共享一个微信会话，路由按微信用户单归属）：

- **引用回复是保证路径**：长按引用审批消息后回复 `y`，hub 按 L0 msg_id 精确
  路由回该消息的产出后端（hitl-server），无视当前路由归属（quote_route.rs，
  L0 msg_id → L1 时间戳 → L2 内容前缀 → L3 footer 四层回退）。
- **普通回复不保证**：取决于当时 `/use` 路由归属与后端在线状态（实测出站
  发送**不**认领路由——bot.rs 的 sendmessage 无 set_route；只有 `/use` 命令
  与启动时的路由加载会写路由表）。审批场景请指引用户引用回复。
- 微信里 `/list` 查看后端与当前路由，`/use <名称>` 切换，`@<名称> <消息>`
  临时定向。
- 多个等待会话且无引用时，hitl-server 会提示长按引用目标消息再回复
  （ambiguous_session，不猜测）。
- 如需彻底隔离（审批与日常 agent 不同会话命名空间），hub 的会话本就按
  `(vctx, vtoken)` 隔离——同后端内 approval 与日常消息靠引用回复区分即可，
  无需第二 bot_key（hitl-server 单实例也只支持一个 ilink 引擎）。

## 文件

- `hitl-approval.mjs` — Cordis 插件（dsh 万物皆插件：`approval/request` 瀑布的外部应答器）
- `patch.example.yml` — 挂载模板
