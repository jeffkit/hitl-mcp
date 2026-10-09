/**
 * 逻辑测试脚本
 *
 * 测试 WeComClient 核心逻辑（不依赖 Cursor / 外部服务）：
 * 进程内起一个 mock HITL Server，校验 payload 构造、轮询与超时处理。
 */

import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { setConfig, createConfig } from './src/config.js';
import { WeComClient } from './src/wecom-client.js';

// ────────────────────────── mock HITL Server ──────────────────────────

interface SentPayload {
  message?: string;
  chat_id?: string;
  chat_type?: string;
  wait_reply?: boolean;
  project_name?: string;
  timeout?: number;
}

function startMockHitlServer(): Promise<{
  port: number;
  close: () => Promise<void>;
  sent: SentPayload[];
  timeoutCalls: string[];
}> {
  const sent: SentPayload[] = [];
  const timeoutCalls: string[] = [];
  const noReplySessions = new Set<string>();
  const pollCounts = new Map<string, number>();
  let sessionSeq = 0;

  const reply = (res: ServerResponse, status: number, body: unknown) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };

  const server = http.createServer((req: IncomingMessage, res: ServerResponse) => {
    const url = new URL(req.url ?? '/', 'http://mock.local');
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const rawBody = Buffer.concat(chunks).toString('utf8');

      if (req.method === 'POST' && url.pathname === '/api/send') {
        let payload: SentPayload;
        try {
          payload = JSON.parse(rawBody);
        } catch {
          return reply(res, 400, { success: false, error: 'invalid json' });
        }
        if (typeof payload.message !== 'string' || payload.message.length === 0) {
          return reply(res, 400, { success: false, error: 'message required' });
        }
        if (payload.chat_type !== 'group' && payload.chat_type !== 'single') {
          return reply(res, 400, { success: false, error: 'chat_type must be group|single' });
        }
        if (typeof payload.wait_reply !== 'boolean') {
          return reply(res, 400, { success: false, error: 'wait_reply must be boolean' });
        }
        const sessionId = `sess-${++sessionSeq}`;
        // 带 [timeout-case] 标记的会话永不返回回复，用于验证超时路径
        if (payload.message.includes('[timeout-case]')) noReplySessions.add(sessionId);
        sent.push(payload);
        return reply(res, 200, { success: true, session_id: sessionId });
      }

      const pollMatch = url.pathname.match(/^\/api\/poll\/([^/]+)$/);
      if (req.method === 'GET' && pollMatch) {
        const sessionId = decodeURIComponent(pollMatch[1]);
        const n = (pollCounts.get(sessionId) ?? 0) + 1;
        pollCounts.set(sessionId, n);
        if (noReplySessions.has(sessionId) || n < 2) {
          return reply(res, 200, { has_reply: false, replies: [] });
        }
        return reply(res, 200, {
          has_reply: true,
          replies: [{
            msg_type: 'text',
            content: 'OK',
            from_user: { name: '测试用户', alias: 'tester' },
            timestamp: new Date().toISOString(),
          }],
        });
      }

      const timeoutMatch = url.pathname.match(/^\/api\/session\/([^/]+)\/timeout$/);
      if (req.method === 'POST' && timeoutMatch) {
        timeoutCalls.push(decodeURIComponent(timeoutMatch[1]));
        return reply(res, 200, { success: true, message: 'ok' });
      }

      return reply(res, 404, { success: false, error: `no route: ${req.method} ${url.pathname}` });
    });
  });

  return new Promise(resolve => {
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      resolve({
        port,
        close: () => new Promise<void>(done => server.close(() => done())),
        sent,
        timeoutCalls,
      });
    });
  });
}

// ─────────────────────────────── 测试 ───────────────────────────────

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(`断言失败: ${msg}`);
}

async function testWeComClient() {
  console.log('🧪 测试 WeComClient...\n');

  const mock = await startMockHitlServer();
  console.log(`🛰  mock HITL Server: http://127.0.0.1:${mock.port}/api\n`);

  // 配置测试环境（指向本地 mock）
  const config = createConfig({
    serviceUrl: `http://127.0.0.1:${mock.port}/api`,
    defaultRecipient: 'chat-test-001',
    defaultProjectName: 'test-ts-mcp',
    defaultTimeout: 3600,
  });
  setConfig(config);

  const client = new WeComClient();

  try {
    // 测试 1: 发送消息（不等待回复）
    console.log('📤 测试 1: 发送消息（不等待回复）');
    const result = await client.sendMessage({
      message: '🧪 测试 TypeScript 版 MCP - send_message_only\n\n这是一条测试消息，无需回复。',
      chat_id: config.defaultRecipient,
      project_name: config.defaultProjectName,
      wait_reply: false,
    });

    assert(result.success === true, `发送应成功: ${JSON.stringify(result)}`);
    assert(typeof result.session_id === 'string' && result.session_id.length > 0, '应返回 session_id');

    const sent1 = mock.sent.at(-1);
    assert(!!sent1, 'mock 应收到一次 /api/send');
    assert(sent1!.chat_id === 'chat-test-001', 'payload.chat_id 应原样透传');
    assert(sent1!.chat_type === 'group', '默认 chat_type 应为 group');
    assert(sent1!.wait_reply === false, 'wait_reply=false 应原样透传');
    assert(sent1!.project_name === 'test-ts-mcp', 'project_name 应原样透传');
    console.log('✅ 发送成功，payload 校验通过\n');

    // 测试 2: 发送消息并等待回复
    console.log('📤 测试 2: 发送消息并等待回复');
    const result2 = await client.sendMessage({
      message: '🧪 测试 TypeScript 版 MCP - send_and_wait_reply\n\n请回复 "OK" 来完成测试（30秒超时）',
      chat_id: config.defaultRecipient,
      project_name: config.defaultProjectName,
      timeout: 30,  // 30 秒超时
      wait_reply: true,
    });

    assert(result2.success === true, `发送应成功: ${JSON.stringify(result2)}`);
    const sent2 = mock.sent.at(-1);
    assert(sent2!.wait_reply === true, 'wait_reply=true 应原样透传');
    assert(sent2!.timeout === 30, 'timeout 应原样透传');
    console.log('✅ 发送成功，已创建会话');
    console.log(`   Session ID: ${result2.session_id}\n`);

    const sessionId = result2.session_id!;

    // 轮询等待回复
    console.log('⏳ 等待用户回复（30秒超时）...');
    const startTime = Date.now();
    const timeout = 30000;
    const pollInterval = 200;

    let replyReceived = false;
    while (Date.now() - startTime < timeout) {
      const pollResult = await client.pollReplies(sessionId);

      if (pollResult.has_reply) {
        console.log('✅ 收到用户回复！');
        console.log(`   回复数量: ${pollResult.replies.length}`);
        pollResult.replies.forEach((reply, index) => {
          console.log(`   回复 ${index + 1}:`);
          console.log(`     类型: ${reply.msg_type}`);
          console.log(`     内容: ${reply.content}`);
          console.log(`     用户: ${reply.from_user.name} (@${reply.from_user.alias})`);
        });
        assert(pollResult.replies[0].msg_type === 'text', '回复类型应为 text');
        assert(pollResult.replies[0].content === 'OK', '回复内容应为 OK');
        replyReceived = true;
        break;
      }

      if (pollResult.status === 'not_found') {
        throw new Error('会话不存在或已过期');
      }

      // 显示进度
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      process.stdout.write(`\r   已等待 ${elapsed} 秒...`);

      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }
    assert(replyReceived, '30 秒内未收到回复');
    console.log('\n');

    // 测试 3: 超时处理
    console.log('📤 测试 3: 会话超时标记');
    const result3 = await client.sendMessage({
      message: '🧪 测试 TypeScript 版 MCP - timeout [timeout-case]',
      chat_id: config.defaultRecipient,
      project_name: config.defaultProjectName,
      wait_reply: false,
    });
    assert(result3.success === true && !!result3.session_id, `发送应成功: ${JSON.stringify(result3)}`);

    const poll3 = await client.pollReplies(result3.session_id!);
    assert(poll3.has_reply === false, '无回复会话轮询应保持 has_reply=false');

    console.log('⏰ 无回复，标记会话超时');
    const timeoutResp = await client.markTimeout(result3.session_id!);
    assert(timeoutResp.success === true, `标记超时应成功: ${JSON.stringify(timeoutResp)}`);
    assert(mock.timeoutCalls.includes(result3.session_id!), 'mock 应收到 timeout 请求');
    console.log('✅ 会话已标记为超时\n');
  } finally {
    await mock.close();
  }

  console.log('🎉 所有测试完成！\n');
  console.log('总结:');
  console.log('  ✅ 配置管理正常');
  console.log('  ✅ payload 构造正常（chat_id / chat_type / wait_reply / project_name / timeout）');
  console.log('  ✅ 发送消息（不等待）正常');
  console.log('  ✅ 发送消息（等待回复）+ 轮询机制正常');
  console.log('  ✅ 超时处理正常');
}

// 运行测试
testWeComClient().catch(error => {
  console.error('测试失败:', error);
  process.exit(1);
});
