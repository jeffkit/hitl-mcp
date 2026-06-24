/**
 * 企业微信 AI Bot 引擎
 *
 * 通过 WebSocket 长连接直接对接企业微信 AI Bot 服务端。
 * 无需 HIL Server，无需公网 IP，无需回调 URL。
 *
 * 官方协议文档：https://developer.work.weixin.qq.com/document/path/101463
 *
 * 协议：
 *   连接 wss://openws.work.weixin.qq.com
 *   → aibot_subscribe（鉴权，body 包裹，headers.req_id 必填）
 *   ← 响应无 cmd，通过 headers.req_id 匹配，errcode=0 表示成功
 *   → ping（心跳，每 30s）
 *   ← pong（errcode=0）
 *   ← aibot_msg_callback（用户消息，字段在 body 中）
 *   → aibot_send_msg（发送消息，body 包裹）
 */

import WebSocket from 'ws';
import { getConfig } from '../config.js';
import { sessionManager, TimeoutError } from '../session.js';
import type { Engine, SendResult } from './base.js';

export class WecomAibotEngine implements Engine {
  private ws: WebSocket | null = null;
  private ready = false;
  private readyPromise: Promise<void> | null = null;
  private readyResolve?: () => void;
  private readyReject?: (err: Error) => void;
  private heartbeatTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private stopped = false;

  /** req_id → callback，用于匹配无 cmd 的响应 */
  private _pending = new Map<string, (resp: any) => void>();

  async start(): Promise<void> {
    const cfg = getConfig();
    if (!cfg.wecomBotId || !cfg.wecomBotSecret) {
      throw new Error('必须通过 --bot-id 和 --bot-secret 指定企业微信 AI Bot 凭证');
    }
    console.error(`[WecomAibot] 连接: ${cfg.wecomWsUrl}`);
    this._connect();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  private _resetReady() {
    this.ready = false;
    this.readyPromise = new Promise<void>((res, rej) => {
      this.readyResolve = res;
      this.readyReject = rej;
    });
  }

  private _connect() {
    this._resetReady();
    this._pending.clear();
    const cfg = getConfig();
    const ws = new WebSocket(cfg.wecomWsUrl);
    this.ws = ws;

    ws.on('open', () => {
      const reqId = _genReqId();
      // 官方格式：bot_id/secret 放在 body 中，headers 携带 req_id
      this._sendRaw(ws, {
        cmd: 'aibot_subscribe',
        headers: { req_id: reqId },
        body: {
          bot_id: cfg.wecomBotId,
          secret: cfg.wecomBotSecret,
        },
      }, reqId, (resp) => {
        if (resp.errcode === 0) {
          this.ready = true;
          this.readyResolve?.();
          console.error('[WecomAibot] 订阅成功，连接就绪');
        } else {
          console.error(`[WecomAibot] 订阅失败: errcode=${resp.errcode}, errmsg=${resp.errmsg}`);
          this.readyReject?.(new Error(`订阅失败: ${resp.errmsg}`));
        }
      });

      this.heartbeatTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          const pingId = _genReqId();
          this._sendRaw(ws, { cmd: 'ping', headers: { req_id: pingId } }, pingId, () => {});
        }
      }, cfg.wecomHeartbeatInterval * 1000);
    });

    ws.on('message', (raw: Buffer) => {
      let msg: any;
      try { msg = JSON.parse(raw.toString()); } catch { return; }
      this._handleMessage(msg);
    });

    ws.on('close', () => {
      if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
      this._pending.clear();
      this.ready = false;
      if (!this.stopped) {
        const delay = cfg.wecomReconnectDelay * 1000;
        console.error(`[WecomAibot] 连接断开，${delay / 1000}s 后重连...`);
        this.reconnectTimer = setTimeout(() => this._connect(), delay);
      }
    });

    ws.on('error', (err: Error) => {
      console.error('[WecomAibot] WebSocket 错误:', err.message);
    });
  }

  /** 发送消息，如提供 reqId 则注册响应回调 */
  private _sendRaw(ws: WebSocket, payload: any, reqId: string | null, cb: (resp: any) => void) {
    if (reqId) this._pending.set(reqId, cb);
    ws.send(JSON.stringify(payload));
  }

  private _handleMessage(msg: any) {
    const cmd = msg.cmd as string | undefined;
    const reqId = msg.headers?.req_id as string | undefined;

    // 响应消息：无 cmd，通过 req_id 匹配待处理请求
    if (!cmd && reqId && this._pending.has(reqId)) {
      const cb = this._pending.get(reqId)!;
      this._pending.delete(reqId);
      cb(msg);
      return;
    }

    if (cmd === 'aibot_msg_callback') {
      const body = msg.body ?? {};
      const chatType: string = body.chattype ?? 'single';
      // 单聊没有 chatid，用 from.userid 作为 recipient；群聊用 chatid
      const recipient: string = chatType === 'group'
        ? (body.chatid ?? '')
        : (body.from?.userid ?? '');
      const msgType: string = body.msgtype ?? '';
      const content: string = body.text?.content ?? '';

      if (msgType !== 'text') return;

      // 引用回复：WeCom 将被引用内容以 「原文」\n 格式嵌入正文开头
      // 提取引用部分（「...」块）传给 dispatch，以便匹配 [#shortId]
      const quoteMatch = content.match(/^「(.+?)」\s*/s);
      const quotes = quoteMatch ? [quoteMatch[1]] : [];

      const matched = sessionManager.dispatch(recipient, content, quotes);
      if (!matched) {
        console.error(`[WecomAibot] 无匹配会话，忽略: recipient=${recipient}, text=${content.substring(0, 40)}`);
      }
      return;
    }

    if (cmd === 'aibot_event_callback') {
      const eventType = msg.body?.event?.eventtype;
      if (eventType === 'disconnected_event') {
        console.error('[WecomAibot] 收到 disconnected_event，连接被新连接踢出');
      }
      return;
    }

    // 其他未处理消息静默忽略
  }

  private async _waitReady(timeoutMs = 30_000): Promise<void> {
    if (this.ready) return;
    await Promise.race([
      this.readyPromise,
      new Promise<void>((_, rej) =>
        setTimeout(() => rej(new Error('等待 WeCom 连接超时')), timeoutMs)
      ),
    ]);
  }

  private async _send(chatId: string, text: string): Promise<void> {
    await this._waitReady();
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket 未连接');
    }
    const reqId = _genReqId();
    // 官方格式：chatid/msgtype/markdown 放在 body 中
    this._sendRaw(this.ws, {
      cmd: 'aibot_send_msg',
      headers: { req_id: reqId },
      body: {
        chatid: chatId,
        chat_type: 0,
        msgtype: 'markdown',
        markdown: { content: text },
      },
    }, reqId, (resp) => {
      if (resp.errcode !== 0) {
        console.error(`[WecomAibot] 发送消息失败: errcode=${resp.errcode}, errmsg=${resp.errmsg}`);
      }
    });
  }

  async sendAndWait(recipient: string, text: string, timeoutSec: number, _projectName?: string): Promise<SendResult> {
    const shortId = _genShortId();
    const promise = sessionManager.create(shortId, recipient, timeoutSec * 1000);

    try {
      await this._send(recipient, text);
    } catch (e) {
      sessionManager.cancel(shortId);
      return { status: 'error', message: `发送失败: ${e}` };
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
    try {
      await this._send(recipient, text);
      return { status: 'success', message: '消息发送成功' };
    } catch (e) {
      return { status: 'error', message: `发送失败: ${e}` };
    }
  }
}

function _genShortId(): string {
  return Math.random().toString(16).slice(2, 8);
}

function _genReqId(): string {
  return `req_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}
