#!/usr/bin/env node

/**
 * hitl-mcp-ilink-login — 微信 iLink 扫码登录
 *
 * 用法：
 *   hitl-mcp-ilink-login --token-store /path/to/store.json
 */

import { program } from 'commander';
import { createConfig, setConfig } from './config.js';
import { ilinkLogin } from './engines/ilink.js';

program
  .name('hitl-mcp-ilink-login')
  .description('微信 iLink / ClawBot 扫码登录，将 bot_token 保存到本地文件')
  .option(
    '--token-store <path>',
    'token 存储路径（默认: ./data/ilink_store.json）',
    './data/ilink_store.json'
  )
  .option(
    '--base-url <url>',
    'iLink API 基础地址（默认: https://ilinkai.weixin.qq.com）'
  )
  .parse();

const opts = program.opts();

setConfig(createConfig({
  engine: 'ilink',
  ilinkTokenStorePath: opts.tokenStore,
  ilinkBaseUrl:        opts.baseUrl,
}));

console.log('正在初始化 iLink 登录流程...');

ilinkLogin(opts.tokenStore)
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('登录失败:', err.message ?? err);
    process.exit(1);
  });
