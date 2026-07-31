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
 *   hitl-mcp --engine telegram --tg-token <token> --service-url http://localhost:8081
 *   hitl-mcp --engine discord --discord-token <token> --service-url http://localhost:8081
 *   hitl-mcp --engine feishu --feishu-app-id <id> --feishu-app-secret <secret> --service-url http://localhost:8081
 */

import { program } from 'commander';
import { homedir } from 'os';
import { createConfig, setConfig, type EngineType } from './config.js';
import { startServer } from './server.js';
import { runSetup } from './setup.js';

program
  .name('hitl-mcp')
  .description('Human-in-the-Loop MCP Server（支持 企业微信 AI Bot / 微信 iLink 内置引擎）')
  .version('0.6.1')

  // ── 子命令：iLink 一键安装 + 服务化 ───────────────────────────────────────
  .command('ilink-setup')
  .description(
    '一键安装并服务化 HITL Server（macOS launchd / Linux systemd）。\n' +
    '无需任何参数：服务启动后自动打开管理台，在浏览器里完成扫码、激活、复制配置。'
  )
  .option('--service-url <url>', 'HITL Server 地址', 'http://localhost:8081')
  .option('--token-store <path>', 'iLink 凭证存储路径（跨重启保留登录态）', '~/.hitl/ilink_store.json')
  .option('--uninstall', '卸载服务（凭证保留）')
  .action(async (opts) => {
    const tokenStore = opts.tokenStore.replace(/^~/, homedir());
    try {
      await runSetup({
        serviceUrl: opts.serviceUrl,
        tokenStorePath: tokenStore,
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
    '引擎类型: auto | wecom-aibot | ilink | telegram | discord | feishu（默认: auto，按管理台已配置引擎自动选用）',
    'auto'
  )
  .option('--chat-id <id>',       '默认 chatid（wecom-aibot / telegram / discord / feishu 引擎）')
  .option('--bot-key <key>',     '可选。单 bot 可不传，后端按引擎类型自动路由；管理台绑定多个 bot 时用它指定')
  .option('--project-name <name>','默认项目名称')
  .option('--timeout <seconds>',  '等待回复超时（秒，默认 1200）', parseInt)

  // ── 共享部署模式（HITL Server 部署在服务器端，全员共用一个企微 AI Bot）────────
  .option('--shared',             '共享部署模式：recipient(chat_id) 必填，请求带 API Key 鉴权')
  .option('--api-key <key>',      'HITL Server 的 API Key（共享模式下必填，作为 Authorization Bearer）')

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

  // ── Telegram / Discord / 飞书 参数 ──────────────────────────────────────────
  .option('--tg-token <token>',           'Telegram Bot Token（engine=telegram 时向 HITL Server 自动注册）')
  .option('--discord-token <token>',      'Discord Bot Token（engine=discord 时向 HITL Server 自动注册）')
  .option('--feishu-app-id <id>',         '飞书企业自建应用 App ID（engine=feishu 时使用）')
  .option('--feishu-app-secret <secret>', '飞书企业自建应用 App Secret（engine=feishu 时使用）')

  // ── 默认行为（无子命令时）：启动 MCP server ──────────────────────────────
  // 用 program.action 而非顶层直接调用，确保子命令（ilink-setup）触发时不会同时启动 server。
  .action(() => {
    const opts = program.opts();

    const engine = (opts.engine as EngineType) ?? 'auto';
    if (!['auto', 'ilink', 'wecom-aibot', 'telegram', 'discord', 'feishu'].includes(engine)) {
      console.error(`[Main] 不支持的 --engine: ${opts.engine}（可选: auto | ilink | wecom-aibot | telegram | discord | feishu）`);
      process.exit(1);
    }

    const config = createConfig({
      engine,
      defaultRecipient:   opts.chatId ?? '',
      defaultProjectName: opts.projectName ?? '',
      defaultTimeout:     opts.timeout,
      botKey:             opts.botKey ?? '',
      shared:             !!opts.shared,
      apiKey:             opts.apiKey ?? '',
      // HIL Server
      serviceUrl:         opts.serviceUrl,
      // WeCom AI Bot
      wecomBotId:         opts.botId,
      wecomBotSecret:     opts.botSecret,
      // iLink
      ilinkTokenStorePath: opts.tokenStore,
      ilinkBaseUrl:        opts.baseUrl,
      // Telegram / Discord / 飞书
      tgToken:            opts.tgToken,
      discordToken:       opts.discordToken,
      feishuAppId:        opts.feishuAppId,
      feishuAppSecret:    opts.feishuAppSecret,
    });

    setConfig(config);

    startServer().catch((err) => {
      console.error('[Main] 启动失败:', err);
      process.exit(1);
    });
  });

program.parse();
