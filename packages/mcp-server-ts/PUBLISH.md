# 发布到 npm 指南

本文档说明如何将 TypeScript 版 hitl-mcp 发布到 npm。

## 前置准备

### 1. 注册 npm 账号

如果还没有 npm 账号，访问 https://www.npmjs.com/signup 注册。

### 2. 登录 npm

```bash
npm login
```

按提示输入用户名、密码和邮箱。

### 3. 验证登录状态

```bash
npm whoami
```

## 发布流程

### 步骤 1：确保代码已构建

```bash
cd /Users/kongjie/projects/hil-mcp/mcp_server_ts
pnpm run build
```

### 步骤 2：检查包内容

```bash
npm pack --dry-run
```

这会显示将要发布的文件列表，确保包含：
- `dist/` 目录（编译后的 JS 文件）
- `README.md`
- `LICENSE`
- `package.json`

### 步骤 3：测试包安装（可选）

```bash
# 在临时目录测试
npm pack
npm install -g ./hitl-mcp-server-0.2.1.tgz
hitl-mcp --help
npm uninstall -g @hitl/mcp-server
```

### 步骤 4：发布到 npm

```bash
npm publish --access public
```

> **注意**：由于包名带 `@` scope（`@hitl/mcp-server`），需要使用 `--access public` 参数。

### 步骤 5：验证发布

```bash
# 查看 npm 上的包信息
npm view @hitl/mcp-server

# 测试安装
npx -y @hitl/mcp-server --help
```

## 版本管理

### 更新版本号

根据更改类型更新版本号：

```bash
# 修复 bug（0.2.1 -> 0.2.2）
npm version patch

# 新增功能（0.2.1 -> 0.3.0）
npm version minor

# 破坏性更改（0.2.1 -> 1.0.0）
npm version major
```

### 发布新版本

```bash
# 1. 更新版本号
npm version patch

# 2. 构建
pnpm run build

# 3. 发布
npm publish --access public

# 4. 推送 git tag
git push --tags
```

## 撤销发布

如果发布后发现问题，可以在 72 小时内撤销：

```bash
npm unpublish @hitl/mcp-server@0.2.1
```

> **警告**：撤销发布会影响已经使用该版本的用户。建议直接发布修复版本。

## 常见问题

### Q: 包名已被占用

如果 `@hitl/mcp-server` 已被占用，可以更改为：
- `@your-username/hitl-mcp`
- `hitl-mcp-ts`
- `wecom-hitl-mcp`

### Q: 发布失败：403 Forbidden

确保：
1. 已登录 npm（`npm whoami`）
2. 使用了 `--access public` 参数
3. 有权限发布该 scope 下的包

### Q: 如何测试未发布的包？

使用 `npm link`：

```bash
cd /Users/kongjie/projects/hil-mcp/mcp_server_ts
npm link

# 在其他项目中
npm link @hitl/mcp-server
```

## 发布检查清单

- [ ] 代码已构建（`pnpm run build`）
- [ ] 版本号已更新（`package.json`）
- [ ] README 完整准确
- [ ] LICENSE 文件存在
- [ ] 测试命令正常（`pnpm run test`）
- [ ] 包内容正确（`npm pack --dry-run`）
- [ ] 已登录 npm（`npm whoami`）
- [ ] Git 已提交所有更改
- [ ] 准备好发布（`npm publish --access public`）

## 自动化发布（可选）

可以创建 GitHub Actions 自动发布：

```yaml
# .github/workflows/publish.yml
name: Publish to npm

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: pnpm/action-setup@v2
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
          registry-url: 'https://registry.npmjs.org'
      - run: pnpm install
      - run: pnpm run build
      - run: npm publish --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```
