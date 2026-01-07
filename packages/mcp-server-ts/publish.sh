#!/bin/bash

# 发布到 npm 脚本

set -e  # 遇到错误立即退出

echo "🚀 开始发布 @hitl/mcp-server 到 npm..."
echo ""

# 检查是否已登录 npm
echo "📝 检查 npm 登录状态..."
if ! npm whoami > /dev/null 2>&1; then
    echo "❌ 未登录 npm，请先运行: npm login"
    exit 1
fi
echo "✅ 已登录为: $(npm whoami)"
echo ""

# 检查 git 状态
if [[ -n $(git status -s) ]]; then
    echo "⚠️  Git 工作区有未提交的更改，建议先提交:"
    git status -s
    read -p "是否继续？(y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 类型检查
echo "🔍 运行类型检查..."
pnpm run typecheck
echo "✅ 类型检查通过"
echo ""

# 构建项目
echo "🔨 构建项目..."
pnpm run build
echo "✅ 构建完成"
echo ""

# 测试命令行
echo "🧪 测试命令行..."
node dist/index.js --help > /dev/null
echo "✅ 命令行测试通过"
echo ""

# 检查包内容
echo "📦 检查包内容..."
npm pack --dry-run
echo ""

# 确认发布
read -p "确认发布到 npm？(y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 取消发布"
    exit 1
fi

# 发布到 npm
echo "📤 发布到 npm..."
npm publish --access public

echo ""
echo "✅ 发布成功！"
echo ""
echo "验证发布："
echo "  npm view @hitl/mcp-server"
echo "  npx -y @hitl/mcp-server --help"
echo ""
echo "推送 git tag（可选）："
echo "  git tag v$(node -p \"require('./package.json').version\")"
echo "  git push --tags"
