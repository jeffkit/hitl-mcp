#!/usr/bin/env node

/**
 * hitl-mcp — Human-in-the-Loop MCP Server（内置引擎版本）
 *
 * 用法：
 *   # 自动：按管理台已配置的内置引擎选用（默认，推荐）
 *   hitl-mcp --service-url http://localhost:8081
 *
 *   # 指定引擎（覆盖 auto）
 *   hitl-mcp --engine ilink --service-url http://localhost:8081
 *   hitl-mcp --engine wecom-aibot --service-url http://localhost:8081
 */

import { program } from 'commander';
import { homedir } from 'os';
import { createConfig, setConfig, type EngineType } from './config.js';
import { startServer } from './server.js';
import { runSetup } from './setup.js';

program
  .name('hitl-mcp')
  .description('Human-in-the-Loop MCP Server（支持 企业微信 AI Bot / 微信 iLink 内置引擎）')
  .version('0.3.0')

  // ── 子命令：iLink 一键安装 + 服务化 ───────────────────────────────────────
  .command('ilink-setup')
  .description('一键安装并服务化 iLink worker（macOS launchd）：建 venv、写 plist、扫码登录、打印 Cursor 配置')
  .option('--ilink-base-url <url>', 'iLink API 地址', 'https://ilinkai.weixin.qq.com')
  .option('--bot-key <key>', 'worker 的 bot_key（MCP 端按此路由）', 'ilink-bot-1')
  .option('--service-url <url>', 'HITL Server 地址', 'http://localhost:8081')
  .option('--token-store <path>', 'iLink 凭证存储路径', '~/.hil-mcp/ilink_store.json')
  .option('--project-name <name>', '写入 Cursor 配置的默认项目名')
  .option('--enable-wecom-aibot', '同时启用企微 AI Bot 内置引擎')
  .option('--wecom-bot-id <id>', '企微 AI Bot ID')
  .option('--wecom-bot-secret <secret>', '企微 AI Bot Secret')
  .option('--wecom-bot-key <key>', '企微 AI Bot 的 bot_key（MCP 端按此路由）', 'wecom-aibot-1')
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
        enableWecomAibot: !!opts.enableWecomAibot,
        wecomBotId: opts.wecomBotId ?? '',
        wecomBotSecret: opts.wecomBotSecret ?? '',
        wecomBotKey: opts.wecomBotKey,
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
    '引擎类型: auto | wecom-aibot | ilink（默认: auto，按管理台已配置引擎自动选用）',
    'auto'
  )
  .option('--chat-id <id>',       '默认 chatid（wecom-aibot 引擎）')
  .option('--bot-key <key>',     '可选。单 bot 可不传，后端按引擎类型自动路由；管理台绑定多个 bot 时用它指定')
  .option('--project-name <name>','默认项目名称')
  .option('--timeout <seconds>',  '等待回复超时（秒，默认 1200）', parseInt)

  // ── HITL Server 地址 ─────────────────────────────────────────────────────
  .option('--service-url <url>',  'HITL Server 地址（内置引擎走 /api/send、/api/poll 等）')

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

    const engine = (opts.engine as EngineType) ?? 'auto';
    if (engine !== 'auto' && engine !== 'ilink' && engine !== 'wecom-aibot') {
      console.error(`[Main] 不支持的 --engine: ${opts.engine}（可选: auto | ilink | wecom-aibot）`);
      process.exit(1);
    }

    const config = createConfig({
      engine,
      defaultRecipient:   opts.chatId ?? '',
      defaultProjectName: opts.projectName ?? '',
      defaultTimeout:     opts.timeout,
      botKey:             opts.botKey ?? '',
      // HIL Server
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
