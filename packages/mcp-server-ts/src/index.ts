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
import { createConfig, setConfig, type EngineType } from './config.js';
import { startServer } from './server.js';

program
  .name('hitl-mcp')
  .description('Human-in-the-Loop MCP Server（支持 HIL Server / 企业微信 AI Bot / 微信 iLink）')
  .version('0.3.0')

  // ── 通用参数 ──────────────────────────────────────────────────────────────
  .option(
    '--engine <type>',
    '引擎类型: hil | wecom-aibot | ilink（默认: hil）',
    'hil'
  )
  .option('--chat-id <id>',       '默认 chatid（hil / wecom-aibot 引擎）')
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

  .parse();

const opts = program.opts();

const config = createConfig({
  engine:             (opts.engine as EngineType) ?? 'hil',
  defaultRecipient:   opts.chatId ?? '',
  defaultProjectName: opts.projectName ?? '',
  defaultTimeout:     opts.timeout,
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
