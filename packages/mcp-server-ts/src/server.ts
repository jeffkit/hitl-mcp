/**
 * 统一 MCP Server
 *
 * 工具（按引擎）：
 *   auto        — send_and_wait_reply, send_message_only（启动时按管理台配置解析为下面之一）
 *   hil         — send_and_wait_reply, send_message_only
 *   wecom-aibot — send_and_wait_reply, send_message_only
 *   ilink       — send_and_wait_reply, send_message_only
 *
 * 初始化（扫码登录 / 填写凭证 / 激活收件人）统一在管理台完成，MCP 侧不再暴露
 * wait_for_login / list_activated_users 工具；未初始化时 send_* 返回 not_initialized
 * 并引导用户打开管理台。
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

/**
 * auto 模式：查询管理台 /admin/api/engines，按 ilink(logged_in) → wecom-aibot(connected)
 * → ilink(已注册) → wecom-aibot(已注册) → hil 的优先级选用通道。
 * 返回具体引擎类型与对应 bot_key（供 /api/send 路由）。
 */
async function resolveAutoEngine(serviceUrl: string): Promise<{ engineType: EngineType; botKey: string }> {
  const base = serviceUrl.replace(/\/$/, '');
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch(`${base}/admin/api/engines`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as { engines?: Array<Record<string, any>> };
    const engines = data.engines ?? [];
    const find = (type: string, ready: (e: Record<string, any>) => boolean) =>
      engines.find(e => e.worker_type === type && ready(e));

    const ilinkReady = find('ilink', e => e.logged_in === true);
    if (ilinkReady) return { engineType: 'ilink', botKey: String(ilinkReady.bot_key ?? '') };

    const wecomReady = find('wecom-aibot', e => e.connected === true);
    if (wecomReady) return { engineType: 'wecom-aibot', botKey: String(wecomReady.bot_key ?? '') };

    const ilinkAny = engines.find(e => e.worker_type === 'ilink');
    if (ilinkAny) return { engineType: 'ilink', botKey: String(ilinkAny.bot_key ?? '') };

    const wecomAny = engines.find(e => e.worker_type === 'wecom-aibot');
    if (wecomAny) return { engineType: 'wecom-aibot', botKey: String(wecomAny.bot_key ?? '') };

    return { engineType: 'hil', botKey: '' };
  } catch (e) {
    console.error(`[Server] auto 解析失败（管理台不可达?），回退到 hil: ${e instanceof Error ? e.message : e}`);
    return { engineType: 'hil', botKey: '' };
  }
}

function jsonText(obj: unknown): { content: Array<{ type: string; [k: string]: unknown }> } {
  return { content: [{ type: 'text', text: JSON.stringify(obj, null, 2) }] };
}

function resultToContent(result: SendResult) {
  if (result.status === 'not_initialized') {
    const text = [
      '【需要初始化】本工具调用已结束，请勿等待。',
      '',
      `请让用户在浏览器打开管理台完成初始化：${result.initUrl ?? '(未获取到链接)'}`,
      '',
      '初始化步骤（管理台「引擎管理」页）：',
      '  • iLink：扫码登录，然后给 bot 发一条消息激活收件人',
      '  • WeCom AI Bot：填写 Bot ID + Secret 启动，然后在企微给 bot 发一条消息激活收件人',
      '',
      '完成后请重试原请求。',
      '',
      JSON.stringify({ status: result.status, init_url: result.initUrl, tool_completed: true }, null, 2),
    ].join('\n');
    return { content: [{ type: 'text', text }] };
  }
  if (result.status === 'login_required') {
    // 仅返回文本：Cursor 工具面板会裁切内嵌图片，扫码链接更可靠
    const text = [
      '【需要微信扫码登录】本工具调用已结束，请勿等待。',
      '',
      '扫码链接（手机微信打开）：',
      result.qrUrl ?? '(未获取到链接)',
      '',
      'Agent 下一步：向用户展示上方链接，引导用户在管理台扫码完成登录后，重试原请求。',
      '',
      JSON.stringify({
        status: result.status,
        tool_completed: true,
        qr_url: result.qrUrl,
        next_action: result.nextAction ?? 'retry_after_console_login',
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
      ];

    case 'wecom-aibot':
      return [
        makeSendAndWaitTool('wecom-aibot', '目标 chatid（群聊或私聊）。可选；不指定时使用最近活跃收件人（需先在企微给 bot 发条消息激活）'),
        makeSendOnlyTool('wecom-aibot', '目标 chatid（群聊或私聊）。可选；不指定时使用最近活跃收件人（需先在企微给 bot 发条消息激活）'),
      ];

    default: // hil
      return [
        makeSendAndWaitTool('hil', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
        makeSendOnlyTool('hil', '目标 chatid（群聊或私聊）。不指定时使用 --chat-id 默认值'),
      ];
  }
}

function makeSendAndWaitTool(engine: EngineType, recipientDesc: string): Tool {
  const initNote = (engine === 'ilink' || engine === 'wecom-aibot')
    ? '\n若引擎未初始化（未登录/未激活收件人），本工具返回 not_initialized（含管理台链接 init_url），请引导用户打开管理台完成初始化后重试。'
    : '';
  return {
    name: 'send_and_wait_reply',
    description: `发送消息并等待用户回复（引擎: ${engine}）。
发出带 [#id] 标识的消息，等待用户回复后返回内容。支持引用回复精确匹配，也支持直接回复（FIFO）。
超时后返回 timeout 状态。${initNote}`,
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
  const description = (engine === 'ilink' || engine === 'wecom-aibot')
    ? `仅发送消息，不等待回复（引擎: ${engine}）。适用于通知场景。
若引擎未初始化，本工具返回 not_initialized（含管理台链接 init_url），请引导用户打开管理台完成初始化后重试。`
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

export async function startServer(): Promise<void> {
  const cfg = getConfig();

  // auto 模式：启动时查管理台，按 ilink→wecom-aibot→hil 优先级解析出具体引擎与 bot_key
  if (cfg.engine === 'auto') {
    const resolved = await resolveAutoEngine(cfg.serviceUrl);
    cfg.engine = resolved.engineType;
    if (resolved.botKey) cfg.botKey = resolved.botKey;
    console.error(`[Server] auto 解析 → 引擎: ${cfg.engine}, bot_key: ${cfg.botKey || '(默认)'}`);
  }

  const engine = makeEngine(cfg.engine);

  const server = new Server(
    { name: 'hitl-mcp', version: '0.3.0' },
    { capabilities: { tools: {} } }
  );

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

        if (!recipient && cfg.engine === 'hil') {
          return jsonText({ status: 'error', message: '必须指定 recipient 或通过 --chat-id 设置默认值' });
        }

        // hil / ilink / wecom-aibot 引擎：shortId/头部/「请回复」全部由 HIL Server 端 (Python) 统一处理，
        // TS 端不生成 shortId、不格式化、也不传 shortId，避免重复添加。
        if (cfg.engine === 'hil' || cfg.engine === 'ilink' || cfg.engine === 'wecom-aibot') {
          const result = await engine.sendAndWait(recipient, message, cfg.defaultTimeout, projectName);
          return resultToContent(result);
        }

        const shortId = genShortId();
        const text = formatMessage(message, shortId, projectName);
        const result = await engine.sendAndWait(recipient, text, cfg.defaultTimeout, projectName, shortId);
        return resultToContent(result);
      }

      if (name === 'send_message_only') {
        const message   = String(a.message ?? '');
        const recipient = String(a.recipient ?? cfg.defaultRecipient);
        const projectName = a.project_name ? String(a.project_name) : cfg.defaultProjectName || undefined;

        if (!recipient && cfg.engine === 'hil') {
          return jsonText({ status: 'error', message: '必须指定 recipient 或通过 --chat-id 设置默认值' });
        }

        // 同上：hil / ilink / wecom-aibot 引擎跳过 TS 端格式化，由 HIL Server 端统一处理。
        const text = (cfg.engine === 'hil' || cfg.engine === 'ilink' || cfg.engine === 'wecom-aibot')
          ? message
          : formatMessageOnly(message, projectName);
        const result = await engine.sendOnly(recipient, text, projectName);
        return resultToContent(result);
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
