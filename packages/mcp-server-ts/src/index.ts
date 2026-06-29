#!/usr/bin/env node

/**
 * hitl-mcp — Human-in-the-Loop MCP Server（三合一版本）
 *
 * 用法：
 *   # 对接 HIL Server（原有，默认）
 *   hitl-mcp --engine hil --service-url http://hitl.woa.com/api --chat-id xxx
 *
 *   # 企业微信智能机器人（直连，无需 HIL Server）
 *   hitl-mcp --engine wecom-aibot --bot-id xxx --bot-secret yyy --chat-id xxx
 *
 *   # 微信 ClawBot/iLink（直连，无需 HIL Server）
 *   hitl-mcp --engine ilink --user-id xxx --token-store /path/to/store.json
 */

import { program } from 'commander';
import { homedir } from 'os';
import { createConfig, setConfig, type EngineType } from './config.js';
import { startServer } from './server.js';
import { runSetup } from './setup.js';

program
  .name('hitl-mcp')
  .description('Human-in-the-Loop MCP Server（支持 HIL Server / 企业微信 AI Bot / 微信 iLink）')
  .version('0.3.0')

  // ── 子命令：iLink 一键安装 + 服务化 ───────────────────────────────────────
  .command('ilink-setup')
  .description('一键安装并服务化 iLink worker（macOS launchd）：建 venv、写 plist、扫码登录、打印 Cursor 配置')
  .option('--ilink-base-url <url>', 'iLink API 地址', 'https://ilinkai.weixin.qq.com')
  .option('--bot-key <key>', 'worker 的 bot_key（MCP 端按此路由）', 'ilink-bot-1')
  .option('--service-url <url>', 'HIL Server 地址', 'http://localhost:8081')
  .option('--token-store <path>', 'iLink 凭证存储路径', '~/.hil-mcp/ilink_store.json')
  .option('--project-name <name>', '写入 Cursor 配置的默认项目名')
  .option('--uninstall', '卸载 launchd 服务（凭证保留）')
  .action(async (opts) => {
    const tokenStore = opts.tokenStore.replace(/^~/, homedir());
    try {
      await runSetup({
        ilinkBaseUrl: opts.ilinkBaseUrl,
        botKey: opts.botKey,
        serviceUrl: opts.serviceUrl,
        tokenStorePath: tokenStore,
        projectName: opts.projectName,
        uninstall: !!opts.uninstall,
      });
      process.exit(0);
    } catch (e) {
      console.error('[setup] 失败:', e instanceof Error ? e.message : e);
      process.exit(1);
    }
  });

program
  // ── 通用参数（默认行为：启动 MCP server） ────────────────────────────────
  .option(
    '--engine <type>',
    '引擎类型: hil | wecom-aibot | ilink（默认: hil）',
    'hil'
  )
  .option('--chat-id <id>',       '默认 chatid（hil / wecom-aibot 引擎）')
  .option('--bot-key <key>',     'bot_key（ilink / wecom-aibot 走 HIL Server 时的路由键）')
  .option('--project-name <name>','默认项目名称')
  .option('--timeout <seconds>',  '等待回复超时（秒，默认 1200）', parseInt)

  // ── HIL Server 参数 ───────────────────────────────────────────────────────
  .option('--service-url <url>',  'HIL Server 地址（engine=hil 时使用）')

  // ── 企业微信 AI Bot 参数 ──────────────────────────────────────────────────
  .option('--bot-id <id>',        '企业微信 AI Bot ID（engine=wecom-aibot 时使用）')
  .option('--bot-secret <secret>','企业微信 AI Bot Secret（engine=wecom-aibot 时使用）')

  // ── iLink 参数 ────────────────────────────────────────────────────────────
  .option(
    '--token-store <path>',
    'iLink token 存储路径（engine=ilink 时使用，默认: ./data/ilink_store.json）'
  )
  .option(
    '--base-url <url>',
    'iLink API 基础地址（扫码登录、getupdates、sendmessage，默认: https://ilinkai.weixin.qq.com）'
  )

  // ── 默认行为（无子命令时）：启动 MCP server ──────────────────────────────
  // 用 program.action 而非顶层直接调用，确保子命令（ilink-setup）触发时不会同时启动 server。
  .action(() => {
    const opts = program.opts();

    const config = createConfig({
      engine:             (opts.engine as EngineType) ?? 'hil',
      defaultRecipient:   opts.chatId ?? '',
      defaultProjectName: opts.projectName ?? '',
      defaultTimeout:     opts.timeout,
      botKey:             opts.botKey ?? '',
      // HIL
      serviceUrl:         opts.serviceUrl,
      // WeCom AI Bot
      wecomBotId:         opts.botId,
      wecomBotSecret:     opts.botSecret,
      // iLink
      ilinkTokenStorePath: opts.tokenStore,
      ilinkBaseUrl:        opts.baseUrl,
    });

    setConfig(config);

    startServer().catch((err) => {
      console.error('[Main] 启动失败:', err);
      process.exit(1);
    });
  });

program.parse();
