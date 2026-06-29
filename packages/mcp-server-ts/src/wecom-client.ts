/**
 * 服务客户端
 * 
 * 用于 MCP Server 调用 HITL Server
 */

import { readFileSync } from 'fs';
import { basename } from 'path';
import { getConfig } from './config.js';

export interface SendMessageRequest {
  message: string;
  chat_id?: string;
  user_id?: string;
  chat_type?: 'group' | 'single';
  images?: string[];
  mention_list?: string[];
  project_name?: string;
  timeout?: number;
  wait_reply?: boolean;
}

export interface SendMessageResponse {
  success: boolean;
  session_id?: string;
  error?: string;
}

export interface UploadImageResponse {
  success: boolean;
  image_url?: string;
  error?: string;
}

export interface Reply {
  msg_type: string;
  content: string;
  from_user: {
    name: string;
    alias: string;
  };
  timestamp: string;
}

export interface PollRepliesResponse {
  status?: string;
  has_reply: boolean;
  replies: Reply[];
}

export interface TimeoutResponse {
  success: boolean;
  message?: string;
}

/**
 * 企业微信客户端（连接 HITL Server）
 */
export class WeComClient {
  private baseUrlOverride?: string;
  private timeout: number = 30000;

  constructor(baseUrl?: string) {
    this.baseUrlOverride = baseUrl;
  }

  /**
   * 每次调用时从 config 读取，支持命令行参数覆盖
   */
  private get baseUrl(): string {
    const url = this.baseUrlOverride || getConfig().serviceUrl;
    return url.replace(/\/$/, '');
  }

  /**
   * 发送消息
   */
  async sendMessage(request: SendMessageRequest): Promise<SendMessageResponse> {
    const url = `${this.baseUrl}/send`;
    
    const payload: Record<string, any> = {
      message: request.message,
      chat_type: request.chat_type || 'group',
      wait_reply: request.wait_reply !== false,
    };

    if (request.chat_id) payload.chat_id = request.chat_id;
    if (request.user_id) payload.user_id = request.user_id;
    if (request.images) payload.images = request.images;
    if (request.mention_list) payload.mention_list = request.mention_list;
    if (request.project_name) payload.project_name = request.project_name;
    if (request.timeout !== undefined) payload.timeout = request.timeout;

    console.error(`[WeComClient] 发送消息: url=${url}, payload=${JSON.stringify(payload)}`);

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(this.timeout),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json() as SendMessageResponse;
  }

  /**
   * 上传图片
   */
  async uploadImage(imagePath: string): Promise<UploadImageResponse> {
    const url = `${this.baseUrl}/upload-image`;

    try {
      // 读取图片内容
      const content = readFileSync(imagePath);
      const filename = basename(imagePath);

      // 确定 MIME 类型
      const ext = imagePath.toLowerCase().split('.').pop();
      const mimeTypes: Record<string, string> = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp',
      };
      const contentType = mimeTypes[ext || 'png'] || 'image/png';

      console.error(`[WeComClient] 上传图片: url=${url}, path=${imagePath}, size=${content.length}`);

      // 使用原生 FormData 和 Blob
      const formData = new FormData();
      const blob = new Blob([content], { type: contentType });
      // @ts-ignore - File constructor exists in Node.js 20+
      const file = new File([blob], filename, { type: contentType });
      formData.append('file', file);

      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        signal: AbortSignal.timeout(this.timeout),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`);
      }

      return await response.json() as UploadImageResponse;
    } catch (error) {
      console.error(`[WeComClient] 上传图片失败:`, error);
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * 轮询获取会话回复
   */
  async pollReplies(sessionId: string): Promise<PollRepliesResponse> {
    const url = `${this.baseUrl}/poll/${sessionId}`;

    const response = await fetch(url, {
      method: 'GET',
      signal: AbortSignal.timeout(this.timeout),
    });

    if (response.status === 404) {
      return { status: 'not_found', has_reply: false, replies: [] };
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json() as PollRepliesResponse;
  }

  /**
   * 标记会话超时
   */
  async markTimeout(sessionId: string): Promise<TimeoutResponse> {
    const url = `${this.baseUrl}/session/${sessionId}/timeout`;

    const response = await fetch(url, {
      method: 'POST',
      signal: AbortSignal.timeout(this.timeout),
    });

    if (response.status === 404) {
      return { success: false, message: '会话不存在' };
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json() as TimeoutResponse;
  }
}
