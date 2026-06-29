# HITL Server 打包与发布

HITL Server 是个人电脑端可安装的 Human-in-the-Loop 服务，内置 **iLink** 与 **企业微信 AI Bot** 两个引擎。
发布形态：**自包含二进制**（PyInstaller one-dir，内嵌管理台），再封装为 macOS Homebrew 与 Linux deb/rpm。

> 旧 HIL service（fly-pigeon / 飞鸽传书 Direct 模式）不在个人端发行范围；其代码保留，
> 但 `fly-pigeon` 已转为可选依赖（`pip install "hitl-server[direct]"`），打包时不收集。

## 产物

| 平台 | 制品 | 安装方式 |
|---|---|---|
| macOS arm64 | `hitl-server-darwin-arm64.tar.gz` | Homebrew / 手动解压 |
| macOS x86_64 | `hitl-server-darwin-x86_64.tar.gz` | Homebrew / 手动解压 |
| Linux x86_64 | `hitl-server-linux-x86_64.tar.gz` / `.deb` / `.rpm` | dpkg / rpm / 手动解压 |

二进制运行：`./hitl-server`（读环境变量，默认监听 `127.0.0.1:8081`，管理台 `/console`）。

## 本地构建

```bash
cd packages/hitl-server
bash packaging/build.sh            # 产出 dist/hitl-server/ 与 dist/hitl-server-<os>-<arch>.tar.gz
```

依赖：`uv`、`pnpm`、`python>=3.10`。`build.sh` 会自动构建管理台 dist、安装 PyInstaller、打包。

## Linux deb / rpm

```bash
bash packaging/build.sh                      # 先产出 dist/hitl-server/
sudo gem install fpm --no-document
bash packaging/build-linux-pkgs.sh 2.1.0     # 产出 dist/*.deb / *.rpm
```

安装：`sudo dpkg -i hitl-server_*.deb` 或 `sudo rpm -i hitl-server-*.rpm`，然后：
```bash
sudo systemctl enable --now hitl-server
```
systemd unit 默认开启 iLink 引擎；企微 AI Bot 在管理台运行时配置（凭证落盘后自动恢复）。

## macOS Homebrew

发版 CI 会渲染 `hitl-server.rb` 并附在 Release。发布到 tap 后：
```bash
brew tap jeffkit/hitl
brew install hitl-server
brew services start hitl-server
```
或直接用 Release 里的 formula：`brew install --formula ./hitl-server.rb`。

## 发版流程

```bash
# 1. 改 packages/hitl-server/pyproject.toml 的 version 与 app.py 版本号
# 2. 提交并打 tag
git tag hitl-server/v<version>
git push github hitl-server/v<version>
```
CI（`.github/workflows/release-hitl-server.yml`）在 macOS 14/13 与 Ubuntu 22.04 上分别
PyInstaller 构建、Linux 上额外打 deb/rpm，计算 sha256，渲染 Homebrew formula，发布到 GitHub Release。

## 目录约定

- 数据/凭证：`~/.hitl`（首次运行若存在旧 `~/.hil-mcp` 会自动迁移）
- 日志：`~/.hitl/logs/hitl-server.{out,err}.log`
- macOS launchd label：`com.woa.hitl-mcp.hitl-server`
