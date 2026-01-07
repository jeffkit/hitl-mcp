# 快速开始测试和发布

## 🧪 快速测试（5 分钟）

### 1. 更新 Cursor MCP 配置

编辑 `~/.cursor/mcp.json`，添加或修改：

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

### 2. 重启 Cursor

完全退出并重新启动 Cursor。

### 3. 测试工具

在 Cursor 中测试：

```
请使用 send_message_only 发送消息 "测试 TypeScript 版 MCP 🎉" 到企微
```

如果企微收到消息，说明测试成功！✅

### 4. 测试等待回复（可选）

```
请使用 send_and_wait_reply 发送消息 "请回复 OK" 并等待我的回复
```

然后在企微中回复 "OK"，看 AI 是否收到。

---

## 📦 发布到 npm

### 方法一：使用发布脚本（推荐）

```bash
cd /Users/kongjie/projects/hil-mcp/mcp_server_ts
./publish.sh
```

脚本会自动：
- ✅ 检查 npm 登录状态
- ✅ 运行类型检查
- ✅ 构建项目
- ✅ 测试命令行
- ✅ 检查包内容
- ✅ 发布到 npm

### 方法二：手动发布

```bash
cd /Users/kongjie/projects/hil-mcp/mcp_server_ts

# 1. 登录 npm（如果还没登录）
npm login

# 2. 构建
pnpm run build

# 3. 检查包内容
npm pack --dry-run

# 4. 发布
npm publish --access public
```

### 验证发布

```bash
# 查看包信息
npm view @hitl/mcp-server

# 测试安装
npx -y @hitl/mcp-server --help
```

---

## 🔄 更新 Cursor 配置使用 npm 版本

发布成功后，可以更新 Cursor 配置使用 npm 版本：

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

---

## 📝 后续版本发布

```bash
# 1. 更新代码...

# 2. 更新版本号
npm version patch  # 或 minor / major

# 3. 构建和发布
pnpm run build
npm publish --access public

# 4. 推送 git tag
git push --tags
```

---

## ❓ 常见问题

### npm login 失败

确保使用正确的 npm 账号和密码。如果启用了 2FA，需要提供验证码。

### 包名已被占用

修改 `package.json` 中的 `name` 字段，例如：
- `@your-username/hitl-mcp`
- `hitl-mcp-ts`

### 发布后 npx 找不到包

等待几分钟，npm 需要时间同步。可以访问 https://www.npmjs.com/package/@hitl/mcp-server 查看。

---

## 📚 更多文档

- [TEST.md](./TEST.md) - 详细测试指南
- [PUBLISH.md](./PUBLISH.md) - 发布流程说明
- [README.md](./README.md) - 用户使用文档
