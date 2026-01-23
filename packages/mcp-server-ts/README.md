# hitl-mcp - Human-in-the-Loop MCP for WeCom (企业微信)

让 AI Agent 能够发送消息到企业微信并等待用户回复的 MCP 服务（TypeScript 实现）。

## 功能特性

- 🚀 **发送消息到企微群聊/私聊**
- ⏳ **等待用户回复并返回结果**
- 🎯 **引用回复匹配** - 通过 `[#short_id]` 精确匹配多个并发会话
- 💬 **多会话冲突检测** - 自动提示用户使用引用回复
- ⏰ **20分钟默认超时**
- 📋 **自动回复 chat_id** - 方便用户获取配置信息
- ⚡ **一键安装** - 通过 `npx` 无需预先安装
- 📦 **TypeScript 实现** - 类型安全，易于维护

---

## 快速开始

### 方式一：使用 npx（推荐）

在 Cursor 的 MCP 配置文件中添加（`~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "npx",
      "args": [
        "-y",
        "hitl-mcp",
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id",
        "--project-name", "my-project"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

### 方式二：本地安装

```bash
# 使用 pnpm（推荐）
pnpm add -g hitl-mcp

# 或使用 npm
npm install -g hitl-mcp
```

然后在 MCP 配置中：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "hitl-mcp",
      "args": [
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id",
        "--project-name", "my-project"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

### 方式三：从源码运行（开发）

```bash
# 克隆仓库
git clone git@github.com:jeffkit/tunely.git
cd tunely/packages/mcp-server-ts

# 安装依赖
pnpm install

# 构建
pnpm run build

# 运行
node dist/index.js --service-url http://hitl.woa.com/api --chat-id your-chat-id
```

在 MCP 配置中：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "node",
      "args": [
        "/path/to/tunely/packages/mcp-server-ts/dist/index.js",
        "--service-url", "http://hitl.woa.com/api",
        "--chat-id", "your-chat-id"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

---

## 命令行参数说明

| 参数 | 说明 | 是否必填 | 默认值 |
|------|------|----------|--------|
| `--service-url` | HIL Server 地址（如 `http://hitl.woa.com/api`） | ✅ 必填 | `http://localhost:8081` |
| `--chat-id` | 默认 Chat ID（群聊或私聊） | ✅ 必填 | - |
| `--project-name` | 项目名称，用于标识消息来源 | 可选 | - |
| `--timeout` | 等待回复超时时间（秒） | 可选 | `1200` (20 分钟) |

### 获取 Chat ID

**方法1**：直接在企微中 @机器人 发送任意消息，机器人会自动回复 Chat ID

**方法2**：查看服务器日志，找到 `chatid` 字段

---

## 环境变量配置

除了命令行参数，也可以通过环境变量配置（命令行参数优先级更高）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SERVICE_URL` | HIL Server 地址 | `http://localhost:8081` |
| `DEFAULT_CHAT_ID` | 默认 Chat ID | - |
| `DEFAULT_PROJECT_NAME` | 默认项目名称 | - |
| `DEFAULT_TIMEOUT` | 超时时间（秒） | `1200` |
| `POLL_INTERVAL` | 轮询间隔（秒，内部使用） | `2` |

在 MCP 配置中使用环境变量：

```json
{
  "mcpServers": {
    "wecom-hil": {
      "command": "npx",
      "args": ["-y", "hitl-mcp"],
      "env": {
        "SERVICE_URL": "http://hitl.woa.com/api",
        "DEFAULT_CHAT_ID": "your-chat-id",
        "DEFAULT_PROJECT_NAME": "my-project",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    }
  }
}
```

---

## 使用方法

### AI Agent 调用示例

```typescript
// 发送消息并等待回复
const result = await send_and_wait_reply({
  message: "请确认是否继续？",
  project_name: "my-project",  // 可选，用于标识消息来源
});

// 仅发送消息，不等待回复
const result = await send_message_only({
  message: "任务已完成！"
});
```

### 返回格式

**send_and_wait_reply**：

```json
{
  "status": "success" | "timeout" | "error",
  "replies": [
    {
      "msg_type": "text",
      "content": "用户回复的文本",
      "from_user": {"name": "张三", "alias": "zhangsan"},
      "timestamp": "2024-01-01T10:30:00"
    }
  ],
  "message": "收到 1 条回复"
}
```

**send_message_only**：

```json
{
  "status": "success" | "error",
  "message": "消息发送成功"
}
```

### 用户回复方式

1. **单会话场景**：直接回复即可
2. **多会话场景**：使用「引用回复」功能精确选择要回复的消息

---

## 开发指南

### 项目结构

```
mcp_server_ts/
├── src/
│   ├── index.ts          # 入口文件（命令行解析）
│   ├── server.ts         # MCP Server 主程序
│   ├── config.ts         # 配置管理
│   └── wecom-client.ts   # HTTP 客户端
├── dist/                 # 编译输出目录
├── package.json
├── tsconfig.json
└── README.md
```

### 本地开发

```bash
# 安装依赖
pnpm install

# 开发模式（使用 tsx）
pnpm run dev -- --service-url http://hitl.woa.com/api --chat-id your-chat-id

# 类型检查
pnpm run typecheck

# 构建
pnpm run build
```

### 发布到 npm

```bash
# 构建
pnpm run build

# 发布
npm publish --access public
```

---

## 与 Python 版本的对比

| 特性 | Python 版 | TypeScript 版 |
|------|-----------|---------------|
| 安装方式 | `uvx` / `pipx` / `pip` | `npx` / `npm` / `pnpm` |
| 运行时 | Python 3.10+ | Node.js 18+ |
| 类型系统 | 运行时类型检查（Pydantic） | 编译时类型检查（TypeScript） |
| 命令行参数 | ✅ 完全一致 | ✅ 完全一致 |
| 配置方式 | ✅ 完全一致 | ✅ 完全一致 |
| 功能 | ✅ 完全一致 | ✅ 完全一致 |

---

## 常见问题

### Q: 出现 502 Bad Gateway 错误

**原因**：通常是设置了 HTTP 代理。

**解决方案**：在 MCP 配置中禁用代理：

```json
"env": {
  "http_proxy": "",
  "https_proxy": "",
  "all_proxy": ""
}
```

### Q: npx 每次都下载很慢

使用 `-y` 参数可以跳过确认，或者全局安装：

```bash
pnpm add -g hitl-mcp
```

然后在 MCP 配置中直接使用 `hitl-mcp` 命令。

### Q: 如何查看日志？

MCP Server 的日志会输出到 stderr，可以在 Cursor 的开发者工具中查看。

---

## 服务端部署

请参考主项目的 [README.md](../README.md) 了解如何部署 HIL Server。

---

## License

MIT
