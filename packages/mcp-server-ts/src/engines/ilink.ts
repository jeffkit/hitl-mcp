/**
 * 微信 iLink 引擎（ClawBot）
 *
 * 通过 HTTP 长轮询直接对接微信 iLink 服务端。
 * 无需 HIL Server，无需公网 IP，无需回调 URL。
 *
 * 登录：首次调用时自动发起扫码流程，以二维码图片形式返回给 Agent 显示，
 *       用户扫码后重试即可，无需单独运行登录命令。
 *
 * "ghost fields"（未文档化但 sendmessage 必须携带）：
 *   client_id, message_type, message_state, base_info.channel_version
 */

import QRCode from 'qrcode';
import { getConfig } from '../config.js';
import { sessionManager, TimeoutError } from '../session.js';
import { TokenStore } from '../token-store.js';
import type { Engine, SendResult } from './base.js';

const UA = 'Mozilla/5.0 (compatible; iLink-Bot/1.0)';

interface MessageItem {
  type?: number;
  text_item?: { text?: string };
  voice_item?: { text?: string };
}

interface WeixinMessage {
  from_user_id?: string;
  to_user_id?: string;
  context_token?: string;
  message_type?: number;
  message_state?: number;
  client_id?: string;
  item_list?: MessageItem[];
}

function _genShortId(): string {
  return Math.random().toString(16).slice(2, 8);
}

function _randomUin(): string {
  const uint32 = Math.floor(Math.random() * 0xFFFFFFFF);
  return Buffer.from(String(uint32)).toString('base64');
}

function ilinkHeaders(botToken: string): Record<string, string> {
  return {
    AuthorizationType: 'ilink_bot_token',
    Authorization: `Bearer ${botToken}`,
    'Content-Type': 'application/json',
    'User-Agent': UA,
    'X-WECHAT-UIN': _randomUin(),
  };
}

function _extractText(msg: WeixinMessage): string {
  for (const item of msg.item_list ?? []) {
    const text = item.text_item?.text ?? item.voice_item?.text;
    if (text) return text;
  }
  return '';
}

function _buildTextReply(contextToken: string, text: string, toUserId: string): WeixinMessage {
  return {
    context_token: contextToken,
    to_user_id: toUserId,
    from_user_id: '',
    message_type: 2,
    message_state: 2,
    client_id: `mcp-${Date.now()}`,
    item_list: [{ type: 1, text_item: { text } }],
  };
}

// QR 过期由 API status="expired"/status=3 信号驱动，不依赖本地时间
type LoginOutcome = 'success' | 'expired';

interface PendingQR {
  qrBase64: string;
  qrUrl: string;
  qrcodeKey: string;
  /** 背景轮询完成时 resolve，供 waitForLogin 直接 await */
  settle: (outcome: LoginOutcome) => void;
  promise: Promise<LoginOutcome>;
}

export class ILinkEngine implements Engine {
  private store!: TokenStore;
  private polling = false;
  private stopped = false;

  /** QR 二维码等待扫码中的状态，为 null 表示无待扫码流程 */
  private pendingQR: PendingQR | null = null;

  /**
   * 登录状态变化回调（登录成功或 QR 过期时触发）。
   * 由 server.ts 注入，用于发送 MCP 工具列表变更通知。
   */
  onLoginStateChange?: () => void;

  /** 当前是否处于"等待扫码"状态（供 server 动态决定是否暴露 wait_for_login 工具） */
  isLoginPending(): boolean {
    return !this.store?.getBotToken() && this.pendingQR !== null;
  }

  /** 尚未登录（无论是否已申请二维码） */
  needsLogin(): boolean {
    return !this.store?.getBotToken();
  }

  async start(): Promise<void> {
    const cfg = getConfig();
    this.store = new TokenStore(cfg.ilinkTokenStorePath);

    if (!this.store.getBotToken()) {
      console.error('[iLink] 未找到 bot_token，首次调用工具时将自动发起扫码登录。');
    }

    this.polling = true;
    this._pollLoop().catch(e => console.error('[iLink] 轮询循环异常:', e));
    console.error('[iLink] 长轮询已启动');
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.polling = false;
  }

  private async _pollLoop(): Promise<void> {
    let retryDelay = 3000;
    const cfg = getConfig();

    while (this.polling && !this.stopped) {
      const botToken = this.store.getBotToken();
      if (!botToken) {
        await _sleep(5000);
        continue;
      }

      try {
        const buf = this.store.getUpdatesBuf();
        const res = await fetch(`${cfg.ilinkBaseUrl}/ilink/bot/getupdates`, {
          method: 'POST',
          headers: ilinkHeaders(botToken),
          body: JSON.stringify({
            get_updates_buf: buf,
            timeout: cfg.ilinkPollTimeout,
            base_info: { channel_version: '0.3.0', bot_agent: 'hitl-mcp/0.3.0' },
          }),
          signal: AbortSignal.timeout((cfg.ilinkPollTimeout + 10) * 1000),
        });

        if (res.status === 401) {
          console.error('[iLink] bot_token 已失效，请重新扫码登录');
          await _sleep(30_000);
          continue;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json() as Record<string, any>;
        if (data['get_updates_buf']) {
          this.store.setUpdatesBuf(data['get_updates_buf'] as string);
        }

        for (const msg of ((data['msgs'] ?? []) as WeixinMessage[])) {
          await this._processUpdate(msg);
        }
        retryDelay = 3000;

      } catch (e) {
        console.error(`[iLink] 轮询异常: ${e}，${retryDelay / 1000}s 后重试`);
        await _sleep(retryDelay);
        retryDelay = Math.min(retryDelay * 2, 60_000);
      }
    }
  }

  private async _processUpdate(msg: WeixinMessage): Promise<void> {
    const fromUserId = msg.from_user_id ?? '';
    const contextToken = msg.context_token ?? '';
    const text = _extractText(msg);

    if (contextToken && fromUserId) {
      this.store.setContextToken(fromUserId, contextToken);
    }

    if (fromUserId && text) {
      const matched = sessionManager.dispatch(fromUserId, text);
      if (!matched) {
        console.error(`[iLink] 无匹配会话，忽略: user=${fromUserId}, text=${text.substring(0, 40)}`);
      }
    }
  }

  async sendAndWait(recipient: string, text: string, timeoutSec: number, _projectName?: string): Promise<SendResult> {
    const loginResult = await this._ensureLoggedIn();
    if (loginResult) return loginResult;

    const resolved = this._resolveRecipient(recipient);
    if (resolved.error) return resolved.error;
    recipient = resolved.userId!;

    const check = this._checkActivated(recipient);
    if (check) return check;

    const shortId = _genShortId();
    const promise = sessionManager.create(shortId, recipient, timeoutSec * 1000);

    const sendErr = await this._sendMessage(recipient, text);
    if (sendErr) {
      sessionManager.cancel(shortId);
      return { status: 'error', message: sendErr };
    }

    try {
      const reply = await promise;
      return {
        status: 'success',
        replies: [{ text: reply.text }],
        message: '收到用户回复',
      };
    } catch (e) {
      if (e instanceof TimeoutError) {
        return { status: 'timeout', replies: [], message: e.message };
      }
      throw e;
    }
  }

  async sendOnly(recipient: string, text: string, _projectName?: string): Promise<SendResult> {
    const loginResult = await this._ensureLoggedIn();
    if (loginResult) return loginResult;

    const resolved = this._resolveRecipient(recipient);
    if (resolved.error) return resolved.error;
    recipient = resolved.userId!;

    const check = this._checkActivated(recipient);
    if (check) return check;

    const err = await this._sendMessage(recipient, text);
    return err
      ? { status: 'error', message: err }
      : { status: 'success', message: '消息发送成功' };
  }

  listActivatedUsers(): Array<{ fromUserId: string; hasContextToken: boolean }> {
    return this.store.listKnownUsers();
  }

  /**
   * 阻塞等待用户完成扫码登录（供 wait_for_login 工具调用）。
   * 直接 await 背景轮询的 Promise，收到结果立即返回。
   */
  async waitForLogin(): Promise<SendResult> {
    if (this.store.getBotToken()) {
      return { status: 'success', message: '已登录，可以直接重试请求。' };
    }

    if (!this.pendingQR) {
      return {
        status: 'error',
        message: '没有待完成的登录流程，请重新调用 send_and_wait_reply 获取二维码。',
      };
    }

    const outcome = await this.pendingQR.promise;

    if (outcome === 'success') {
      return { status: 'success', message: '登录成功！现在可以重新调用 send_and_wait_reply。' };
    }

    return {
      status: 'timeout',
      message: '二维码已过期，微信端未在有效期内确认。请重新调用 send_and_wait_reply 获取新二维码。',
    };
  }

  /** 解析收件人：优先用传入值，否则取 store 里第一个激活用户 */
  private _resolveRecipient(recipient: string): { userId: string | null; error?: SendResult } {
    const userId = recipient || this.store.resolveRecipient();
    if (userId) return { userId };
    return {
      userId: null,
      error: {
        status: 'error',
        message: '尚无已激活用户。请先向 ClawBot 发送一条消息完成激活。',
      },
    };
  }

  private _loginRequiredResult(qrUrl: string, qrBase64: string): SendResult {
    return {
      status: 'login_required',
      message: [
        '需要微信扫码登录。本工具调用已结束，请勿等待。',
        `扫码链接（手机微信打开）：${qrUrl}`,
        '请向用户展示上方链接或二维码，然后立即调用 wait_for_login 等待扫码完成，成功后重试原请求。',
      ].join('\n'),
      qrUrl,
      qrCode: { data: qrBase64, mimeType: 'image/png' },
      nextAction: 'call wait_for_login',
    };
  }

  /**
   * 检查登录状态。未登录时：
   * - 若已有进行中的 pendingQR，直接复用同一张二维码
   * - 否则申请新 QR，创建 deferred Promise，启动背景轮询
   */
  private async _ensureLoggedIn(): Promise<SendResult | null> {
    if (this.store.getBotToken()) return null;

    // 复用已申请、尚未完成的 QR
    if (this.pendingQR) {
      return this._loginRequiredResult(this.pendingQR.qrUrl, this.pendingQR.qrBase64);
    }

    const cfg = getConfig();
    const base = cfg.ilinkBaseUrl;

    try {
      const qrRes = await fetch(`${base}/ilink/bot/get_bot_qrcode?bot_type=3`, {
        method: 'GET',
        headers: { 'User-Agent': UA },
        signal: AbortSignal.timeout(15_000),
      });
      if (!qrRes.ok) throw new Error(`get_bot_qrcode HTTP ${qrRes.status}`);
      const qrData = await qrRes.json() as Record<string, any>;
      if (qrData['ret'] !== 0) {
        throw new Error(qrData['errmsg'] ?? `get_bot_qrcode ret=${qrData['ret']}`);
      }

      const qrcodeKey: string = qrData['qrcode'] ?? '';
      const qrUrl: string = qrData['qrcode_img_content'] ?? '';
      if (!qrcodeKey || !qrUrl) throw new Error('无法获取二维码');

      const pngBuffer = await QRCode.toBuffer(qrUrl, {
        width: 200,
        margin: 2,
        errorCorrectionLevel: 'M',
      });
      const qrBase64 = pngBuffer.toString('base64');

      // 创建 deferred Promise，让 waitForLogin 可以直接 await
      let settle!: (outcome: LoginOutcome) => void;
      const promise = new Promise<LoginOutcome>(res => { settle = res; });

      this.pendingQR = { qrBase64, qrUrl, qrcodeKey, settle, promise };

      // 通知 server：wait_for_login 工具现在可用
      this.onLoginStateChange?.();

      // 背景轮询：通过 settle 通知 waitForLogin
      this._pollLoginInBackground(qrcodeKey, base);

      return this._loginRequiredResult(qrUrl, qrBase64);
    } catch (e) {
      return { status: 'error', message: `发起登录失败: ${e}` };
    }
  }

  /**
   * 背景轮询 get_qrcode_status，直到 confirmed 或 expired。
   */
  private _pollLoginInBackground(qrcodeKey: string, base: string): void {
    const poll = async () => {
      while (true) {
        await _sleep(2000);

        if (!this.pendingQR) return;

        try {
          const res = await fetch(
            `${base}/ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcodeKey)}`,
            { method: 'GET', headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(35_000) },
          );
          if (!res.ok) continue;
          const data = await res.json() as Record<string, any>;
          const status: string = data['status'] ?? '';

          if (status === 'confirmed') {
            const botToken: string = data['bot_token'] ?? '';
            if (botToken) {
              this.store.setBotToken(botToken);
              console.error('[iLink] 扫码登录成功');
            }
            this.pendingQR.settle('success');
            this.pendingQR = null;
            this.onLoginStateChange?.();
            return;
          }

          if (status === 'expired') {
            console.error('[iLink] 二维码已过期（API 返回 expired）');
            this.pendingQR.settle('expired');
            this.pendingQR = null;
            this.onLoginStateChange?.();
            return;
          }

          // wait / scaned / scanned：继续等待
        } catch { /* 忽略网络抖动，下次重试 */ }
      }
    };
    poll().catch(e => console.error('[iLink] 登录轮询异常:', e));
  }

  private _checkActivated(userId: string): SendResult | null {
    const ctx = this.store.getContextToken(userId);
    if (!ctx) {
      return {
        status: 'error',
        message: `用户尚未激活。请让目标用户先向 ClawBot 发送任意一条消息。`,
      };
    }
    return null;
  }

  private async _sendMessage(toUserId: string, text: string): Promise<string | null> {
    const cfg = getConfig();
    const botToken = this.store.getBotToken()!;
    const contextToken = this.store.getContextToken(toUserId)!;

    try {
      const res = await fetch(`${cfg.ilinkBaseUrl}/ilink/bot/sendmessage`, {
        method: 'POST',
        headers: ilinkHeaders(botToken),
        body: JSON.stringify({
          msg: _buildTextReply(contextToken, text, toUserId),
          base_info: { channel_version: '0.3.0', bot_agent: 'hitl-mcp/0.3.0' },
        }),
        signal: AbortSignal.timeout(15_000),
      });

      if (!res.ok) return `HTTP ${res.status}`;
      const raw = await res.text();
      if (!raw.trim()) return null;
      const data = JSON.parse(raw) as Record<string, any>;
      if (data['ret'] != null && data['ret'] !== 0) {
        return `ret=${data['ret']}, errmsg=${data['errmsg']}`;
      }
      return null;
    } catch (e) {
      return String(e);
    }
  }
}

function _sleep(ms: number) {
  return new Promise<void>(r => setTimeout(r, ms));
}

// ── iLink 登录流程（供 ilink-login.ts 调用） ──────────────────────────────────

export async function ilinkLogin(storePath: string): Promise<void> {
  const cfg = getConfig();
  const store = new TokenStore(storePath);
  const base = cfg.ilinkBaseUrl;

  const qrRes = await fetch(`${base}/ilink/bot/get_bot_qrcode?bot_type=3`, {
    method: 'GET',
    headers: { 'User-Agent': UA },
  });
  if (!qrRes.ok) throw new Error(`get_bot_qrcode 失败: HTTP ${qrRes.status}`);
  const qrData = await qrRes.json() as Record<string, any>;
  if (qrData['ret'] !== 0) {
    throw new Error(qrData['errmsg'] ?? `get_bot_qrcode ret=${qrData['ret']}`);
  }

  const qrcodeKey: string = qrData['qrcode'] ?? '';
  const qrUrl: string = qrData['qrcode_img_content'] ?? '';
  if (!qrcodeKey || !qrUrl) throw new Error(`无法获取二维码: ${JSON.stringify(qrData)}`);

  console.log(`\n请使用微信扫描以下二维码登录：\n${qrUrl}\n`);
  _printQrInTerminal(qrUrl);

  for (let i = 0; i < 120; i++) {
    await _sleep(2000);
    const pollRes = await fetch(
      `${base}/ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qrcodeKey)}`,
      { method: 'GET', headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(35_000) },
    );
    if (!pollRes.ok) continue;
    const poll = await pollRes.json() as Record<string, any>;

    if (poll['status'] === 'confirmed') {
      const botToken: string = poll['bot_token'] ?? '';
      if (!botToken) throw new Error('扫码成功但未返回 bot_token');
      store.setBotToken(botToken);
      console.log(`\n登录成功！bot_token 已保存到 ${storePath}`);
      return;
    }
    if (poll['status'] === 'expired') throw new Error('二维码已过期，请重新运行登录命令');
    process.stdout.write('.');
  }

  throw new Error('等待扫码超时（240 秒）');
}

function _printQrInTerminal(url: string): void {
  // 用纯文本 URL 展示，如需真正的二维码可安装 qrcode-terminal 包
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const qrcode = require('qrcode-terminal');
    qrcode.generate(url, { small: true });
  } catch {
    // qrcode-terminal 未安装，仅打印 URL
  }
}
