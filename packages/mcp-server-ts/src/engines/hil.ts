/**
 * HITL Server 引擎（原有行为）
 *
 * 通过 HTTP 调用 HITL Server，轮询等待回复。
 * 适用于腾讯内部飞鸽传书场景（需要 HITL Server 在线）。
 */

import { getConfig } from '../config.js';
import type { Engine, SendResult } from './base.js';

function sleep(ms: number) {
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

export class HilEngine implements Engine {
  async start(): Promise<void> {
    const cfg = getConfig();
    console.error(`[HIL] 使用 HITL Server: ${cfg.serviceUrl}`);
  }

  async stop(): Promise<void> {}

  async sendAndWait(
    recipient: string,
    text: string,
    timeoutSec: number,
    projectName?: string,
    _shortId?: string,
  ): Promise<SendResult> {
    const cfg = getConfig();

    const sendResult: Record<string, any> = await apiFetch('/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient,
        wait_reply: true,
        timeout: timeoutSec,
        project_name: projectName,
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    if (!sendResult.success) {
      return { status: 'error', message: `发送失败: ${sendResult.error ?? '未知错误'}` };
    }

    const sessionId: string = sendResult.session_id;
    if (!sessionId) {
      return { status: 'error', message: '发送成功但未获取到 session_id' };
    }

    const deadline = Date.now() + timeoutSec * 1000;
    const pollMs = cfg.pollInterval * 1000;

    while (Date.now() < deadline) {
      try {
        const poll = await apiFetch(`/poll/${sessionId}`);
        if (poll.has_reply) {
          return {
            status: 'success',
            replies: (poll.replies ?? []).map((r: any) => ({
              text: r.content ?? r.text ?? '',
            })),
            message: `收到 ${poll.replies?.length ?? 0} 条回复`,
          };
        }
        if (poll.status === 'not_found') {
          return { status: 'error', message: '会话不存在或已过期' };
        }
      } catch (e) {
        console.error('[HIL] 轮询失败:', e);
      }
      await sleep(pollMs);
    }

    // 超时，通知服务端清理
    try {
      await apiFetch(`/session/${sessionId}/timeout`, { method: 'POST' });
    } catch {}

    return { status: 'timeout', replies: [], message: `等待 ${timeoutSec} 秒后超时` };
  }

  async sendOnly(
    recipient: string,
    text: string,
    projectName?: string,
  ): Promise<SendResult> {
    const result = await apiFetch('/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient,
        wait_reply: false,
        project_name: projectName,
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    return result.success
      ? { status: 'success', message: '消息发送成功' }
      : { status: 'error', message: `发送失败: ${result.error}` };
  }
}
