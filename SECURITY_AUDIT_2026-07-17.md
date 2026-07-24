# 敏感信息审计 — hil-mcp 仓库

> 审计时间：2026-07-17
> 审计范围：整个 git 仓库（含所有分支历史）+ 工作树
> 结论：**发现一处高危泄露**，其余基本合规。

---

## 🔴 高危：`db_backup/forward_service_dev.db` 被提交并推送到远程

该 SQLite 文件**已在 `main` 分支，并推送到 `github/main` / `origin/main` / `woa/main`**（提交 `cf9e91e`）。
它**违背了本项目 AGENTS.md 明确禁令**："禁止提交含真实 Bot Secret / API Key 的配置或数据库"。

注意：`.gitignore` 第 71 行已有 `*.db`，但该文件是被 `git add -f` / 显式提交，**手动忽略了忽略规则**，所以没起作用。

### 库内真实敏感数据

| 表 | 行数 | 泄露内容 |
|----|------|----------|
| `chatbots` | 6 | **真实 `bot_key`（36 字符）与 `api_key`（50 字符）**，对应 jarvis / thor / edan / loki / hitl-mcp / agent-studio；以及**内网服务地址**（10.43.63.41、9.134.37.237）和 agent UUID |
| `user_sessions` | 41 | **真实企微 `user_id`（如 T15500028A）、`chat_id`（wokSFfCgAA…）、session UUID，以及真实对话片段** |
| `forward_logs` | 177 | 真实转发消息日志 |
| `system_config` | 1 | 管理员账号列表（kongjie） |

**风险判定**：这是一份**真实运营库**（不是测试夹具），含可用 bot 凭证 + 真实用户 PII。任何能 clone 仓库的人都能拿到这些 `api_key` / `bot_key` 去调用对应 bot，并看到真实对话记录。

---

## 🟢 合规项（已确认安全）

- **源码无硬编码密钥**：`packages/` 下只有测试用的假值（`test-secret-key-12345`、`vctx_xxx`），无生产密钥。
- **`.env.example` / `data/`** 已被 `.gitignore` 正确忽略，未进仓库。
- **`.env`（工作树本地文件，未跟踪）**：仅含内网 DevCloud URL（`http://9.134.172.68:8080`），无密钥。安全，但注意别误 `git add`。
- **git 历史全量签名扫描**（AKIA / xox* / ghp_ / glpat_ / AIza / 私钥头 / `sk-`/`wx`/`qy_` 等）**未命中**任何第三方平台密钥。泄露的是项目自有的 bot 凭证，不是云厂商密钥。

---

## 建议的处置步骤（需你拍板，部分涉及破坏性 git 操作）

1. **立即轮换已泄露的 bot `api_key` / `bot_key`**（最高优先级）。
   即便把文件从历史抹掉，密钥已经在远程存在过，必须当作已泄露处理。
2. **从工作树移除**该 db，并确认不再被提交。
3. **从 git 历史彻底擦除**（所有分支）：用 `git filter-repo` 或 BFG 清理 `db_backup/forward_service_dev.db`，再 **force-push** 到所有远程。
   - ⚠️ force-push 会重写历史，属于破坏性操作；按惯例需你确认后再做，且要通知协作者重新 clone。
4. **加固 `.gitignore`**：确认 `*.db` 规则生效；考虑显式追加 `db_backup/*.db`；并在 CI / pre-commit 加一道密钥扫描（如 gitleaks）防止复发。
5. **PII 处置**：库中含真实企微 user_id / chat_id / 对话内容，建议评估是否需要告知相关用户或按内部数据泄露流程上报。

---

## 我做了什么 / 没做什么

- ✅ 已扫描：全量 git 历史密钥签名、被跟踪文件清单、`data/`/`db_backup/` 内容、源码硬编码密钥、`.env` 与 `.gitignore`。
- ❌ 未轮换密钥、未动 `woa` 远程、未创建新分支。

---

## 处置结果（2026-07-17 已执行）

按 Jeff 指示执行第 2 步：**从 git 历史擦除 db + force-push 到 github（不动 woa）**。

1. **回滚兜底**：改写前创建完整 bundle 备份
   `/tmp/hil-mcp-pre-filter-20260717-122504.bundle`（含全部分支/标签，17MB）。
   ⚠️ 该备份本身含旧历史（含 db 与密钥），妥善保管，确认无需回滚后删除。
2. **历史改写**：`git filter-repo --path db_backup/forward_service_dev.db --invert-paths --force`
   - db 已从所有本地分支历史移除，工作树 `db_backup/` 目录已删除。
3. **force-push 到 github**（仅 `main` 与 `feat/wecom-shared-mode`，即 github 上唯一带 db 的两个分支）：
   - `main: ecb5a6b → e1fcaf2 (forced update)`
   - `feat/wecom-shared-mode: e439fc1 → e7c1af6 (forced update)`
4. **服务器验证**：`git fetch` 后确认 `github/main` 与 `github/feat/wecom-shared-mode` 的树与历史均不再含 `db_backup`。✅
5. 恢复了被 filter-repo 误删的 `origin` 远程（与 github 同地址）。

### 仍需你跟进（重要）

- 🔴 **密钥仍需轮换**（原报告第 1 步）。force-push 只改了历史，db 内容在被改写前已公开存在过，且 GitHub 侧旧对象可能在 GC 前仍可访问、旧 fork/clone 仍持有。6 个 bot 的 `api_key`/`bot_key` 应视为已泄露并轮换。
- 🟡 **`woa` 远程未处理**。按指示只推了 github；但 `woa`（`git.woa.com`）服务器上的 `woa/main` 等分支仍含旧历史与 db。如需在 woa 也清除，需再对 woa 执行同样的 force-push（会再重写一次历史，涉及另一远程的协作者）。
- 🟡 **`.gitignore` 加固**：`*.db` 规则本应挡住该文件，是被 `git add -f` 强提交绕过的。建议显式追加 `db_backup/*.db` 并在 CI 加 gitleaks 类扫描防复发。
- 🟡 **本地未推分支**：`develop`、`feat/multi-target-per-user` 本地已改写干净（无 db），但不在 github 上，无需推送；日后推送即为干净状态。
