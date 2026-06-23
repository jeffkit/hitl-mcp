/**
 * 本地会话管理（供 wecom-aibot / ilink 引擎使用）
 *
 * 每个 send_and_wait_reply 调用创建一个 Session，用 Promise + setTimeout 等待回复。
 * 回复匹配优先级：
 *   1. quotes 中含 [#shortId] → 精确匹配
 *   2. 消息正文含 [#shortId]  → 精确匹配
 *   3. 同 recipient 最早的待处理会话 → FIFO 匹配
 */

const SHORT_ID_RE = /\[#([0-9a-f]{6,8})\]/;

export interface ReplyData {
  text: string;
  recipient: string;
}

interface PendingSession {
  shortId: string;
  recipient: string;
  resolve: (data: ReplyData) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class TimeoutError extends Error {
  constructor(timeoutSec: number) {
    super(`等待 ${timeoutSec} 秒后超时，未收到回复`);
    this.name = 'TimeoutError';
  }
}

class SessionManager {
  private sessions = new Map<string, PendingSession>();
  // recipient → [shortId, ...] (FIFO order)
  private queue = new Map<string, string[]>();

  /**
   * 创建会话，返回等待回复的 Promise。
   * 超时后自动 reject TimeoutError。
   */
  create(shortId: string, recipient: string, timeoutMs: number): Promise<ReplyData> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._cleanup(shortId);
        reject(new TimeoutError(Math.round(timeoutMs / 1000)));
      }, timeoutMs);

      this.sessions.set(shortId, { shortId, recipient, resolve, timer });
      const q = this.queue.get(recipient) ?? [];
      q.push(shortId);
      this.queue.set(recipient, q);
    });
  }

  /**
   * 分发收到的用户消息，尝试匹配并解决对应会话。
   * @returns 是否成功匹配到某个会话
   */
  dispatch(recipient: string, text: string, quotes?: string[]): boolean {
    const reply: ReplyData = { text, recipient };

    // 1. quotes 中提取 shortId
    if (quotes) {
      for (const q of quotes) {
        const m = q.match(SHORT_ID_RE);
        if (m && this.sessions.has(m[1])) {
          return this._resolve(m[1], reply);
        }
      }
    }

    // 2. 正文中提取 shortId
    const m = text.match(SHORT_ID_RE);
    if (m && this.sessions.has(m[1])) {
      return this._resolve(m[1], reply);
    }

    // 3. FIFO 匹配
    const q = this.queue.get(recipient);
    if (q && q.length > 0) {
      return this._resolve(q[0], reply);
    }

    return false;
  }

  /** 取消会话（用于超时前的主动清理） */
  cancel(shortId: string): void {
    const session = this.sessions.get(shortId);
    if (!session) return;
    clearTimeout(session.timer);
    this._cleanup(shortId);
  }

  private _resolve(shortId: string, reply: ReplyData): boolean {
    const session = this.sessions.get(shortId);
    if (!session) return false;
    clearTimeout(session.timer);
    this._cleanup(shortId);
    session.resolve(reply);
    return true;
  }

  private _cleanup(shortId: string): void {
    const session = this.sessions.get(shortId);
    if (!session) return;
    this.sessions.delete(shortId);
    const q = this.queue.get(session.recipient) ?? [];
    const idx = q.indexOf(shortId);
    if (idx >= 0) q.splice(idx, 1);
  }
}

export const sessionManager = new SessionManager();
