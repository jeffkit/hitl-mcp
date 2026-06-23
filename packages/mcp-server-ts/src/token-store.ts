/**
 * iLink Token 持久化存储（JSON 文件）
 *
 * 存储内容：
 *   bot_token        — ClawBot 登录凭证
 *   get_updates_buf  — 长轮询游标
 *   context_tokens   — { [from_user_id]: context_token }（回复时必须携带）
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { dirname } from 'path';

interface StoreData {
  bot_token?: string;
  get_updates_buf?: string;
  context_tokens?: Record<string, string>;
}

export class TokenStore {
  private path: string;
  private data: StoreData = {};

  constructor(storePath: string) {
    this.path = storePath;
    this._load();
  }

  private _load(): void {
    if (existsSync(this.path)) {
      try {
        this.data = JSON.parse(readFileSync(this.path, 'utf-8'));
      } catch {
        this.data = {};
      }
    }
  }

  private _save(): void {
    const dir = dirname(this.path);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    writeFileSync(this.path, JSON.stringify(this.data, null, 2), 'utf-8');
  }

  getBotToken(): string | null {
    return this.data.bot_token ?? null;
  }

  setBotToken(token: string): void {
    this.data.bot_token = token;
    this._save();
  }

  getUpdatesBuf(): string {
    return this.data.get_updates_buf ?? '';
  }

  setUpdatesBuf(buf: string): void {
    this.data.get_updates_buf = buf;
    this._save();
  }

  getContextToken(fromUserId: string): string | null {
    return this.data.context_tokens?.[fromUserId] ?? null;
  }

  setContextToken(fromUserId: string, token: string): void {
    this.data.context_tokens ??= {};
    this.data.context_tokens[fromUserId] = token;
    this._save();
  }

  listKnownUsers(): Array<{ fromUserId: string; hasContextToken: boolean }> {
    return Object.entries(this.data.context_tokens ?? {}).map(([id, t]) => ({
      fromUserId: id,
      hasContextToken: Boolean(t),
    }));
  }

  /**
   * 返回第一个已激活用户的 ID，没有则返回 null。
   * 不区分单/多用户，始终取第一个（通常就是自己）。
   */
  resolveRecipient(): string | null {
    const users = Object.keys(this.data.context_tokens ?? {});
    return users[0] ?? null;
  }
}
