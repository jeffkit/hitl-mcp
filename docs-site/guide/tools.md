# MCP 工具说明

hitl-mcp 向 AI 暴露以下工具。AI 会根据你的对话意图自动选用，你也可以在对话里点名调用。

## send_and_wait_reply

**发送消息并等待用户回复。** 最常用的「人在回路」工具。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | ✅ | 要发给用户的消息内容 |
| `recipient` | string | ❌ | 收件人。wecom-aibot 为群/用户 ID；ilink 自动推断，通常留空 |
| `project_name` | string | ❌ | 项目名，显示在消息头，方便区分来源 |

### 返回

```json
{
  "status": "success",
  "replies": [{ "text": "用户回复的文本" }],
  "message": "收到 1 条回复"
}
```

`status` 可能的值：

| status | 含义 |
|--------|------|
| `success` | 在超时前收到回复 |
| `timeout` | 等待超时（默认 20 分钟），未收到回复 |
| `error` | 发送失败 |
| `not_initialized` | 引擎未初始化（未登录 / 未激活收件人），返回里带 `init_url` 指向管理台 |

### 未初始化时怎么办

当返回 `not_initialized`，AI 会引导你打开 `init_url`（即 `http://localhost:8081/console`）完成初始化：

- **iLink**：在管理台扫码登录微信，并给 ClawBot 发过一条消息。
- **wecom-aibot**：在管理台填好 Bot ID / Bot Secret，并在企微里给 bot 发过消息激活收件人。

完成后重试即可。

## send_message_only

**仅发送消息，不等待回复。** 适用于通知场景（任务完成、进度汇报）。

参数与 `send_and_wait_reply` 相同，返回更简单：

```json
{ "status": "success", "message": "消息发送成功" }
```

同样可能返回 `not_initialized`，处理方式同上。

## wait_for_login（仅 iLink）

当 iLink 处于「等待扫码」状态时，hitl-mcp 会 **动态** 暴露这个工具。

- 作用：阻塞等待你在管理台扫码登录完成（最长 5 分钟）。
- 你在管理台扫码确认后，工具返回 `success`，AI 即可重试 `send_and_wait_reply`。

> 普通用户不用手动调它，AI 会自动在需要时调用并引导你扫码。

## list_activated_users（仅 iLink）

列出 iLink 引擎下「已激活」的微信用户（给 ClawBot 发过消息的用户）。

```json
[
  { "fromUserId": "wxid_xxx", "hasContextToken": true }
]
```

用于确认收件人是否已激活，或在多用户场景下选择收件人。

## 多会话与「引用回复」

当你 **同时** 有多个 `send_and_wait_reply` 在等回复时，直接回复会 ambiguous。hitl-server 会给每条消息分配一个短 ID（如 `[#a1b2]`）放在消息头：

```
[#a1b2] (my-project) 请确认是否继续？
```

此时请用微信/企微的 **「引用回复」** 功能精确选你要回的那条。单会话场景直接回复即可，无需引用。

## 让 AI 养成「先问再动」的习惯

光装好 MCP 不够，还要让 AI 知道何时用它。在你的项目根目录 `CLAUDE.md` / `AGENTS.md` 里加一条规则：

```md
## 人在回路规则

在执行以下操作前，必须先用 `send_and_wait_reply` 向我确认，收到明确同意后才执行：
- git push / git reset --hard / 删除文件
- 执行任何不可逆的写操作
- 花费较高的命令（如批量重跑、部署）

仅读取或本地预览类操作无需确认。
```

这样每个会话都会自动遵守，AI 在动手前会主动发微信问你。

## 下一步

- [常见问题](./faq)
- 回到 [快速开始](./quickstart)
