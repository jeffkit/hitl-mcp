/**
 * `hitl-mcp ilink-setup` — iLink 一键安装 + 服务化（macOS launchd，单进程模式）
 *
 * 架构：iLink 长连接作为 HITL Server 的内置引擎跑在同一个进程内，
 * 不再需要独立的 ilink-worker 进程。因此只需服务化 HITL Server 一个进程。
 *
 * 流程：
 *   1. 确保 hitl-server venv 与依赖（httpx 等内置引擎所需）
 *   2. 停掉旧的服务：unload 现有 HITL Server / ilink-worker plist，kill 占用 :8081 的手动进程
 *   3. 生成 HITL Server 的 launchd plist（带 ENABLE_ILINK_ENGINE 等环境变量），load
 *   4. 等 HITL Server 起来 + 内置 ilink 引擎就绪
 *   5. 若未登录：拉二维码引导扫码
 *   6. 打印一段可直接粘贴进 Cursor 的 MCP 配置
 *
 * 设计取舍：
 *   - 全参数可命令行传入，不做交互式 readline（Agent 跑时 stdin 不可交互）。
 *   - hitl-server 用 venv 内 python 的绝对路径写进 plist，不依赖 shell PATH。
 *   - 仅支持 macOS（launchd 专属）。
 */
import { spawnSync } from 'child_process';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'fs';
import { homedir, platform } from 'os';
import { dirname, join, resolve } from 'path';

// ── 路径常量 ──────────────────────────────────────────────────────────────

const HITL_DIR = process.env.HITL_HOME || join(homedir(), '.hitl');
const LOG_DIR = join(HITL_DIR, 'logs');
const LAUNCH_AGENT_DIR = join(homedir(), 'Library', 'LaunchAgents');

const HITL_SERVER_LABEL = 'com.woa.hitl-mcp.hitl-server';
const HITL_SERVER_PLIST = join(LAUNCH_AGENT_DIR, `${HITL_SERVER_LABEL}.plist`);
// 旧名 plist（改名前），重装时一并卸载，避免端口被旧服务占用
const LEGACY_HITL_SERVER_PLIST = join(LAUNCH_AGENT_DIR, 'com.woa.hitl-mcp.hil-server.plist');
const LEGACY_WORKER_PLIST = join(LAUNCH_AGENT_DIR, 'com.woa.hitl-mcp.ilink-worker.plist');

/** monorepo 根：从本文件向上回溯 4 层（src -> mcp-server-ts -> packages -> hil-mcp） */
const REPO_ROOT = resolve(dirname(new URL(import.meta.url).pathname), '..', '..', '..');
const HITL_SERVER_DIR = join(REPO_ROOT, 'packages', 'hitl-server');
const HITL_SERVER_VENV_PY = join(HITL_SERVER_DIR, '.venv', 'bin', 'python');

// ── 小工具 ────────────────────────────────────────────────────────────────

function log(msg: string): void {
  console.error(`[setup] ${msg}`);
}

function run(cmd: string, args: string[], opts: { cwd?: string; env?: Record<string, string> } = {}): { ok: boolean; stdout: string; stderr: string; code: number | null } {
  const r = spawnSync(cmd, args, { cwd: opts.cwd, env: { ...process.env, ...opts.env }, encoding: 'utf-8' });
  return { ok: r.status === 0, stdout: r.stdout ?? '', stderr: r.stderr ?? '', code: r.status };
}

function hasCmd(cmd: string): boolean {
  return run('which', [cmd]).ok;
}

async function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}

async function httpGet(url: string, timeoutMs = 5000): Promise<Record<string, any> | null> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) return null;
    return (await res.json()) as Record<string, any>;
  } catch {
    return null;
  }
}

/** 找到占用 :8081 LISTEN 的进程 PID（本机手动起的 HITL Server），返回 PID 或 null */
function pidListeningOn(port: number): number | null {
  const r = run('lsof', ['-nP', '-iTCP:' + port, '-sTCP:LISTEN', '-t']);
  if (!r.ok) return null;
  const pid = parseInt(r.stdout.trim().split('\n')[0], 10);
  return Number.isFinite(pid) && pid > 0 ? pid : null;
}

// ── plist 生成 ────────────────────────────────────────────────────────────

function buildHitlServerPlist(args: {
  pythonPath: string;
  workingDir: string;
  port: string;
  env: Record<string, string>;
  logDir: string;
}): string {
  const envEntries = Object.entries(args.env)
    .map(([k, v]) => `      <key>${k}</key><string>${v}</string>`)
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${HITL_SERVER_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${args.pythonPath}</string>
    <string>-m</string>
    <string>hitl_server.app</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${args.workingDir}</string>
  <key>EnvironmentVariables</key>
  <dict>
      <key>HITL_PORT</key><string>${args.port}</string>
${envEntries}
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${args.logDir}/hitl-server.out.log</string>
  <key>StandardErrorPath</key>
  <string>${args.logDir}/hitl-server.err.log</string>
</dict>
</plist>
`;
}

// ── 核心步骤 ──────────────────────────────────────────────────────────────

/** 确保 hitl-server venv 与依赖（内置引擎需要 httpx；qrcode 可选） */
function ensureHitlServerVenv(): string {
  if (!existsSync(HITL_SERVER_DIR)) {
    throw new Error(`找不到 hitl-server 包目录: ${HITL_SERVER_DIR}\n请确认在 hil-mcp monorepo 内运行。`);
  }
  if (!existsSync(HITL_SERVER_VENV_PY)) {
    if (!hasCmd('uv')) {
      throw new Error(
        `hitl-server venv 缺失，且 PATH 中没有 uv。\n` +
        `请先安装 uv:  curl -LsSf https://astral.sh/uv/install.sh | sh\n然后重跑本命令。`
      );
    }
    log('建立 hitl-server venv...');
    const r = run('uv', ['sync'], { cwd: HITL_SERVER_DIR });
    if (!r.ok) throw new Error(`hitl-server uv sync 失败: ${r.stderr}`);
  }
  // 确保 httpx 可用（内置 ilink 引擎依赖；hitl-server 主依赖未必含 httpx）
  const probe = run(HITL_SERVER_VENV_PY, ['-c', 'import httpx'], { cwd: HITL_SERVER_DIR });
  if (!probe.ok) {
    log('venv 缺 httpx，安装中...');
    const r = run(HITL_SERVER_VENV_PY, ['-m', 'pip', 'install', 'httpx'], { cwd: HITL_SERVER_DIR });
    if (!r.ok) throw new Error(`安装 httpx 失败: ${r.stderr}`);
  }
  log(`hitl-server venv 就绪: ${HITL_SERVER_VENV_PY}`);
  return HITL_SERVER_VENV_PY;
}

/** 停掉旧的服务：unload 旧 plist + kill 占用端口的手动进程 */
function stopExistingServices(port: number): void {
  // 卸载旧的单进程 HITL Server plist（如有）
  if (existsSync(HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', HITL_SERVER_PLIST]);
    log('已卸载旧 HITL Server plist');
  }
  // 卸载改名前的旧 label plist（com.woa.hitl-mcp.hil-server）
  if (existsSync(LEGACY_HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', LEGACY_HITL_SERVER_PLIST]);
    rmSync(LEGACY_HITL_SERVER_PLIST);
    log('已卸载改名前的旧 plist（hil-server）');
  }
  // 卸载遗留的独立 ilink-worker plist（切换到内置引擎后不再需要）
  if (existsSync(LEGACY_WORKER_PLIST)) {
    run('launchctl', ['unload', LEGACY_WORKER_PLIST]);
    rmSync(LEGACY_WORKER_PLIST);
    log('已卸载遗留的独立 ilink-worker plist（改用内置引擎）');
  }
  // kill 占用端口的手动进程（非 launchd 管理的）
  const pid = pidListeningOn(port);
  if (pid) {
    log(`检测到端口 ${port} 被手动进程 PID=${pid} 占用，停掉它以腾出版本...`);
    run('kill', [String(pid)]);
  }
}

/** 写 HITL Server plist 并 load */
function installHitlServer(pythonPath: string, env: Record<string, string>, port: string): void {
  if (!existsSync(LAUNCH_AGENT_DIR)) mkdirSync(LAUNCH_AGENT_DIR, { recursive: true });
  const plist = buildHitlServerPlist({
    pythonPath,
    workingDir: HITL_SERVER_DIR,
    port,
    env,
    logDir: LOG_DIR,
  });
  writeFileSync(HITL_SERVER_PLIST, plist);
  log(`已写入 plist: ${HITL_SERVER_PLIST}`);
  const load = run('launchctl', ['load', HITL_SERVER_PLIST]);
  if (!load.ok) throw new Error(`launchctl load 失败: ${load.stderr}`);
  log('HITL Server 已加载（开机自启 + 崩溃自动重启 + 内置 iLink 引擎）');
}

/** 等 HITL Server 起来且 ilink 引擎就绪（login_status 可达即可） */
async function waitReady(serviceUrl: string, botKey: string): Promise<void> {
  const base = serviceUrl.replace(/\/$/, '');
  const url = `${base}/api/ilink/login_status?bot_key=${encodeURIComponent(botKey)}`;
  for (let i = 0; i < 40; i++) {
    const r = await httpGet(url, 3000);
    if (r !== null && r.status !== 'error') {
      log(`HITL Server 就绪，内置 ilink 引擎 login_status=${r.status}`);
      return;
    }
    await sleep(1000);
  }
  throw new Error(
    `HITL Server 未在 40s 内就绪。\n查看日志: tail -f ${join(LOG_DIR, 'hitl-server.err.log')}`
  );
}

/** 若未登录，拉二维码引导扫码 */
async function ensureLogin(serviceUrl: string, botKey: string): Promise<void> {
  const base = serviceUrl.replace(/\/$/, '');
  const statusUrl = `${base}/api/ilink/login_status?bot_key=${encodeURIComponent(botKey)}`;
  const qrUrl = `${base}/api/ilink/qr?bot_key=${encodeURIComponent(botKey)}`;

  const status = (await httpGet(statusUrl))?.status;
  if (status === 'success') {
    log('已登录，无需扫码。');
    return;
  }

  log('未登录，申请二维码...');
  const qr = await httpGet(qrUrl, 20000);
  if (!qr || qr.status === 'error') {
    throw new Error(`获取二维码失败: ${qr?.error ?? '未知'}`);
  }
  if (qr.status === 'success') {
    log('已登录（刚完成）。');
    return;
  }
  console.error('\n========================================');
  console.error('请用手机微信扫码登录（打开链接或扫二维码）:');
  console.error(`  ${qr.qr_url ?? '(未获取到链接)'}`);
  console.error('========================================\n');
  if (qr.qr_base64) {
    const qrFile = join(LOG_DIR, 'ilink-login-qr.png');
    writeFileSync(qrFile, Buffer.from(qr.qr_base64, 'base64'));
    console.error(`二维码图片已存: ${qrFile}\n`);
  }

  log('等待扫码确认（最长 5 分钟）...在微信确认后即完成。');
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2000);
    const r = await httpGet(statusUrl);
    if (r?.status === 'success') {
      log('✅ 扫码登录成功！');
      return;
    }
    if (r?.status === 'expired' || r?.status === 'not_started') {
      throw new Error('二维码已过期，请重跑本命令获取新二维码。');
    }
  }
  throw new Error('等待扫码超时（5 分钟内未确认）。');
}

/** 打印可粘贴进 Cursor 的 MCP 配置 */
function printCursorConfig(args: { serviceUrl: string; botKey: string; projectName?: string }): void {
  const cfg = {
    'mcpServers': {
      'hitl-mcp-ilink': {
        command: 'npx',
        args: [
          '-y',
          'hitl-mcp',
          '--engine', 'ilink',
          '--service-url', args.serviceUrl,
          '--bot-key', args.botKey,
          ...(args.projectName ? ['--project-name', args.projectName] : []),
        ],
      },
    },
  };
  console.error('\n✅ 安装完成。把下面这段粘贴进 Cursor 的 MCP 配置（Settings → MCP）:\n');
  console.log(JSON.stringify(cfg, null, 2));
  console.error('\n日志: ' + LOG_DIR);
  console.error('卸载: npx hitl-mcp ilink-setup --uninstall\n');
}

/** 卸载：unload HITL Server plist + 删文件（凭证保留） */
function uninstallAll(): void {
  if (existsSync(HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', HITL_SERVER_PLIST]);
    rmSync(HITL_SERVER_PLIST);
    log('已卸载 HITL Server launchd 服务');
  } else {
    log('未找到 HITL Server plist，无需卸载');
  }
  if (existsSync(LEGACY_WORKER_PLIST)) {
    run('launchctl', ['unload', LEGACY_WORKER_PLIST]);
    rmSync(LEGACY_WORKER_PLIST);
    log('已清理遗留的独立 ilink-worker plist');
  }
  if (existsSync(LEGACY_HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', LEGACY_HITL_SERVER_PLIST]);
    rmSync(LEGACY_HITL_SERVER_PLIST);
    log('已清理改名前的旧 plist（hil-server）');
  }
  log('注意：凭证文件未删除（' + HITL_DIR + '），如需彻底清理请手动 rm -rf ~/.hitl');
}

// ── 入口 ──────────────────────────────────────────────────────────────────

export interface SetupOptions {
  ilinkBaseUrl: string;
  botKey: string;
  serviceUrl: string;
  tokenStorePath: string;
  projectName?: string;
  uninstall: boolean;
  // 企微 AI Bot 内置引擎（可选，与 iLink 共进程）
  enableWecomAibot: boolean;
  wecomBotId: string;
  wecomBotSecret: string;
  wecomBotKey: string;
}

export async function runSetup(opts: SetupOptions): Promise<void> {
  if (platform() !== 'darwin') {
    throw new Error('ilink-setup 目前仅支持 macOS（依赖 launchd）。Linux 请用 systemd 自行管理。');
  }

  if (opts.uninstall) {
    uninstallAll();
    return;
  }

  // 一次性迁移：旧目录 ~/.hil-mcp → ~/.hitl（保留凭证与日志）
  const legacyDir = join(homedir(), '.hil-mcp');
  if (existsSync(legacyDir) && !existsSync(join(HITL_DIR, '.migrated'))) {
    log(`检测到旧数据目录 ${legacyDir}，迁移到 ${HITL_DIR}...`);
    run('cp', ['-R', `${legacyDir}/.`, `${HITL_DIR}/`]);
    writeFileSync(join(HITL_DIR, '.migrated'), new Date().toISOString());
    log('迁移完成（旧目录保留，可手动删除: rm -rf ~/.hil-mcp）');
  }

  mkdirSync(HITL_DIR, { recursive: true });
  mkdirSync(LOG_DIR, { recursive: true });

  const port = (() => {
    try { return String(new URL(opts.serviceUrl).port || '8081'); }
    catch { return '8081'; }
  })();

  // 1. venv + 依赖
  const pythonPath = ensureHitlServerVenv();

  // 2. 停旧服务
  stopExistingServices(parseInt(port, 10));
  await sleep(2000);

  // 3. 安装 HITL Server（内置 ilink 引擎，可选 wecom-aibot）
  const env: Record<string, string> = {
    ENABLE_ILINK_ENGINE: 'true',
    ILINK_BOT_KEY: opts.botKey,
    ILINK_BASE_URL: opts.ilinkBaseUrl,
    ILINK_TOKEN_STORE_PATH: opts.tokenStorePath,
    PATH: `/usr/local/bin:/usr/bin:/bin:${homedir()}/.local/bin`,
  };
  if (opts.enableWecomAibot) {
    if (!opts.wecomBotId || !opts.wecomBotSecret) {
      throw new Error('启用 wecom-aibot 需要 --wecom-bot-id 和 --wecom-bot-secret');
    }
    env.ENABLE_WECOM_AIBOT_ENGINE = 'true';
    env.WECOM_AIBOT_BOT_KEY = opts.wecomBotKey;
    env.WECOM_AIBOT_BOT_ID = opts.wecomBotId;
    env.WECOM_AIBOT_BOT_SECRET = opts.wecomBotSecret;
  }
  installHitlServer(pythonPath, env, port);

  // 4. 等就绪
  await waitReady(opts.serviceUrl, opts.botKey);

  // 5. 扫码登录
  await ensureLogin(opts.serviceUrl, opts.botKey);

  // 6. 打印 Cursor 配置
  printCursorConfig({ serviceUrl: opts.serviceUrl, botKey: opts.botKey, projectName: opts.projectName });
}
