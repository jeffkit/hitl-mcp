/**
 * Telegram Bot 引擎（HTTP 客户端版，走 HITL Server）
 *
 * 长轮询 / 消息发送均由 Python 侧 hitl_server/engines/telegram.py 维持。
 * 本文件只负责：
 *   - start()   → 可选：若 CLI 携带 --tg-token，则在 HITL Server 自动注册引擎
 *   - sendAndWait / sendOnly → 调 /api/send + /api/poll
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
  const cfg = getConfig();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (cfg.apiKey) headers['Authorization'] = `Bearer ${cfg.apiKey}`;
  const res = await fetch(`${baseUrl()}${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
  return res.json() as Promise<Record<string, any>>;
}

function notInitialized(reason: string): SendResult {
  return {
    status: 'not_initialized',
    initUrl: baseUrl() + '/console',
    message: `${reason}。请打开管理台完成 Telegram 引擎初始化（填写 Bot Token），然后重试。`,
  };
}

export class TelegramEngine implements Engine {
  async start(): Promise<void> {
    const cfg = getConfig();
    const botKey = cfg.botKey || 'telegram-1';
    const tgToken = (cfg as any).tgToken as string | undefined;
    if (!tgToken) {
      console.error(`[Telegram] 未带 --tg-token，跳过自动注册（假定已在管理台配置 bot_key=${botKey}）`);
      return;
    }
    console.error(`[Telegram] 注册到 HITL Server: ${cfg.serviceUrl}, bot_key=${botKey}`);
    try {
      const r = await apiFetch('/api/engines/telegram/start', {
        method: 'POST',
        body: JSON.stringify({ bot_token: tgToken, bot_key: botKey }),
      });
      console.error(`[Telegram] 引擎就绪: ${r.success}`);
    } catch (e) {
      console.error(`[Telegram] 注册失败（HITL Server 是否已启动？）: ${e}`);
    }
  }

  async stop(): Promise<void> {}

  async sendAndWait(
    recipient: string,
    text: string,
    timeoutSec: number,
    projectName?: string,
  ): Promise<SendResult> {
    const cfg = getConfig();
    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: true,
        timeout: timeoutSec,
        bot_key: cfg.botKey || 'telegram-1',
        upstream: 'telegram',
        project_name: projectName,
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
    if (!sessionId) return { status: 'error', message: '发送成功但未获取到 session_id' };
    return this._pollReply(sessionId, timeoutSec);
  }

  async sendOnly(
    recipient: string,
    text: string,
    projectName?: string,
  ): Promise<SendResult> {
    const cfg = getConfig();
    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: false,
        bot_key: cfg.botKey || 'telegram-1',
        upstream: 'telegram',
        project_name: projectName,
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
        if (poll.status === 'not_found') return { status: 'error', message: '会话不存在或已过期' };
      } catch (e) {
        console.error('[Telegram] 轮询失败:', e);
      }
      await sleep(pollMs);
    }

    try { await apiFetch(`/api/session/${sessionId}/timeout`, { method: 'POST' }); } catch {}
    return { status: 'timeout', replies: [], message: `等待 ${timeoutSec} 秒后超时` };
  }
}
