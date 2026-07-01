/**
 * 统一配置
 *
 * 所有配置均通过命令行参数传入（不依赖环境变量）。
 *
 * 引擎选择（--engine）：
 *   auto        → 自动：查询管理台已注册的内置引擎，按 ilink→wecom-aibot 优先级选用（默认）
 *   wecom-aibot → 企业微信智能机器人（走 HITL Server 的 wecom-aibot 内置引擎）
 *   ilink       → 微信 ClawBot/iLink（走 HITL Server 的 ilink 内置引擎）
 */

export type EngineType = 'auto' | 'wecom-aibot' | 'ilink';

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
}

export function createConfig(opts: Partial<Config>): Config {
  return {
    engine:               opts.engine               ?? 'auto',
    defaultRecipient:     opts.defaultRecipient     ?? '',
    defaultProjectName:   opts.defaultProjectName   ?? '',
    defaultTimeout:       opts.defaultTimeout       ?? 1200,
    botKey:               opts.botKey               ?? '',
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
