/**
 * 统一 MCP Server
 *
 * 工具（按引擎）：
 *   hil         — send_and_wait_reply, send_message_only
 *   wecom-aibot — send_and_wait_reply, send_message_only
 *   ilink       — send_and_wait_reply, send_message_only, wait_for_login, list_activated_users
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from '@modelcontextprotocol/sdk/types.js';
import { getConfig, type EngineType } from './config.js';
import { HilEngine } from './engines/hil.js';
import { WecomAibotEngine } from './engines/wecom-aibot.js';
import { ILinkEngine } from './engines/ilink.js';
import type { Engine, SendResult } from './engines/base.js';

function genShortId(): string {
  return Math.random().toString(16).slice(2, 8);
}

function formatMessage(text: string, shortId: string, projectName?: string): string {
  const headerParts = [`[#${shortId}]`];
  if (projectName) headerParts.push(`[${projectName}]`);
  return `${headerParts.join(' ')}\n${text}\n\n> 请引用回复此消息`;
}

function formatMessageOnly(text: string, projectName?: string): string {
  if (projectName) return `[${projectName}]\n${text}`;
  return text;
}

function makeEngine(engineType: EngineType): Engine {
  switch (engineType) {
    case 'wecom-aibot': return new WecomAibotEngine();
    case 'ilink':       return new ILinkEngine();
    default:            return new HilEngine();
  }
}

function jsonText(obj: unknown): { content: Array<{ type: string; [k: string]: unknown }> } {
  return { content: [{ type: 'text', text: JSON.stringify(obj, null, 2) }] };
}

function resultToContent(result: SendResult) {
  if (result.status === 'login_required') {
    // 仅返回文本：Cursor 工具面板会裁切内嵌图片，扫码链接更可靠
    const text = [
      '【需要微信扫码登录】本工具调用已结束，请勿等待。',
      '',
      '扫码链接（手机微信打开）：',
      result.qrUrl ?? '(未获取到链接)',
      '',
      'Agent 下一步：向用户展示上方链接，然后立即调用 wait_for_login 等待扫码，成功后重试原请求。',
      '',
      JSON.stringify({
        status: result.status,
        tool_completed: true,
        qr_url: result.qrUrl,
        next_action: result.nextAction ?? 'wait_for_login',
      }, null, 2),
    ].join('\n');
    return { content: [{ type: 'text', text }] };
  }
  return jsonText(result);
}

// ── 工具定义（静态部分，引擎启动后不变） ──────────────────────────────────────

function buildTools(cfg: ReturnType<typeof getConfig>): Tool[] {
  switch (cfg.engine) {
    case 'ilink':
      return [
        makeSendAndWaitTool('ilink', '目标微信用户 ID。通常留空——有且仅有一个激活用户时自动选择'),
        makeSendOnlyTool('ilink', '目标微信用户 ID。通常留空——有且仅有一个激活用户时自动选择'),
        WAIT_FOR_LOGIN_TOOL,
        LIST_ACTIVATED_USERS_TOOL,
      ];

    case 'wecom-aibot':
      return [
        makeSendAndWaitTool('wecom-aibot', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
        makeSendOnlyTool('wecom-aibot', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
      ];

    default: // hil
      return [
        makeSendAndWaitTool('hil', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
        makeSendOnlyTool('hil', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
      ];
  }
}

function makeSendAndWaitTool(engine: EngineType, recipientDesc: string): Tool {
  const ilinkNote = engine === 'ilink'
    ? '\n若未登录，本工具会立即返回 login_required（含 qr_url），随后 Agent 应调用 wait_for_login 等待扫码，成功后重试。'
    : '';
  return {
    name: 'send_and_wait_reply',
    description: `发送消息并等待用户回复（引擎: ${engine}）。
发出带 [#id] 标识的消息，等待用户回复后返回内容。支持引用回复精确匹配，也支持直接回复（FIFO）。
超时后返回 timeout 状态。${ilinkNote}`,
    inputSchema: {
      type: 'object',
      properties: {
        message:      { type: 'string', description: '要发送给用户的消息内容' },
        recipient:    { type: 'string', description: recipientDesc },
        project_name: { type: 'string', description: '项目名称，显示在消息头中' },
      },
      required: ['message'],
    },
  };
}

function makeSendOnlyTool(engine: EngineType, recipientDesc: string): Tool {
  const description = engine === 'ilink'
    ? `仅发送消息，不等待回复（引擎: ilink）。
若未登录，本工具会立即返回 login_required（含扫码链接 qr_url 和二维码图片），工具调用随即结束。
收到 login_required 后，Agent 必须：1) 向用户展示扫码链接；2) 立即调用 wait_for_login 等待扫码；3) 登录成功后重试本工具。`
    : `仅发送消息，不等待回复（引擎: ${engine}）。适用于通知场景。`;
  return {
    name: 'send_message_only',
    description,
    inputSchema: {
      type: 'object',
      properties: {
        message:      { type: 'string', description: '要发送给用户的消息内容' },
        recipient:    { type: 'string', description: recipientDesc },
        project_name: { type: 'string', description: '项目名称' },
      },
      required: ['message'],
    },
  };
}

const WAIT_FOR_LOGIN_TOOL: Tool = {
  name: 'wait_for_login',
  description: `等待用户完成微信扫码登录（阻塞，最长约 5 分钟）。
在 send_message_only / send_and_wait_reply 返回 login_required 后，Agent 必须立即调用本工具。
本工具会阻塞直到用户扫码确认或二维码过期；登录成功后返回 success，Agent 应重试原先的发送请求。`,
  inputSchema: { type: 'object', properties: {} },
};

const LIST_ACTIVATED_USERS_TOOL: Tool = {
  name: 'list_activated_users',
  description: '列出已向 ClawBot 发送过消息（已激活）的微信用户',
  inputSchema: { type: 'object', properties: {} },
};

export async function startServer(): Promise<void> {
  const cfg = getConfig();
  const engine = makeEngine(cfg.engine);

  const server = new Server(
    { name: 'hitl-mcp', version: '0.3.0' },
    // listChanged: true 声明此服务端支持动态工具列表变更通知
    { capabilities: { tools: { listChanged: true } } }
  );

  // ── iLink 引擎：注入登录状态变化回调 ──────────────────────────────────────
  if (engine instanceof ILinkEngine) {
    engine.onLoginStateChange = () => {
      // 通知 MCP 客户端重新拉取工具列表
      server.notification({ method: 'notifications/tools/list_changed' });
    };
  }

  await engine.start();

  // ── 动态工具列表 ──────────────────────────────────────────────────────────
  // 每次客户端 list_tools 时重新计算，以反映最新的登录状态

  server.setRequestHandler(ListToolsRequestSchema, () => ({
    tools: buildTools(cfg),
  }));

  // ── 工具调用处理器 ────────────────────────────────────────────────────────

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    const a = (args ?? {}) as Record<string, unknown>;

    try {
      if (name === 'send_and_wait_reply') {
        const message   = String(a.message ?? '');
        const recipient = String(a.recipient ?? cfg.defaultRecipient);
        const projectName = a.project_name ? String(a.project_name) : cfg.defaultProjectName || undefined;

        if (!recipient && cfg.engine !== 'ilink') {
          return jsonText({ status: 'error', message: '必须指定 recipient 或通过 --chat-id 设置默认值' });
        }

        // hil 引擎：HIL Server 端 (Python) 会自己调用 format_message_with_header 加头部和「请回复」，
        // TS 端不能再加一次，否则企微群机器人会出现双层短 ID/项目名 和双层「请回复」提示。
        const text = cfg.engine === 'hil'
          ? message
          : formatMessage(message, genShortId(), projectName);
        const result = await engine.sendAndWait(recipient, text, cfg.defaultTimeout, projectName);
        return resultToContent(result);
      }

      if (name === 'send_message_only') {
        const message   = String(a.message ?? '');
        const recipient = String(a.recipient ?? cfg.defaultRecipient);
        const projectName = a.project_name ? String(a.project_name) : cfg.defaultProjectName || undefined;

        if (!recipient && cfg.engine !== 'ilink') {
          return jsonText({ status: 'error', message: '必须指定 recipient 或通过 --chat-id 设置默认值' });
        }

        // 同上：hil 引擎跳过 TS 端格式化，由 HIL Server 端统一处理。
        const text = cfg.engine === 'hil'
          ? message
          : formatMessageOnly(message, projectName);
        const result = await engine.sendOnly(recipient, text, projectName);
        return resultToContent(result);
      }

      if (name === 'wait_for_login' && cfg.engine === 'ilink') {
        const result = await (engine as ILinkEngine).waitForLogin();
        return resultToContent(result);
      }

      if (name === 'list_activated_users' && cfg.engine === 'ilink') {
        return jsonText({ status: 'success', users: (engine as ILinkEngine).listActivatedUsers() });
      }

      throw new Error(`未知工具: ${name}`);

    } catch (e) {
      console.error('[Server] 工具执行错误:', e);
      return jsonText({ status: 'error', message: e instanceof Error ? e.message : String(e) });
    }
  });

  // ── 连接传输层 ────────────────────────────────────────────────────────────

  const transport = new StdioServerTransport();
  await server.connect(transport);

  console.error('[Server] hitl-mcp 已启动');
  console.error(`[Server]   引擎: ${cfg.engine}`);
  console.error(`[Server]   默认收件人: ${cfg.defaultRecipient || '(未设置)'}`);
  console.error(`[Server]   默认项目名: ${cfg.defaultProjectName || '(未设置)'}`);
  console.error(`[Server]   超时: ${cfg.defaultTimeout}s`);
}
