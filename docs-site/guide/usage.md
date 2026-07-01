# 使用方法：让 AI 学会「边做边问你」

装好 hitl-mcp 只是第一步，真正好用与否，取决于你能不能让 AI 在合适的时机主动联系你。本文给出一套 **可复制的工作流**，并以 Cursor 的 `with-feedback` 自定义 slash command 为例，带你跑通「AI 执行任务 ↔ 微信/企微反馈 ↔ 你给意见 ↔ AI 继续」的闭环。

## 核心思路

hitl-mcp 提供两个核心工具（详见 [MCP 工具说明](./tools)）：

| 工具 | 何时用 |
|------|--------|
| `send_and_wait_reply` | 需要你拍板时——AI 发完消息后 **阻塞等你的回复**，拿到意见再继续 |
| `send_message_only` | 仅通知你时——AI 发完即继续，不阻塞 |

让 AI 主动用这两个工具的关键，是给它一段 **明确的指令**。最省心的做法是把这段指令沉淀成一条 **slash command**，下次一句 `/with-feedback …` 就能让 AI 进入「人在回路」模式。

## 示例：Cursor 的 `with-feedback` 命令

Cursor 支持自定义 slash command：把一个 Markdown 文件放进 `.cursor/commands/`（项目级）或 `~/.cursor/commands/`（全局），在聊天里输入 `/` 就能调用。我们用它来做 hitl-mcp 的「入口」。

### 第 1 步：新建命令文件

在项目根目录创建 `.cursor/commands/with-feedback.md`（推荐项目级，跟着仓库走；想所有项目通用就放 `~/.cursor/commands/with-feedback.md`）：

```md
# with-feedback

在完成以下任务过程中，使用 `hitl-mcp` 的工具与我沟通。

- 如需要我提供反馈，请使用 `send_and_wait_reply` 工具，获得我的反馈后，继续执行任务。
- 如仅用于知会我，请使用 `send_message_only` 工具通知我后即可无阻塞地继续执行任务。

**重要：** 使用这些工具时，请务必填写 `project_name` 参数（使用当前项目名称），方便在多项目并行时区分消息来源。

在我给出明确的结束信号前，你不能擅自停止任务。

## 任务描述
```

> 文件名即命令名。叫 `with-feedback.md` 就用 `/with-feedback` 调用；想换个名字，把文件名改掉即可。

### 第 2 步：在对话里调用

在 Cursor 聊天输入框敲 `/with-feedback`，空格后跟上任务描述，例如：

```
/with-feedback 把订单服务的日志级别从 info 调成 debug，并重启服务
```

Cursor 会把命令文件的内容作为提示词喂给 AI，末尾的「任务描述」会接在 `## 任务描述` 后面。AI 看到的完整提示大致是：

> 在完成以下任务过程中，使用 `hitl-mcp` 的工具与我沟通……在我给出明确的结束信号前，你不能擅自停止任务。
>
> ## 任务描述
>
> 把订单服务的日志级别从 info 调成 debug，并重启服务

### 第 3 步：AI 开始边做边问你

进入这个模式后，AI 的行为会变成这样：

1. 先梳理任务，可能用 `send_message_only` 给你发一条「我打算这么做」的通知（不阻塞，继续干）。
2. 遇到需要拍板的节点（比如要改生产配置、要重启服务），调用 `send_and_wait_reply` 把问题发到你手机，然后 **停下来等你**。
3. 你在微信 / 企微里回复（单会话直接回；多个任务并行时用「引用回复」选具体那条，详见 [多会话与引用回复](./tools#多会话与引用回复)）。
4. AI 拿到回复继续执行，循环往复，直到任务完成或你明确喊停。

你的手机上大致会收到这样的消息：

```
[#a1b2] (order-service) 我准备把 log_level 改成 debug 并重启 order-service，
确认继续吗？回复 OK 执行，回复 NO 取消。
```

## 为什么这么写命令

这条命令里藏了几个让 AI 表现稳定的关键点：

- **点名工具**：直接写出 `send_and_wait_reply` / `send_message_only`，避免 AI 自由发挥、用错工具。
- **区分「要反馈」与「仅通知」**：让 AI 自己判断当前节点该阻塞还是该只通知，兼顾安全与效率。
- **强制 `project_name`**：多项目并行时，消息头的项目名是你分辨来源的唯一线索。
- **「未明确结束前不得停止」**：防止 AI 在等你回复时自作主张地把任务标记完成。

## 进阶用法

### 给纯通知场景准备一条轻量命令

如果某个任务只希望 AI 做完告诉你一声、不需要你回，可以再建一条 `notify-only.md`：

```md
# notify-only

完成下面的任务后，用 `send_message_only` 把结果摘要发给我（请填写 `project_name` 为当前项目名）。
过程中无需等待我的回复，做完即止。

## 任务描述
```

适合长跑任务（跑测试、构建、数据迁移）结束后「微信通知我结果」。

### 配合项目规则长期生效

slash command 是 **按需触发** 的；如果你希望某个项目里 AI **始终** 先问再动，把规则写进项目根目录的 `CLAUDE.md` / `AGENTS.md`：

```md
## 人在回路规则

在执行以下操作前，必须先用 `send_and_wait_reply` 向我确认，收到明确同意后才执行：
- git push / git reset --hard / 删除文件
- 执行任何不可逆的写操作
- 花费较高的命令（如批量重跑、部署）

仅读取或本地预览类操作无需确认。
```

两种方式可以叠加：日常写代码靠 `CLAUDE.md` 兜底，跑专项任务时用 `/with-feedback` 显式进入「强交互」模式。

### 在其他客户端里复用

这套提示词不挑客户端，Claude Code、Claude Desktop 等支持自定义命令/提示词的工具都能用，只是落地位置不同：

- **Claude Code**：放进 `~/.claude/commands/with-feedback.md`，用 `/with-feedback` 调用。
- **Claude Desktop**：没有 slash command 时，直接把上面那段提示词粘贴到对话开头，再附上任务描述即可。

## 验证一下

新命令建好后，先用一个小任务自测：

```
/with-feedback 给我发一条消息确认 hitl-mcp 链路正常，然后等我回复 OK
```

如果手机收到消息、你回复 `OK` 后 AI 能接上话，说明从命令到 MCP 到引擎的整条链路都通了，可以放心用在真实任务里。

## 下一步

- [MCP 工具说明](./tools) — `send_and_wait_reply` / `send_message_only` 的参数与返回。
- [配置 MCP 客户端](./mcp-config) — 各客户端的配置文件位置。
- [常见问题](./faq) — 收不到消息、502、npx 慢怎么办。
