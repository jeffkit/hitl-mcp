/**
 * 统一配置
 *
 * 所有配置均通过命令行参数传入（不依赖环境变量）。
 *
 * 引擎选择（--engine）：
 *   auto        → 自动：查询管理台已注册的内置引擎，按 ilink→wecom-aibot→telegram→discord→feishu 优先级选用（默认）
 *   wecom-aibot → 企业微信智能机器人（走 HITL Server 的 wecom-aibot 内置引擎）
 *   ilink       → 微信 ClawBot/iLink（走 HITL Server 的 ilink 内置引擎）
 *   telegram    → Telegram Bot（走 HITL Server 的 telegram 内置引擎，长轮询在服务端维持）
 *   discord     → Discord Bot（走 HITL Server 的 discord 内置引擎，Gateway WS 在服务端维持）
 *   feishu      → 飞书企业自建应用（走 HITL Server 的 feishu 内置引擎，WebSocket 在服务端维持）
 */

/** 任意 string 也可（外置插件渠道，走 GenericEngine 通用路径） */
export type EngineType = 'auto' | 'wecom-aibot' | 'ilink' | 'telegram' | 'discord' | 'feishu' | (string & {});

export interface Config {
  engine: EngineType;

  // ── 通用 ────────────────────────────────────────────────────────────────────
  /** 默认收件人：chatid（wecom-aibot）；ilink 引擎自动推断，通常无需设置 */
  defaultRecipient: string;
  defaultProjectName: string;
  /** 等待回复超时（秒） */
  defaultTimeout: number;
  /** bot_key：ilink/wecom-aibot 走 HITL Server 时的路由键 */
  botKey: string;

  // ── 共享部署模式 ──────────────────────────────────────────────────────────────
  /** 共享部署模式：HITL Server 部署在服务器端、全员共用一个企微 AI Bot。
   *  开启后：recipient(chat_id) 必填；请求带 Authorization Bearer。 */
  shared: boolean;
  /** 调用 HITL Server /api/* 用的 API Key（Bearer Token） */
  apiKey: string;

  // ── HITL Server 引擎 ─────────────────────────────────────────────────────────
  serviceUrl: string;
  pollInterval: number;

  // ── 企业微信 AI Bot 引擎 ─────────────────────────────────────────────────────
  wecomBotId: string;
  wecomBotSecret: string;
  wecomWsUrl: string;
  wecomHeartbeatInterval: number;
  wecomReconnectDelay: number;
  wecomMaxReconnectDelay: number;

  // ── iLink 引擎 ───────────────────────────────────────────────────────────────
  /** iLink API 基础地址（登录扫码、getupdates、sendmessage 均走此地址） */
  ilinkBaseUrl: string;
  ilinkTokenStorePath: string;
  ilinkPollTimeout: number;

  // ── Telegram / Discord / 飞书 引擎 ──────────────────────────────────────────
  /** Telegram Bot Token（--tg-token，自动向 HITL Server 注册 telegram 引擎） */
  tgToken: string;
  /** Discord Bot Token（--discord-token，自动向 HITL Server 注册 discord 引擎） */
  discordToken: string;
  /** 飞书企业自建应用 App ID（--feishu-app-id） */
  feishuAppId: string;
  /** 飞书企业自建应用 App Secret（--feishu-app-secret） */
  feishuAppSecret: string;

  // ── 通用外置引擎 ──────────────────────────────────────────────────────────
  /** 引擎注册凭证 JSON（--engine-credentials '{"bot_token": "..."}'，
   *  engine 为非内置渠道时 POST /api/engines/{type}/start 用；字段由渠道定义） */
  engineCredentials: string;
}

export function createConfig(opts: Partial<Config>): Config {
  return {
    engine:               opts.engine               ?? 'auto',
    defaultRecipient:     opts.defaultRecipient     ?? '',
    defaultProjectName:   opts.defaultProjectName   ?? '',
    defaultTimeout:       opts.defaultTimeout       ?? 7200,
    botKey:               opts.botKey               ?? '',
    shared:               opts.shared               ?? false,
    apiKey:               opts.apiKey               ?? '',
    serviceUrl:           opts.serviceUrl           ?? 'http://localhost:8081',
    pollInterval:         opts.pollInterval         ?? 2,
    wecomBotId:           opts.wecomBotId           ?? '',
    wecomBotSecret:       opts.wecomBotSecret       ?? '',
    wecomWsUrl:           opts.wecomWsUrl           ?? 'wss://openws.work.weixin.qq.com',
    wecomHeartbeatInterval: opts.wecomHeartbeatInterval ?? 30,
    wecomReconnectDelay:  opts.wecomReconnectDelay  ?? 5,
    wecomMaxReconnectDelay: opts.wecomMaxReconnectDelay ?? 60,
    ilinkBaseUrl:         opts.ilinkBaseUrl         ?? 'https://ilinkai.weixin.qq.com',
    ilinkTokenStorePath:  opts.ilinkTokenStorePath  ?? './data/ilink_store.json',
    ilinkPollTimeout:     opts.ilinkPollTimeout     ?? 40,
    tgToken:              opts.tgToken              ?? '',
    discordToken:         opts.discordToken         ?? '',
    feishuAppId:          opts.feishuAppId          ?? '',
    feishuAppSecret:      opts.feishuAppSecret      ?? '',
    engineCredentials:    opts.engineCredentials    ?? '',
  };
}

let _config: Config | null = null;

export function getConfig(): Config {
  if (!_config) _config = createConfig({});
  return _config;
}

export function setConfig(cfg: Config): void {
  _config = cfg;
}
