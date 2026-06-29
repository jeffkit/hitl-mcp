/**
 * 企业微信 AI Bot 引擎（HTTP 客户端版，走 HITL Server）
 *
 * 本引擎不持有 WebSocket——企微 AI Bot 的 WS 长连接由 HITL Server 的内置引擎
 * （hitl_server/engines/wecom_aibot.py）维持。本引擎只做：
 *   - 调 HITL Server 的 /api/send + /api/poll 完成发消息与等回复
 *
 * 会话匹配（[#short_id] / FIFO）由 HITL Server 端统一完成，本引擎不参与。
 * 消息头 [#short_id] 也由 HITL Server 端统一拼接，TS 端不格式化。
 */
import { getConfig } from '../config.js';
import type { Engine, SendResult } from './base.js';

function sleep(ms: number): Promise<void> {
  return new Promise<void>(r => setTimeout(r, ms));
}

function baseUrl(): string {
  return getConfig().serviceUrl.replace(/\/$/, '');
}

async function apiFetch(path: string, init?: RequestInit): Promise<Record<string, any>> {
  const res = await fetch(`${baseUrl()}${path}`, {
    ...init,
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
  return res.json() as Promise<Record<string, any>>;
}

function notInitialized(reason: string): SendResult {
  return {
    status: 'not_initialized',
    initUrl: baseUrl() + '/console',
    message: `${reason}。请打开管理台完成初始化（填写凭证 + 在企微给 bot 发条消息激活收件人），然后重试。`,
  };
}

export class WecomAibotEngine implements Engine {
  async start(): Promise<void> {
    const cfg = getConfig();
    const botKey = cfg.botKey || 'wecom-aibot-1';
    // 凭证可选：若提供则在此自动注册到 HITL Server（兜底）；未提供时假定已通过管理台配置。
    if (!cfg.wecomBotId || !cfg.wecomBotSecret) {
      console.error(`[WecomAibot] 未带 --bot-id/--bot-secret，跳过自动注册（假定已在管理台配置 bot_key=${botKey}）`);
      return;
    }
    console.error(`[WecomAibot] 注册到 HITL Server: ${cfg.serviceUrl}, bot_key=${botKey}`);
    try {
      const r = await apiFetch('/api/engines/wecom-aibot/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bot_id: cfg.wecomBotId,
          bot_secret: cfg.wecomBotSecret,
          bot_key: botKey,
        }),
      });
      console.error(`[WecomAibot] 引擎就绪: ${r.status ?? r.success}`);
    } catch (e) {
      console.error(`[WecomAibot] 注册失败（HITL Server 是否已启动？）: ${e}`);
    }
  }

  async stop(): Promise<void> {}

  async sendAndWait(
    recipient: string,
    text: string,
    timeoutSec: number,
    _projectName?: string,
    _shortId?: string,
  ): Promise<SendResult> {
    const cfg = getConfig();

    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: true,
        timeout: timeoutSec,
        bot_key: cfg.botKey,
        upstream: 'wecom-aibot',
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    if (!sendResult.success) {
      const err = String(sendResult.error ?? '未知错误');
      if (err.includes('engine_not_started') || err.includes('尚无已知收件人')) {
        return notInitialized(err);
      }
      return { status: 'error', message: `发送失败: ${err}` };
    }

    const sessionId: string = sendResult.session_id;
    if (!sessionId) {
      return { status: 'error', message: '发送成功但未获取到 session_id' };
    }

    return this._pollReply(sessionId, timeoutSec);
  }

  async sendOnly(
    recipient: string,
    text: string,
    _projectName?: string,
  ): Promise<SendResult> {
    const cfg = getConfig();

    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: false,
        bot_key: cfg.botKey,
        upstream: 'wecom-aibot',
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    if (!sendResult.success) {
      const err = String(sendResult.error ?? '未知错误');
      if (err.includes('engine_not_started') || err.includes('尚无已知收件人')) {
        return notInitialized(err);
      }
      return { status: 'error', message: `发送失败: ${err}` };
    }
    return { status: 'success', message: '消息发送成功' };
  }

  private async _pollReply(sessionId: string, timeoutSec: number): Promise<SendResult> {
    const cfg = getConfig();
    const deadline = Date.now() + timeoutSec * 1000;
    const pollMs = cfg.pollInterval * 1000;

    while (Date.now() < deadline) {
      try {
        const poll = await apiFetch(`/api/poll/${sessionId}`);
        if (poll.has_reply) {
          return {
            status: 'success',
            replies: (poll.replies ?? []).map((r: any) => ({ text: r.content ?? r.text ?? '' })),
            message: `收到 ${poll.replies?.length ?? 0} 条回复`,
          };
        }
        if (poll.status === 'not_found') {
          return { status: 'error', message: '会话不存在或已过期' };
        }
      } catch (e) {
        console.error('[WecomAibot] 轮询失败:', e);
      }
      await sleep(pollMs);
    }

    try { await apiFetch(`/api/session/${sessionId}/timeout`, { method: 'POST' }); } catch {}
    return { status: 'timeout', replies: [], message: `等待 ${timeoutSec} 秒后超时` };
  }
}
