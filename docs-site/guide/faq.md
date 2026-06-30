# 常见问题

## 收不到消息

按引擎分别排查。

### iLink（微信）

1. **是否给 ClawBot 发过消息？** iLink 的机制是「你先找 Bot，Bot 才认识你」。打开手机微信，搜索 **ClawBot**，加好友并发一条任意消息（如「你好」）。这是最常见的原因。
2. **是否扫码登录了？** 打开 `http://localhost:8081/console`，在 iLink 引擎页面看登录状态，必要时重新扫码。
3. **token-store 路径是不是绝对路径？** 相对路径会因 MCP 客户端工作目录变化而失效，导致每次都要重新扫码。用 `ilink-setup` 或指定 `--token-store ~/.hil-mcp/ilink_store.json`。
4. **hitl-server 是否在跑？** `curl http://localhost:8081/api/ilink/login_status?bot_key=ilink-bot-1` 应返回 JSON。

### wecom-aibot（企微）

1. **Bot ID / Bot Secret 是否正确？** 在企微管理后台 → 应用管理 → AI Bot → 基本信息里核对。
2. **Bot 是否启用了「AI 对话」权限？**
3. **`--chat-id` 是否正确？** 不填则每次调用都要手动指定 `recipient`。可让管理员在企微后台查群 ID，或在企微里给 bot 发消息后从管理台日志看 `chatid`。
4. **网络能否访问 `openws.work.weixin.qq.com`？** 企微 WS 需要出网。

## 出现 502 Bad Gateway

通常是机器设了 HTTP 代理，`npx` 访问 `localhost` 走了代理。在 MCP 配置的 `env` 里清空代理：

```json
"env": {
  "http_proxy": "",
  "https_proxy": "",
  "all_proxy": ""
}
```

## npx 每次都下载很慢

全局安装一次：

```bash
pnpm add -g hitl-mcp   # 或 npm install -g hitl-mcp
```

然后配置里把 `command` 改成 `hitl-mcp`，去掉 `npx -y`。

## 工具返回 not_initialized

说明引擎没初始化好。返回里带 `init_url`，打开它（即管理台 `http://localhost:8081/console`）：

- iLink：扫码登录 + 给 ClawBot 发条消息。
- wecom-aibot：填好 Bot 凭证 + 在企微给 bot 发条消息激活收件人。

完成后重试即可，无需重启 MCP 客户端。

## 多个会话同时等回复，AI 拿到错的回复

这是「多会话冲突」。hitl-server 会给每条消息分配 `[#短ID]`，请用微信/企微的 **引用回复** 功能精确选要回的那条。单会话直接回复即可。

## 等待回复超时了

默认超时 20 分钟（1200 秒）。想延长，在 MCP 配置里加 `--timeout 3600`（单位秒）。注意超时后该会话关闭，需要重新发。

## 怎么查看日志

- **hitl-server**（前台运行）：直接看终端输出。
- **hitl-server**（launchd 服务化）：`tail -f ~/.hitl/logs/hitl-server.err.log`
- **MCP 端**：日志输出到 stderr，可在 Cursor 的开发者工具里查看。

## 卸载 / 重装 iLink 服务

```bash
# 卸载 launchd 服务（凭证保留）
npx hitl-mcp ilink-setup --uninstall

# 彻底清理凭证与日志
rm -rf ~/.hitl ~/.hil-mcp
```

## hitl-server 端口被占用

改端口：`HITL_PORT=8082 hitl-server`（或 `HITL_PORT=8082 ./hitl-server/hitl-server` 用 tar.gz 二进制），并把 MCP 配置里的 `--service-url` 改成对应地址。包管理器安装的用户改服务配置（brew plist / systemd unit）后重启服务。

## 还是不行

[开个 issue](https://github.com/jeffkit/hitl-mcp/issues)，附上：

- 用的引擎（ilink / wecom-aibot）
- hitl-server 日志（`~/.hitl/logs/`）
- MCP 客户端与版本
- 复现步骤
