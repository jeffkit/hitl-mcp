/**
 * 微信 iLink 引擎（HTTP 客户端版，走 HIL Server）
 *
 * 本引擎不持有任何长连接——iLink 长轮询由独立的 ilink-worker 常驻进程维持，
 * 并通过 HIL Server 注册为上游。本引擎只做：
 *   - 调 HIL Server 的 /api/send + /api/poll 完成发消息与等回复
 *   - 调 /api/ilink/qr + /api/ilink/login_status 完成扫码登录流程（方案 B）
 *   - 调 /api/ilink/activated_users 列出已激活用户
 *
 * 会话匹配（[#short_id] / FIFO）由 HIL Server 端统一完成，本引擎不参与。
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

export class ILinkEngine implements Engine {
  /** 登录状态变化回调（登录成功或 QR 过期时触发），由 server.ts 注入。 */
  onLoginStateChange?: () => void;

  /** 当前是否处于"等待扫码"状态（供 server 动态决定是否暴露 wait_for_login 工具） */
  isLoginPending(): boolean {
    return this._loginPending;
  }

  /** 尚未登录 */
  needsLogin(): boolean {
    return this._loginStatus !== 'success';
  }

  private _loginPending = false;
  private _loginStatus: string = 'not_started';

  async start(): Promise<void> {
    const cfg = getConfig();
    console.error(`[iLink] 通过 HIL Server: ${cfg.serviceUrl}, bot_key=${cfg.botKey || '(未设置)'}`);
    // 启动时探一次登录状态，便于 server 暴露正确的工具集
    this._refreshLoginStatus().catch(() => {});
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

    // 未登录 → 触发扫码并返回 login_required
    const loginResult = await this._ensureLoggedIn();
    if (loginResult) return loginResult;

    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: true,
        timeout: timeoutSec,
        bot_key: cfg.botKey,
        upstream: 'ilink',
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    if (!sendResult.success) {
      const err = String(sendResult.error ?? '未知错误');
      if (err.includes('login_required')) {
        const loginResult = await this._ensureLoggedIn();
        if (loginResult) return loginResult;
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

    const loginResult = await this._ensureLoggedIn();
    if (loginResult) return loginResult;

    const sendResult: Record<string, any> = await apiFetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        chat_id: recipient || undefined,
        wait_reply: false,
        bot_key: cfg.botKey,
        upstream: 'ilink',
      }),
    }).catch(e => ({ success: false, error: String(e) }));

    if (!sendResult.success) {
      const err = String(sendResult.error ?? '未知错误');
      if (err.includes('login_required')) {
        const loginResult = await this._ensureLoggedIn();
        if (loginResult) return loginResult;
      }
      return { status: 'error', message: `发送失败: ${err}` };
    }
    return { status: 'success', message: '消息发送成功' };
  }

  async waitForLogin(): Promise<SendResult> {
    if (this._loginStatus === 'success') {
      return { status: 'success', message: '已登录，可以直接重试请求。' };
    }
    if (!this._loginPending) {
      return {
        status: 'error',
        message: '没有待完成的登录流程，请重新调用 send_and_wait_reply 获取二维码。',
      };
    }

    // 轮询 HIL Server 的登录状态，直到 success / expired
    const deadline = Date.now() + 5 * 60 * 1000;
    while (Date.now() < deadline) {
      await sleep(2000);
      await this._refreshLoginStatus();
      if (this._loginStatus === 'success') {
        this.onLoginStateChange?.();
        return { status: 'success', message: '登录成功！现在可以重新调用 send_and_wait_reply。' };
      }
      if (this._loginStatus === 'expired' || this._loginStatus === 'not_started') {
        this.onLoginStateChange?.();
        return {
          status: 'timeout',
          message: '二维码已过期，微信端未在有效期内确认。请重新调用 send_and_wait_reply 获取新二维码。',
        };
      }
    }
    return { status: 'timeout', message: '等待扫码登录超时' };
  }

  async listActivatedUsers(): Promise<Array<{ fromUserId: string; hasContextToken: boolean }>> {
    const cfg = getConfig();
    try {
      const res = await apiFetch(
        `/api/ilink/activated_users?bot_key=${encodeURIComponent(cfg.botKey)}`,
      );
      const users = (res.users ?? []) as Array<Record<string, any>>;
      return users.map(u => ({
        fromUserId: String(u.from_user_id ?? u.userid ?? ''),
        hasContextToken: Boolean(u.has_context_token ?? true),
      }));
    } catch (e) {
      console.error('[iLink] 查询已激活用户失败:', e);
      return [];
    }
  }

  // ── 内部 ──────────────────────────────────────────────────

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
        console.error('[iLink] 轮询失败:', e);
      }
      await sleep(pollMs);
    }

    try { await apiFetch(`/api/session/${sessionId}/timeout`, { method: 'POST' }); } catch {}
    return { status: 'timeout', replies: [], message: `等待 ${timeoutSec} 秒后超时` };
  }

  private async _refreshLoginStatus(): Promise<void> {
    const cfg = getConfig();
    try {
      const res = await apiFetch(
        `/api/ilink/login_status?bot_key=${encodeURIComponent(cfg.botKey)}`,
      );
      this._loginStatus = res.status ?? 'not_started';
      this._loginPending = this._loginStatus === 'pending';
    } catch (e) {
      // HIL Server / worker 不可达时按未登录处理
      this._loginStatus = 'not_started';
      this._loginPending = false;
    }
  }

  private async _ensureLoggedIn(): Promise<SendResult | null> {
    await this._refreshLoginStatus();
    if (this._loginStatus === 'success') return null;

    // 触发 worker 申请二维码
    const cfg = getConfig();
    let qr: Record<string, any> = {};
    try {
      qr = await apiFetch(`/api/ilink/qr?bot_key=${encodeURIComponent(cfg.botKey)}`);
    } catch (e) {
      return { status: 'error', message: `发起登录失败: ${e}` };
    }

    if (qr.status === 'success') {
      // 极少见：刷新状态时刚好登录完成
      this._loginStatus = 'success';
      this._loginPending = false;
      return null;
    }
    if (qr.status === 'error') {
      return { status: 'error', message: `发起登录失败: ${qr.error ?? '未知错误'}` };
    }

    this._loginPending = true;
    this.onLoginStateChange?.();

    return {
      status: 'login_required',
      message: [
        '需要微信扫码登录。本工具调用已结束，请勿等待。',
        `扫码链接（手机微信打开）：${qr.qr_url ?? '(未获取到链接)'}`,
        '请向用户展示上方链接，然后立即调用 wait_for_login 等待扫码完成，成功后重试原请求。',
      ].join('\n'),
      qrUrl: qr.qr_url,
      qrCode: qr.qr_base64 ? { data: qr.qr_base64, mimeType: 'image/png' } : undefined,
      nextAction: 'call wait_for_login',
    };
  }
}
