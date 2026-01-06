# 空闲状态提示消息配置指南

## 概述

当用户在企业微信中向配置的机器人发送消息，但机器人此时并非处于等待回复状态时，系统会自动回复一条提示消息。这条消息会显示当前的 Chat ID 等信息，方便用户获取配置信息。

**核心特性：**
- ✅ JSON 配置文件存储
- ✅ 支持热更新（修改后立即生效，无需重启服务）
- ✅ 全局默认配置 + 按 Chat ID 自定义配置
- ✅ 管理台可视化配置界面
- ✅ 支持启用/禁用

## 快速开始

### 通过管理台配置（推荐）

1. 访问管理台：`http://your-server:8081/admin`
2. 登录后点击"空闲提示配置"标签页
3. 在"全局默认配置"区域编辑消息模板
4. 点击"保存全局配置"按钮
5. 配置立即生效 ✨

### 配置文件位置

配置文件自动存储在：
- HIL Server: `data/idle_hint_config.json`
- DevCloud Service: `data/idle_hint_config.json`

首次运行时会自动创建默认配置文件。

## 配置结构

### JSON 文件格式

```json
{
  "default": {
    "template": "👋 你好 {user_name}！...",
    "enabled": true,
    "updated_at": "2026-01-06T15:30:00",
    "updated_by": "admin"
  },
  "chat_configs": {
    "wrkSFfCgAAxxxxxx": {
      "template": "自定义消息模板...",
      "enabled": true,
      "updated_at": "2026-01-06T16:00:00",
      "updated_by": "admin"
    }
  },
  "version": "1.0"
}
```

### 配置优先级

1. **Chat ID 特定配置**（最高优先级）
   - 为特定的 Chat ID 配置自定义消息
   - 优先于全局默认配置

2. **全局默认配置**
   - 适用于所有未配置特定消息的 Chat ID

### 支持的变量

在消息模板中，可以使用以下变量（使用 Python `str.format()` 语法）：

| 变量 | 说明 | 示例值 |
|------|------|--------|
| `{user_name}` | 发送消息的用户名称 | "张三" |
| `{chat_id}` | 当前会话的 Chat ID | "wrkSFfCgAAxxxxxx" |
| `{chat_type}` | 会话类型 | "私聊" 或 "群聊" |
| `{timestamp}` | 当前时间戳（HH:MM:SS） | "14:30:25" |

## 使用场景

### 场景 1：全局默认配置

为所有 Chat ID 设置统一的提示消息：

```
👋 你好 {user_name}！

当前没有等待中的会话需要你回复。

如果你想配置 MCP 使用此{chat_type}，请使用以下信息：

📋 **Chat ID**: `{chat_id}`
📌 **会话类型**: {chat_type}
🕐 **时间**: {timestamp}

你可以将此 Chat ID 配置到 MCP 的环境变量中：
```
DEFAULT_CHAT_ID={chat_id}
```
```

### 场景 2：VIP 群组自定义消息

为重要的 VIP 群组设置专属消息：

**步骤：**
1. 在管理台点击"+ 添加配置"
2. 输入 VIP 群的 Chat ID
3. 输入自定义消息模板：

```
🌟 尊敬的 {user_name}，您好！

当前机器人没有等待回复的任务。

如需帮助，请联系 VIP 专属客服：xxx-xxxx
或访问：https://vip.example.com
```

4. 保存后立即生效

### 场景 3：测试群禁用提示消息

对于测试群，可能不希望机器人回复提示消息：

**步骤：**
1. 添加测试群的 Chat ID 配置
2. 取消勾选"启用此配置"
3. 保存

此时测试群中的用户将不会收到任何自动回复。

### 场景 4：多语言支持

为国际团队配置英文消息：

```
👋 Hi {user_name}!

No pending messages at the moment.

📋 **Chat ID**: `{chat_id}`
📌 **Type**: {chat_type}
🕐 **Time**: {timestamp}

To configure MCP, use:
```
DEFAULT_CHAT_ID={chat_id}
```
```

## 管理台操作指南

### 1. 查看配置

- 登录管理台
- 点击"空闲提示配置"标签页
- 查看全局默认配置和所有 Chat ID 特定配置

### 2. 修改全局默认配置

- 在"全局默认配置"区域编辑消息模板
- 勾选/取消"启用"来启用或禁用全局配置
- 点击"保存全局配置"

### 3. 添加 Chat ID 特定配置

- 点击"+ 添加配置"按钮
- 输入 Chat ID
- 输入消息模板
- 勾选/取消"启用此配置"
- 点击"保存"

### 4. 编辑 Chat ID 特定配置

- 在 Chat ID 配置列表中找到要编辑的项
- 点击"编辑"按钮
- 修改消息模板或启用状态
- 点击"保存"

### 5. 删除 Chat ID 特定配置

- 在 Chat ID 配置列表中找到要删除的项
- 点击"删除"按钮
- 确认删除

删除后，该 Chat ID 将使用全局默认配置。

## API 接口

### 获取配置

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8081/admin/api/idle-hint-config
```

响应：
```json
{
  "success": true,
  "data": {
    "default": { ... },
    "chat_configs": { ... },
    "version": "1.0",
    "config_file": "/path/to/idle_hint_config.json"
  }
}
```

### 更新全局默认配置

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "你好 {user_name}！...",
    "enabled": true,
    "chat_id": null
  }' \
  http://localhost:8081/admin/api/idle-hint-config
```

### 更新 Chat ID 特定配置

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "自定义消息...",
    "enabled": true,
    "chat_id": "wrkSFfCgAAxxxxxx"
  }' \
  http://localhost:8081/admin/api/idle-hint-config
```

### 删除 Chat ID 特定配置

```bash
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8081/admin/api/idle-hint-config/wrkSFfCgAAxxxxxx
```

## 高级用法

### 1. 动态消息（根据时间变化）

虽然模板中的 `{timestamp}` 是固定格式，但你可以在消息中添加时间相关的提示：

```
👋 {user_name}，{timestamp}

📋 Chat ID: `{chat_id}`

💡 温馨提示：
- 工作日 9:00-18:00 会优先处理
- 非工作时间的消息将在下个工作日处理
```

### 2. Markdown 格式化

消息通过飞鸽传书的 `markdown` 接口发送，支持丰富的格式：

```
👋 **你好 {user_name}！**

> 当前无等待消息

---

📋 **配置信息**
- Chat ID: `{chat_id}`
- 类型: {chat_type}
- 时间: {timestamp}

**使用说明：**
1. 复制上面的 Chat ID
2. 配置到 MCP 环境变量
3. 重启 MCP 客户端

📚 [查看详细文档](https://your-docs-url.com)
```

### 3. 条件性消息（手动实现）

如果需要根据不同条件显示不同消息，可以为不同的 Chat ID 配置不同的模板：

- **开发团队群**: 包含技术文档链接
- **业务团队群**: 包含业务流程说明
- **客户群**: 包含客服联系方式

### 4. 批量配置

通过 API 批量配置多个 Chat ID：

```bash
#!/bin/bash

# Chat ID 列表
CHAT_IDS=("chat_id_1" "chat_id_2" "chat_id_3")

# 统一的消息模板
TEMPLATE="批量配置消息: {user_name} @ {chat_id}"

for CHAT_ID in "${CHAT_IDS[@]}"; do
  curl -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"template\": \"$TEMPLATE\",
      \"enabled\": true,
      \"chat_id\": \"$CHAT_ID\"
    }" \
    http://localhost:8081/admin/api/idle-hint-config
  
  echo "✓ 已配置: $CHAT_ID"
done
```

## 热更新原理

配置管理器采用"读时加载"策略：

1. **每次调用都从文件读取**
   - `format_message()` 调用时会通过 `_load_config()` 重新读取配置文件
   - 不缓存配置内容在内存中

2. **立即生效**
   - 修改配置文件后，下次用户发送消息时即可看到新配置
   - 无需重启 HIL Server 或 DevCloud Service

3. **性能考虑**
   - JSON 文件很小（通常 < 10KB），读取速度极快
   - 对于高并发场景，可以考虑添加短期缓存（如 5 秒）

## 故障排除

### 问题 1：配置修改后未生效

**可能原因：**
- 配置文件格式错误（JSON 语法错误）
- 文件权限问题

**解决方法：**
1. 检查日志中是否有配置文件读取错误
2. 验证 JSON 格式是否正确
3. 确认服务对配置文件有读写权限

### 问题 2：变量未被替换

**症状：** 消息中显示 `{user_name}` 而不是实际的用户名

**原因：** 变量名拼写错误或使用了不支持的变量

**解决：** 
- 检查变量名是否在支持列表中
- 确保使用 `{变量名}` 格式，不是 `{{变量名}}`

### 问题 3：消息未发送

**症状：** 用户没有收到自动回复

**可能原因：**
- 配置被禁用（`enabled: false`）
- 飞鸽 API 调用失败
- `BOT_KEY` 配置错误

**解决：**
1. 检查配置的 `enabled` 字段
2. 查看服务日志中是否有错误
3. 验证 `BOT_KEY` 是否正确

### 问题 4：并发问题

**症状：** 高并发场景下配置读取异常

**解决：** 目前的实现是线程安全的（每次读取都是独立的文件操作），如有问题请报告。

## 最佳实践

1. **简洁明了**
   - 提示消息应简洁，突出重点
   - 避免过长的消息（建议 < 500 字符）

2. **友好的语气**
   - 使用友好、礼貌的语言
   - 可以根据团队文化调整语气

3. **包含必要信息**
   - Chat ID 是必须的（用于配置）
   - 可选：文档链接、联系方式

4. **定期审查**
   - 定期检查配置是否仍然适用
   - 根据用户反馈调整消息内容

5. **测试验证**
   - 修改配置后在测试群中验证
   - 确保变量正确替换

6. **备份配置**
   - 定期备份 `idle_hint_config.json` 文件
   - 特别是在批量修改前

## 版本历史

- **v2.1.0** (2026-01-06): 
  - 新增 JSON 配置文件支持
  - 新增热更新功能
  - 新增管理台可视化配置界面
  - 支持全局默认 + Chat ID 特定配置
  - 支持启用/禁用

- **v2.0.0** 及更早版本：
  - 使用硬编码的默认消息

## 相关文档

- [HIL MCP 主文档](../README.md)
- [管理台使用指南](../README.md#管理台)
- [API 文档](../README.md#api)

## 技术支持

如有问题或建议，请：
- 查看日志文件
- 提交 Issue
- 联系技术支持团队
