/**
 * Human-in-the-Loop MCP Server
 * 
 * 让 AI 能够发送消息到企业微信并等待用户回复
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import { existsSync } from 'fs';
import { extname } from 'path';
import { getConfig } from './config.js';
import { WeComClient } from './wecom-client.js';

/**
 * 根据文件扩展名推断 MIME 类型
 */
function guessImageMime(urlPath: string): string {
  const ext = extname(urlPath).toLowerCase();
  const mimeMap: Record<string, string> = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
  };
  return mimeMap[ext] || 'image/png';
}

/**
 * 等待指定时间
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 下载图片并返回 base64 数据和 MIME 类型
 * 
 * 支持:
 * - data: URL (直接提取 base64)
 * - http/https URL (下载并编码)
 */
async function downloadImage(url: string): Promise<{ data: string; mimeType: string } | null> {
  try {
    // 处理 data URL: data:image/jpeg;base64,xxxxx
    if (url.startsWith('data:')) {
      const commaIdx = url.indexOf(',');
      if (commaIdx === -1) {
        console.error(`[Image] 无效的 data URL: ${url.substring(0, 100)}`);
        return null;
      }
      const header = url.substring(0, commaIdx);
      const data = url.substring(commaIdx + 1);
      // 提取 mime type: "data:image/jpeg;base64" -> "image/jpeg"
      const mimeMatch = header.match(/^data:([^;,]+)/);
      const mimeType = mimeMatch ? mimeMatch[1] : 'image/png';
      return { data, mimeType };
    }

    // 处理 HTTP(S) URL
    if (url.startsWith('http://') || url.startsWith('https://')) {
      const response = await fetch(url, { signal: AbortSignal.timeout(30000) });
      if (!response.ok) {
        console.error(`[Image] 下载失败: HTTP ${response.status} for ${url.substring(0, 80)}`);
        return null;
      }

      const buffer = Buffer.from(await response.arrayBuffer());
      const contentType = response.headers.get('content-type') || '';
      let mimeType = contentType.split(';')[0].trim();

      // 如果 Content-Type 不是图片类型，尝试从 URL 推断
      if (!mimeType.startsWith('image/')) {
        const urlPath = new URL(url).pathname;
        mimeType = guessImageMime(urlPath);
      }

      const data = buffer.toString('base64');
      console.error(`[Image] 图片下载成功: ${url.substring(0, 80)}..., size=${buffer.length}, type=${mimeType}`);
      return { data, mimeType };
    }

    console.error(`[Image] 不支持的图片 URL scheme: ${url.substring(0, 50)}`);
    return null;
  } catch (error) {
    console.error(`[Image] 下载图片失败: ${url.substring(0, 80)}..., error=${error}`);
    return null;
  }
}

/**
 * 处理回复中的图片：下载并转换为 MCP ImageContent
 */
async function processRepliesWithImages(
  resultJson: string,
  replies: any[]
): Promise<{ content: any[] }> {
  const contentBlocks: any[] = [{ type: 'text', text: resultJson }];

  for (const reply of replies) {
    const imageUrl = reply?.image_url;
    if (!imageUrl) continue;

    const downloaded = await downloadImage(imageUrl);
    if (downloaded) {
      contentBlocks.push({
        type: 'image',
        data: downloaded.data,
        mimeType: downloaded.mimeType,
      });
      console.error(`[Image] 图片已编码为 MCP ImageContent: mime=${downloaded.mimeType}`);
    }
  }

  if (contentBlocks.length > 1) {
    console.error(`[Image] 返回 MCP 响应: ${contentBlocks.length} 个内容块 (1 text + ${contentBlocks.length - 1} images)`);
  }

  return { content: contentBlocks };
}

/**
 * 创建并启动 MCP Server
 */
export async function startServer(): Promise<void> {
  const config = getConfig();
  const client = new WeComClient();

  // 创建 MCP Server
  const server = new Server(
    {
      name: 'hitl-mcp',
      version: '0.2.1',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // 定义工具列表
  const tools: Tool[] = [
    {
      name: 'send_and_wait_reply',
      description: `发送消息到企业微信并等待用户回复。

这个工具会：
1. 将消息发送到指定的企微群或个人会话
2. 如果提供了图片路径，也会上传并发送图片
3. 等待用户回复（需要用户在企微中 @机器人 回复）
4. 返回用户的回复内容

注意：
- 用户需要 @机器人 才能触发回调
- 超时后会返回超时状态
- 私聊场景下用户直接回复即可
- 当多个项目同时发送消息时，用户可以使用「引用回复」来精确回复特定消息

返回格式：
{
    "status": "success" | "timeout" | "error",
    "replies": [
        {
            "msg_type": "text",
            "content": "用户回复的文本",
            "from_user": {"name": "张三", "alias": "zhangsan"},
            "timestamp": "2024-01-01T10:30:00"
        }
    ],
    "message": "描述信息"
}`,
      inputSchema: {
        type: 'object',
        properties: {
          message: {
            type: 'string',
            description: '要发送给用户的消息内容',
          },
          chat_id: {
            type: 'string',
            description: '目标群 ID 或个人会话 ID。如果不指定，使用默认配置',
          },
          image_paths: {
            type: 'array',
            items: { type: 'string' },
            description: '要发送的本地图片文件路径列表',
          },
          project_name: {
            type: 'string',
            description: '项目名称，用于标识消息来源。如果不指定，使用默认配置',
          },
        },
        required: ['message'],
      },
    },
    {
      name: 'send_message_only',
      description: `仅发送消息到企业微信，不等待回复。

适用于只需要通知用户、不需要交互的场景。

返回格式：
{
    "status": "success" | "error",
    "message": "描述信息"
}`,
      inputSchema: {
        type: 'object',
        properties: {
          message: {
            type: 'string',
            description: '要发送给用户的消息内容',
          },
          chat_id: {
            type: 'string',
            description: '目标群 ID 或个人会话 ID',
          },
          image_paths: {
            type: 'array',
            items: { type: 'string' },
            description: '要发送的本地图片文件路径列表',
          },
          project_name: {
            type: 'string',
            description: '项目名称，用于标识消息来源。如果不指定，使用默认配置',
          },
        },
        required: ['message'],
      },
    },
  ];

  // 注册工具列表处理器
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools,
  }));

  // 注册工具调用处理器
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    try {
      if (name === 'send_and_wait_reply') {
        return await handleSendAndWaitReply(client, args);
      } else if (name === 'send_message_only') {
        return await handleSendMessageOnly(client, args);
      } else {
        throw new Error(`Unknown tool: ${name}`);
      }
    } catch (error) {
      console.error(`[Server] Tool execution error:`, error);
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              status: 'error',
              message: error instanceof Error ? error.message : String(error),
            }),
          },
        ],
      };
    }
  });

  // 启动服务器
  const transport = new StdioServerTransport();
  await server.connect(transport);

  console.error('[Server] WeCom HIL MCP Server started');
  console.error(`[Server]   服务地址: ${config.serviceUrl}`);
  console.error(`[Server]   默认 Chat ID: ${config.defaultChatId || '(未设置)'}`);
  console.error(`[Server]   默认项目名: ${config.defaultProjectName || '(未设置)'}`);
  console.error(`[Server]   超时时间: ${config.defaultTimeout}s`);
  console.error(`[Server]   轮询间隔: ${config.pollInterval}s`);
}

/**
 * 处理 send_and_wait_reply 工具调用
 */
async function handleSendAndWaitReply(
  client: WeComClient,
  args: any
): Promise<any> {
  const config = getConfig();
  const timeout = config.defaultTimeout;

  const message: string = args.message;
  const chatId: string | undefined = args.chat_id;
  const imagePaths: string[] | undefined = args.image_paths;
  const projectName: string | undefined = args.project_name;

  // 如果没有指定 chat_id，使用配置中的默认值
  console.error(`[Tool] 原始 chat_id=${chatId}, config.defaultChatId=${config.defaultChatId}`);
  const effectiveChatId = chatId || config.defaultChatId || undefined;
  console.error(
    `[Tool] 开始发送消息: message=${message.substring(0, 50)}..., ` +
    `effectiveChatId=${effectiveChatId}, timeout=${timeout}, projectName=${projectName}`
  );

  // 处理图片上传
  const imageUrls: string[] = [];
  if (imagePaths && imagePaths.length > 0) {
    for (const path of imagePaths) {
      if (existsSync(path)) {
        console.error(`[Tool] 上传图片: ${path}`);
        const result = await client.uploadImage(path);
        if (result.success && result.image_url) {
          imageUrls.push(result.image_url);
          console.error(`[Tool] 图片上传成功: ${path}`);
        } else {
          console.error(`[Tool] 图片上传失败: ${path}, ${JSON.stringify(result)}`);
        }
      } else {
        console.error(`[Tool] 图片文件不存在: ${path}`);
      }
    }
  }

  console.error(`[Tool] 共上传 ${imageUrls.length} 张图片`);

  // 发送消息（把 timeout 传给服务端，确保会话超时时间一致）
  const sendResult = await client.sendMessage({
    message,
    chat_id: effectiveChatId,
    images: imageUrls.length > 0 ? imageUrls : undefined,
    project_name: projectName,
    timeout,
    wait_reply: true,
  });

  if (!sendResult.success) {
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            status: 'error',
            replies: [],
            message: `发送消息失败: ${sendResult.error || '未知错误'}`,
          }),
        },
      ],
    };
  }

  const sessionId = sendResult.session_id;
  if (!sessionId) {
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            status: 'error',
            replies: [],
            message: '发送成功但未获取到会话 ID',
          }),
        },
      ],
    };
  }

  console.error(`[Tool] 消息发送成功, session_id=${sessionId}, 开始等待回复...`);

  // 轮询等待回复
  const startTime = Date.now();
  const pollInterval = config.pollInterval * 1000;

  try {
    while (Date.now() - startTime < timeout * 1000) {
      try {
        const result = await client.pollReplies(sessionId);

        if (result.has_reply) {
          const replies = result.replies || [];
          console.error(`[Tool] 收到用户回复: ${replies.length} 条`);
          const replyResult = {
            status: 'success',
            replies,
            message: `收到 ${replies.length} 条回复`,
          };
          // 自动下载图片并作为 MCP ImageContent 返回
          return await processRepliesWithImages(
            JSON.stringify(replyResult),
            replies
          );
        }

        if (result.status === 'not_found') {
          return {
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  status: 'error',
                  replies: [],
                  message: '会话不存在或已过期',
                }),
              },
            ],
          };
        }
      } catch (error) {
        console.error(`[Tool] 轮询失败:`, error);
      }

      // 等待一段时间再轮询
      await sleep(pollInterval);
    }

    // 超时
    console.error(`[Tool] 等待超时: session_id=${sessionId}`);

    // 标记会话超时
    await client.markTimeout(sessionId);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            status: 'timeout',
            replies: [],
            message: `等待 ${timeout} 秒后超时，未收到用户回复`,
          }),
        },
      ],
    };
  } catch (error) {
    // 如果是取消错误，通知服务端清理会话
    console.error(`[Tool] 发生错误或用户取消: ${error}`);
    try {
      await client.markTimeout(sessionId);
      console.error(`[Tool] 已通知服务端清理会话: session_id=${sessionId}`);
    } catch (cleanupError) {
      console.error(`[Tool] 通知服务端清理会话失败:`, cleanupError);
    }
    throw error;
  }
}

/**
 * 处理 send_message_only 工具调用
 */
async function handleSendMessageOnly(
  client: WeComClient,
  args: any
): Promise<any> {
  const config = getConfig();

  const message: string = args.message;
  const chatId: string | undefined = args.chat_id;
  const imagePaths: string[] | undefined = args.image_paths;
  const projectName: string | undefined = args.project_name;

  // 如果没有指定 chat_id，使用配置中的默认值
  const effectiveChatId = chatId || config.defaultChatId || undefined;
  console.error(
    `[Tool] 发送消息（不等待回复）: message=${message.substring(0, 50)}..., ` +
    `chat_id=${effectiveChatId}`
  );

  // 处理图片上传
  const imageUrls: string[] = [];
  if (imagePaths && imagePaths.length > 0) {
    for (const path of imagePaths) {
      if (existsSync(path)) {
        const result = await client.uploadImage(path);
        if (result.success && result.image_url) {
          imageUrls.push(result.image_url);
        }
      }
    }
  }

  // 发送消息（不等待回复，不创建会话）
  const sendResult = await client.sendMessage({
    message,
    chat_id: effectiveChatId,
    images: imageUrls.length > 0 ? imageUrls : undefined,
    project_name: projectName,
    wait_reply: false,
  });

  if (sendResult.success) {
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            status: 'success',
            message: '消息发送成功',
          }),
        },
      ],
    };
  } else {
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            status: 'error',
            message: `发送失败: ${sendResult.error || '未知错误'}`,
          }),
        },
      ],
    };
  }
}
