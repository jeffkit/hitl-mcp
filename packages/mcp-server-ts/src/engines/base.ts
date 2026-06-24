export interface SendResult {
  status: 'success' | 'timeout' | 'error' | 'login_required';
  replies?: Array<{ text: string }>;
  message: string;
  /** 微信扫码链接（手机可直接打开），status=login_required 时存在 */
  qrUrl?: string;
  /** 登录二维码（base64 PNG），status=login_required 时存在 */
  qrCode?: { data: string; mimeType: 'image/png' };
  /** Agent 下一步应执行的操作，status=login_required 时存在 */
  nextAction?: string;
}

export interface Engine {
  /** 启动引擎（建立连接、启动后台任务等） */
  start(): Promise<void>;
  /** 停止引擎 */
  stop(): Promise<void>;
  /** 发消息并等待回复 */
  sendAndWait(
    recipient: string,
    text: string,
    timeoutSec: number,
    projectName?: string,
  ): Promise<SendResult>;
  /** 仅发消息，不等待回复 */
  sendOnly(
    recipient: string,
    text: string,
    projectName?: string,
  ): Promise<SendResult>;
}
