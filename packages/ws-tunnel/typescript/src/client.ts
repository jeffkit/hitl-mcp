/**
 * WS-Tunnel 客户端
 *
 * 连接到隧道服务器，接收请求并转发到本地目标服务
 */

import WebSocket from 'ws';
import {
  AuthMessage,
  AuthOkMessage,
  AuthErrorMessage,
  TunnelRequest,
  TunnelResponse,
  PingMessage,
  MessageType,
  createAuthMessage,
  createPongMessage,
  createResponse,
  parseMessage,
} from './protocol.js';

export interface TunnelClientConfig {
  /** 服务端 WebSocket URL */
  serverUrl: string;
  /** 隧道令牌 */
  token: string;
  /** 本地目标服务 URL */
  targetUrl: string;
  /** 重连间隔（毫秒） */
  reconnectInterval?: number;
  /** 最大重连次数（0 表示无限） */
  maxReconnectAttempts?: number;
  /** 请求超时（毫秒） */
  requestTimeout?: number;
}

export interface TunnelClientEvents {
  onConnect?: (domain: string) => void;
  onDisconnect?: () => void;
  onRequest?: (request: TunnelRequest) => void;
  onError?: (error: Error) => void;
}

export class TunnelClient {
  private config: Required<TunnelClientConfig>;
  private ws: WebSocket | null = null;
  private running = false;
  private connected = false;
  private domain: string | null = null;
  private reconnectCount = 0;
  private events: TunnelClientEvents = {};

  constructor(config: TunnelClientConfig) {
    this.config = {
      serverUrl: config.serverUrl,
      token: config.token,
      targetUrl: config.targetUrl,
      reconnectInterval: config.reconnectInterval ?? 5000,
      maxReconnectAttempts: config.maxReconnectAttempts ?? 0,
      requestTimeout: config.requestTimeout ?? 300000,
    };
  }

  /** 是否已连接 */
  get isConnected(): boolean {
    return this.connected;
  }

  /** 分配的域名 */
  get tunnelDomain(): string | null {
    return this.domain;
  }

  /** 设置事件回调 */
  on<K extends keyof TunnelClientEvents>(
    event: K,
    callback: TunnelClientEvents[K]
  ): void {
    this.events[event] = callback;
  }

  /** 启动客户端 */
  async run(): Promise<void> {
    this.running = true;

    while (this.running) {
      try {
        await this.connectAndRun();
      } catch (error) {
        if (!this.running) break;

        this.connected = false;
        this.events.onDisconnect?.();

        this.reconnectCount++;
        const maxAttempts = this.config.maxReconnectAttempts;

        if (maxAttempts > 0 && this.reconnectCount > maxAttempts) {
          console.error(`超过最大重连次数 (${maxAttempts})，停止`);
          break;
        }

        console.warn(
          `连接断开: ${error}，${this.config.reconnectInterval / 1000}秒后重连 ` +
            `(第 ${this.reconnectCount} 次)`
        );
        await this.sleep(this.config.reconnectInterval);
      }
    }
  }

  /** 停止客户端 */
  stop(): void {
    this.running = false;
    if (this.ws) {
      this.ws.close();
    }
  }

  private async connectAndRun(): Promise<void> {
    console.log(`正在连接到 ${this.config.serverUrl}...`);

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.config.serverUrl);
      this.ws = ws;

      ws.on('open', () => {
        // 发送认证消息
        const authMessage = createAuthMessage(this.config.token);
        ws.send(JSON.stringify(authMessage));
      });

      ws.on('message', async (data: Buffer) => {
        try {
          const message = parseMessage(data.toString());

          switch (message.type) {
            case MessageType.AUTH_OK:
              this.handleAuthOk(message as AuthOkMessage);
              break;

            case MessageType.AUTH_ERROR:
              this.handleAuthError(message as AuthErrorMessage);
              ws.close();
              reject(new Error((message as AuthErrorMessage).error));
              break;

            case MessageType.PING:
              ws.send(JSON.stringify(createPongMessage()));
              break;

            case MessageType.REQUEST:
              await this.handleRequest(message as TunnelRequest, ws);
              break;

            default:
              console.warn(`未知消息类型: ${message.type}`);
          }
        } catch (error) {
          console.error('处理消息错误:', error);
          this.events.onError?.(error as Error);
        }
      });

      ws.on('close', () => {
        this.connected = false;
        this.domain = null;
        resolve();
      });

      ws.on('error', (error) => {
        console.error('WebSocket 错误:', error);
        this.events.onError?.(error);
        reject(error);
      });
    });
  }

  private handleAuthOk(message: AuthOkMessage): void {
    this.domain = message.domain;
    this.connected = true;
    this.reconnectCount = 0;
    console.log(`已连接: domain=${this.domain}`);
    this.events.onConnect?.(this.domain);
  }

  private handleAuthError(message: AuthErrorMessage): void {
    console.error(`认证失败: ${message.error}`);
  }

  private async handleRequest(
    request: TunnelRequest,
    ws: WebSocket
  ): Promise<void> {
    this.events.onRequest?.(request);

    const startTime = Date.now();
    let response: TunnelResponse;

    try {
      // 构建完整 URL
      const url = `${this.config.targetUrl.replace(/\/$/, '')}${request.path}`;

      // 解析请求体
      let body: string | undefined;
      if (request.body) {
        body = request.body;
      }

      // 发送请求
      const fetchOptions: RequestInit = {
        method: request.method,
        headers: request.headers,
        body: body,
      };

      const timeout = request.timeout ?? this.config.requestTimeout;
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      try {
        const fetchResponse = await fetch(url, {
          ...fetchOptions,
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        const responseBody = await fetchResponse.text();
        const durationMs = Date.now() - startTime;

        response = createResponse(
          request.id,
          fetchResponse.status,
          responseBody,
          Object.fromEntries(fetchResponse.headers.entries()),
          undefined,
          durationMs
        );
      } catch (error: any) {
        clearTimeout(timeoutId);
        throw error;
      }
    } catch (error: any) {
      const durationMs = Date.now() - startTime;

      if (error.name === 'AbortError') {
        response = createResponse(
          request.id,
          504,
          null,
          {},
          'Target service timeout',
          durationMs
        );
      } else if (error.code === 'ECONNREFUSED') {
        response = createResponse(
          request.id,
          503,
          null,
          {},
          `Target service unavailable: ${error.message}`,
          durationMs
        );
      } else {
        response = createResponse(
          request.id,
          500,
          null,
          {},
          error.message,
          durationMs
        );
      }
    }

    ws.send(JSON.stringify(response));
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/** 运行隧道客户端的便捷函数 */
export async function runTunnelClient(
  serverUrl: string,
  token: string,
  targetUrl: string,
  reconnectInterval = 5000
): Promise<void> {
  const client = new TunnelClient({
    serverUrl,
    token,
    targetUrl,
    reconnectInterval,
  });
  await client.run();
}
