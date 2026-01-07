#!/usr/bin/env node

/**
 * Human-in-the-Loop MCP Server Entry Point
 * 
 * 运行方式:
 *   node dist/index.js --service-url http://hitl.woa.com/api --chat-id xxx --project-name xxx
 *   或通过 npx:
 *   npx @hitl/mcp-server --service-url http://hitl.woa.com/api --chat-id xxx
 */

import { program } from 'commander';
import { createConfig, setConfig } from './config.js';
import { startServer } from './server.js';

// 解析命令行参数
program
  .name('hitl-mcp')
  .description('WeCom HIL MCP Server - 让 AI 能够发送消息到企业微信并等待用户回复')
  .version('0.2.1')
  .option('--service-url <url>', 'HIL Server 的访问地址（如 http://hitl.woa.com/api）')
  .option('--chat-id <id>', '默认发送消息的 Chat ID（群聊或私聊）')
  .option('--project-name <name>', '默认项目名称，用于标识消息来源')
  .option('--timeout <seconds>', '默认等待回复超时时间（秒），默认 1200 秒（20 分钟）', parseInt)
  .parse();

const options = program.opts();

// 创建配置（命令行参数覆盖环境变量）
const config = createConfig({
  serviceUrl: options.serviceUrl,
  defaultChatId: options.chatId,
  defaultProjectName: options.projectName,
  defaultTimeout: options.timeout,
});

// 设置全局配置
setConfig(config);

// 启动服务器
startServer().catch((error) => {
  console.error('[Main] Failed to start server:', error);
  process.exit(1);
});
