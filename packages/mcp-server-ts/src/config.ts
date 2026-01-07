/**
 * MCP Server 配置
 */

export interface MCPConfig {
  /** HIL Server 的访问地址 */
  serviceUrl: string;
  /** 默认发送消息的 Chat ID（群聊或私聊） */
  defaultChatId: string;
  /** 默认项目名称，用于标识消息来源 */
  defaultProjectName: string;
  /** 默认等待回复超时时间（秒） */
  defaultTimeout: number;
  /** 轮询获取回复的间隔（秒，内部使用） */
  pollInterval: number;
}

/**
 * 从环境变量和命令行参数创建配置
 */
export function createConfig(overrides: Partial<MCPConfig> = {}): MCPConfig {
  return {
    serviceUrl: overrides.serviceUrl || process.env.SERVICE_URL || 'http://localhost:8081',
    defaultChatId: overrides.defaultChatId || process.env.DEFAULT_CHAT_ID || '',
    defaultProjectName: overrides.defaultProjectName || process.env.DEFAULT_PROJECT_NAME || '',
    defaultTimeout: overrides.defaultTimeout || parseInt(process.env.DEFAULT_TIMEOUT || '1200', 10),
    pollInterval: overrides.pollInterval || parseInt(process.env.POLL_INTERVAL || '2', 10),
  };
}

/**
 * 全局配置实例（延迟初始化）
 */
let globalConfig: MCPConfig | null = null;

export function getConfig(): MCPConfig {
  if (!globalConfig) {
    globalConfig = createConfig();
  }
  return globalConfig;
}

export function setConfig(config: MCPConfig): void {
  globalConfig = config;
}
