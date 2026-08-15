// hitl-approval.mjs — WeChat/HITL answerer for the dsh approval seam.
//
// Registers an 'approval/request' waterfall listener: when dsh needs a
// one-shot tool approval, the request is pushed to your phone (WeChat /
// WeCom via hitl-server) and the reply decides the outcome.
//
//   dsh approval seam                    hitl-server (:8081)        phone
//   ──────────────────                   ────────────────────        ─────
//   ctx.on('approval/request')  ──POST /api/send──▶  engine ──▶ WeChat msg
//          ▲                                                              │
//          └── outcome ◀─GET /api/poll/<id>◀─────────────────── user reply│
//
// Outcome mapping (dsh vocabulary is closed and fail-closed):
//   y/yes/同意/允许…   → 'allowed-once'
//   n/no/拒绝/取消…    → 'rejected'
//   no recognizable reply before timeout → 'unavailable'
//   request aborted mid-wait             → 'cancelled'
//
// Delivery failure (hitl-server down, engine not logged in, no activated
// recipient) calls next() to delegate to any later answerer (e.g. the web
// UI prompt) instead of claiming the request — this plugin owns a request
// only once it has actually reached a phone.
//
// Recipient routing: /api/send without chat_id falls back to the server's
// "most recently active recipient", which can point at a stale/unactivated
// user (observed: error 用户未激活). When no chatId is configured, the
// plugin resolves the picked engine's first activated user from
// /admin/api/engines and passes it explicitly.
//
// Load from a profile patch layer (cordis.patch.yml / --patch overlay):
//
//   - insert:
//       - id: hitl-approval
//         name: /Users/kong/.dsh/plugins/hitl-approval.mjs   # absolute path
//         config:
//           timeoutSec: 300
//
// Config (all optional; environment overrides from the launching shell):
//   serviceUrl     hitl-server base URL   (HITL_SERVER_URL, default http://127.0.0.1:8081)
//   botKey         engine routing key     (HITL_BOT_KEY, default: auto-pick ready engine)
//   chatId         explicit recipient     (patch config only — see note in apply)
//   apiKey         Bearer token for /api/* (HITL_API_KEY, default: none)
//   timeoutSec     wait for the human     (HITL_TIMEOUT_SECS, default 300)
//   pollIntervalMs poll cadence            (default 2000)
//   projectLabel   prefix shown on the phone (HITL_PROJECT_LABEL, default 'dsh')
//   debug          set env HITL_DEBUG=1 to trace delivery to stderr

const name = 'hitl-approval';

const REPLY_YES = /^(?:y|yes|yep|ok|okay|approve|allow|go|同意|允许|可以|好的?|是的|准了|批准|执行)(?:[。.!！\s]*)$/i;
const REPLY_NO = /^(?:n|no|nope|deny|reject|cancel|stop|拒绝|不允许|不行|不可以|不要|取消|驳回|停止)(?:[。.!！\s]*)$/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function apply(ctx, config = {}) {
  // Config layering: explicit patch config wins, then environment
  // (HITL_*) from the launching shell, then defaults. NOTE: chatId is
  // deliberately NOT read from the environment — a pre-existing
  // HITL_CHAT_ID in the shell (intended for another hitl deployment,
  // e.g. a wecom engine) silently misroutes this plugin's approvals to
  // an unactivated recipient. Set it in the patch config if needed;
  // otherwise the picked engine's activated user is used.
  const env = process.env;
  const cfg = {
    serviceUrl: config.serviceUrl ?? env.HITL_SERVER_URL ?? 'http://127.0.0.1:8081',
    botKey: config.botKey ?? env.HITL_BOT_KEY ?? '',
    chatId: config.chatId ?? '',
    apiKey: config.apiKey ?? env.HITL_API_KEY ?? '',
    timeoutSec: config.timeoutSec ?? Number(env.HITL_TIMEOUT_SECS ?? 300),
    pollIntervalMs: config.pollIntervalMs ?? 2000,
    projectLabel: config.projectLabel ?? env.HITL_PROJECT_LABEL ?? 'dsh',
  };

  const log = ctx.logger ?? console;

  // Optional tracing (HITL_DEBUG=1 → stderr). ctx.logger output is not
  // visible in headless stderr, so this is the debugging path for
  // delivery problems.
  const debug = process.env.HITL_DEBUG === '1';
  function trace(msg) {
    if (!debug) return;
    try { process.stderr.write(`[hitl-approval] ${msg}\n`); } catch { /* ignore */ }
  }

  /** fetch wrapper against hitl-server with optional bearer auth. */
  async function api(path, init = {}) {
    const headers = { 'Content-Type': 'application/json', ...(init.headers ?? {}) };
    if (cfg.apiKey) headers.Authorization = `Bearer ${cfg.apiKey}`;
    const res = await fetch(`${cfg.serviceUrl.replace(/\/$/, '')}${path}`, { ...init, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
    return res.json();
  }

  /**
   * Cached engine routing (botKey + activated recipient). The server
   * resolves an engine by bot_key, falling back to the `upstream` type —
   * with neither, /api/send fails with engine_not_started even though an
   * engine is logged in. When no botKey is configured, auto-pick from
   * /admin/api/engines using the same readiness priority the hitl MCP
   * client uses (ilink logged_in → wecom-aibot connected → telegram →
   * discord → feishu → any registered), and capture that engine's first
   * activated user as the explicit chat_id so /api/send never depends on
   * the server's "most recently active recipient" fallback.
   */
  let resolved = null;
  async function engineRoute() {
    if (cfg.botKey) return { botKey: cfg.botKey, activatedUser: '' };
    if (resolved !== null) return resolved;
    try {
      const data = await api('/admin/api/engines');
      const engines = Array.isArray(data?.engines) ? data.engines : [];
      const pick = (test) => engines.find((e) => test(e));
      const ready =
        pick((e) => e.worker_type === 'ilink' && e.logged_in === true) ??
        pick((e) => e.worker_type === 'wecom-aibot' && e.connected === true) ??
        pick((e) => e.worker_type === 'telegram' && e.running === true) ??
        pick((e) => e.worker_type === 'discord' && e.connected === true) ??
        pick((e) => e.worker_type === 'feishu' && e.connected === true) ??
        engines[0];
      const activated = Array.isArray(ready?.activated_users) ? ready.activated_users : [];
      resolved = ready
        ? { botKey: String(ready.bot_key ?? ''), activatedUser: String(activated[0]?.from_user_id ?? '') }
        : { botKey: '', activatedUser: '' };
    } catch {
      resolved = { botKey: '', activatedUser: '' };
    }
    return resolved;
  }

  ctx.on('approval/request', async (req, next) => {
    const tool = req?.toolName ?? 'unknown-tool';
    const reason = req?.reason ? `\n原因: ${req.reason}` : '';
    const message =
      `[${cfg.projectLabel}] 审批请求\n` +
      `工具: ${tool}${reason}\n` +
      `\n长按本消息引用回复：y = 允许一次 / n = 拒绝`;

    // 1) Deliver. Failure to deliver means we do NOT own the request —
    //    delegate to any later answerer (web UI) or the fail-closed fallback.
    let sessionId;
    try {
      const route = await engineRoute();
      trace(`engineRoute: ${JSON.stringify(route)}`);
      if (!route.botKey) {
        log.warn('[hitl-approval] no engine registered/logged in on hitl-server; delegating');
        return next();
      }
      const chatId = cfg.chatId || route.activatedUser || '';
      const sendBody = {
          message,
          chat_id: chatId || undefined,
          wait_reply: true,
          timeout: cfg.timeoutSec,
          bot_key: route.botKey,
          project_name: cfg.projectLabel,
      };
      trace(`send body: ${JSON.stringify(sendBody)}`);
      const sent = await api('/api/send', {
        method: 'POST',
        body: JSON.stringify(sendBody),
      });
      trace(`send response: ${JSON.stringify(sent).slice(0, 200)}`);
      if (!sent?.success || !sent?.session_id) {
        log.warn(`[hitl-approval] deliver failed (${sent?.error ?? 'no session'}); delegating`);
        return next();
      }
      sessionId = sent.session_id;
      log.info(`[hitl-approval] asked ${tool} → ${chatId || 'default recipient'} (session ${sessionId})`);
    } catch (e) {
      trace(`send threw: ${e.message}`);
      log.warn(`[hitl-approval] hitl-server unreachable (${e.message}); delegating`);
      return next();
    }

    // 2) Wait for a recognizable human reply. Unrecognized replies are
    //    treated as noise and polling continues; timeout fails closed.
    const deadline = Date.now() + cfg.timeoutSec * 1000;
    while (Date.now() < deadline) {
      if (req?.signal?.aborted) {
        try { await api(`/api/session/${sessionId}/timeout`, { method: 'POST' }); } catch { /* best effort */ }
        return 'cancelled';
      }
      try {
        const p = await api(`/api/poll/${sessionId}`);
        if (p?.has_reply) {
          const first = (p.replies ?? [])[0] ?? {};
          const text = String(first.content ?? first.text ?? '').trim();
          if (REPLY_YES.test(text)) {
            log.info(`[hitl-approval] ${tool} → allowed-once ("${text}")`);
            return 'allowed-once';
          }
          if (REPLY_NO.test(text)) {
            log.info(`[hitl-approval] ${tool} → rejected ("${text}")`);
            return 'rejected';
          }
          log.info(`[hitl-approval] unrecognized reply "${text}" — still waiting`);
        } else if (p?.status === 'not_found') {
          log.warn(`[hitl-approval] session ${sessionId} expired`);
          return 'unavailable';
        }
      } catch { /* transient poll error — retry */ }
      await sleep(cfg.pollIntervalMs);
    }

    try { await api(`/api/session/${sessionId}/timeout`, { method: 'POST' }); } catch { /* best effort */ }
    log.warn(`[hitl-approval] ${tool} → unavailable (timed out after ${cfg.timeoutSec}s)`);
    return 'unavailable';
  });
}

export { apply, name };
