/**
 * 统一配置
 *
 * 所有配置均通过命令行参数传入（不依赖环境变量）。
 *
 * 引擎选择（--engine）：
 *   hil         → 对接 HIL Server（原有行为，默认）
 *   wecom-aibot → 企业微信智能机器人（直连，无需 HIL Server）
 *   ilink       → 微信 ClawBot/iLink（直连，无需 HIL Server）
 */

export type EngineType = 'hil' | 'wecom-aibot' | 'ilink';

export interface Config {
  engine: EngineType;

  // ── 通用 ────────────────────────────────────────────────────────────────────
  /** 默认收件人：chatid（hil/wecom-aibot）；ilink 引擎自动推断，通常无需设置 */
  defaultRecipient: string;
  defaultProjectName: string;
  /** 等待回复超时（秒） */
  defaultTimeout: number;

  // ── HIL Server 引擎 ─────────────────────────────────────────────────────────
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
    engine:               opts.engine               ?? 'hil',
    defaultRecipient:     opts.defaultRecipient     ?? '',
    defaultProjectName:   opts.defaultProjectName   ?? '',
    defaultTimeout:       opts.defaultTimeout       ?? 1200,
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
