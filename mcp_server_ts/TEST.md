# 测试指南

本文档说明如何测试 TypeScript 版 hitl-mcp。

## 测试准备

### 1. 构建项目

```bash
cd /Users/kongjie/projects/hil-mcp/mcp_server_ts
pnpm run build
```

### 2. 测试命令行

```bash
# 测试帮助信息
node dist/index.js --help

# 测试版本信息
node dist/index.js --version
```

预期输出：

```
Usage: hitl-mcp [options]

WeCom HIL MCP Server - 让 AI 能够发送消息到企业微信并等待用户回复

Options:
  -V, --version          output the version number
  --service-url <url>    HIL Server 的访问地址（如 http://hitl.woa.com/api）
  --chat-id <id>         默认发送消息的 Chat ID（群聊或私聊）
  --project-name <name>  默认项目名称，用于标识消息来源
  --timeout <seconds>    默认等待回复超时时间（秒），默认 1200 秒（20 分钟）
  -h, --help             display help for command
```

## 集成测试（在 Cursor 中测试）

### 方法一：使用本地构建版本

1. **添加测试配置到 Cursor**

编辑 `~/.cursor/mcp.json`，添加以下配置：

```json
{
  "mcpServers": {
    "wecom-hil-ts-test": {
      "command": "node",
      "args": [
        "/Users/kongjie/projects/hil-mcp/mcp_server_ts/dist/index.js",
        "--service-url",
        "https://hitl.woa.com/api",
        "--chat-id",
        "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A",
        "--timeout",
        "3600"
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

也可以直接复制 `test-mcp-config.json` 的内容。

2. **重启 Cursor**

完全退出并重新启动 Cursor，让新配置生效。

3. **验证 MCP 加载**

在 Cursor 中打开开发者工具（View -> Developer Tools），查看是否有错误。

4. **测试工具调用**

在 Cursor 中与 AI 对话，测试以下场景：

**场景 1：发送消息并等待回复**

```
请使用 send_and_wait_reply 发送消息 "测试 TypeScript 版 MCP" 到企微
```

预期：
- AI 调用工具发送消息
- 企微收到消息
- 用户在企微回复后，AI 收到回复内容

**场景 2：仅发送消息（不等待）**

```
请使用 send_message_only 发送通知 "测试完成" 到企微
```

预期：
- AI 调用工具发送消息
- 企微收到消息
- 工具立即返回成功

**场景 3：测试图片上传（可选）**

```
请发送消息 "这是一个测试图片" 并附带图片 /path/to/test.png
```

预期：
- 图片上传成功
- 企微收到文本消息和图片

### 方法二：使用 npx（发布后）

发布到 npm 后，修改配置：

```json
{
  "mcpServers": {
    "wecom-hil-ts": {
      "command": "npx",
      "args": [
        "-y",
        "@hitl/mcp-server",
        "--service-url",
        "https://hitl.woa.com/api",
        "--chat-id",
        "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A"
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

## 对比测试（Python vs TypeScript）

### 1. 添加两个配置

```json
{
  "mcpServers": {
    "wecom-hil-python": {
      "command": "uvx",
      "args": [
        "hitl-mcp",
        "--service-url", "https://hitl.woa.com/api",
        "--chat-id", "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A"
      ],
      "env": {
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": ""
      }
    },
    "wecom-hil-ts": {
      "command": "node",
      "args": [
        "/Users/kongjie/projects/hil-mcp/mcp_server_ts/dist/index.js",
        "--service-url", "https://hitl.woa.com/api",
        "--chat-id", "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A"
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

### 2. 对比测试点

| 测试项 | Python 版 | TypeScript 版 |
|--------|-----------|---------------|
| 启动速度 | ? | ? |
| 消息发送 | ✅ | ? |
| 等待回复 | ✅ | ? |
| 超时处理 | ✅ | ? |
| 图片上传 | ✅ | ? |
| 错误处理 | ✅ | ? |
| 日志输出 | ✅ | ? |

## 故障排查

### 问题 1：MCP Server 无法启动

**症状**：Cursor 报告 MCP 连接失败

**排查步骤**：
1. 检查构建是否成功：`ls -la dist/index.js`
2. 测试独立运行：`node dist/index.js --help`
3. 查看 Cursor 开发者工具的错误日志

### 问题 2：工具调用失败

**症状**：AI 无法调用 send_and_wait_reply 等工具

**排查步骤**：
1. 确认 MCP Server 已正确加载（在 Cursor 中应该能看到工具列表）
2. 检查 service-url 是否正确
3. 检查 chat-id 是否正确
4. 查看 stderr 日志输出

### 问题 3：无法连接 HIL Server

**症状**：发送消息时报 HTTP 错误

**排查步骤**：
1. 测试网络连接：`curl https://hitl.woa.com/api/health`
2. 检查代理设置（确保已禁用）
3. 查看详细错误信息

## 测试清单

使用以下清单确保所有功能正常：

- [ ] 命令行 `--help` 正常输出
- [ ] 命令行 `--version` 正常输出
- [ ] Cursor 中 MCP Server 成功加载
- [ ] 可以看到 send_and_wait_reply 工具
- [ ] 可以看到 send_message_only 工具
- [ ] send_message_only 能发送文本消息
- [ ] send_and_wait_reply 能发送并等待回复
- [ ] 超时处理正常
- [ ] 图片上传功能正常（如果测试）
- [ ] 错误处理正常（测试错误的 chat-id）
- [ ] 与 Python 版行为一致

## 性能测试（可选）

### 启动时间

```bash
# Python 版
time uvx hitl-mcp --help

# TypeScript 版
time node dist/index.js --help
```

### 消息发送延迟

记录从调用工具到消息到达企微的时间。

### 内存占用

```bash
# 查看进程内存占用
ps aux | grep hitl
```

## 回归测试

每次更新代码后，重新运行本测试指南中的所有测试用例。
