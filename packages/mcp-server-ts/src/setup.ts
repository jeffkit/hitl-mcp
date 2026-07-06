/**
 * `hitl-mcp ilink-setup` — HITL Server 一键安装 + 服务化
 *
 * 设计原则：CLI 只做「看不见」的事，「看得见」的步骤（扫码、激活、复制配置）
 * 全部在管理台浏览器 UI 里完成。
 *
 * 支持的平台：
 *   - macOS：launchd LaunchAgents（~/.hitl-server/...plist）
 *   - Linux：systemd --user service（~/.config/systemd/user/...service）
 *
 * CLI 流程（全部无交互，零必填参数）：
 *   1. 检查/安装 hitl-server venv（uv sync）
 *   2. 写服务文件并启动（launchd / systemd）
 *   3. 等 HITL Server HTTP 就绪
 *   4. 打开管理台浏览器（open / xdg-open）
 *      → 管理台引导：启动引擎 → 扫码 → 激活 → 复制 Cursor 配置
 */
import { spawnSync } from 'child_process';
import { existsSync, mkdirSync, writeFileSync, rmSync } from 'fs';
import { homedir, platform } from 'os';
import { dirname, join, resolve } from 'path';

// ── 路径常量 ──────────────────────────────────────────────────────────────

const HITL_DIR = process.env.HITL_HOME || join(homedir(), '.hitl');
const LOG_DIR = join(HITL_DIR, 'logs');

// macOS launchd
const LAUNCH_AGENT_DIR = join(homedir(), 'Library', 'LaunchAgents');
const HITL_SERVER_LABEL = 'com.woa.hitl-mcp.hitl-server';
const HITL_SERVER_PLIST = join(LAUNCH_AGENT_DIR, `${HITL_SERVER_LABEL}.plist`);
const LEGACY_HITL_SERVER_PLIST = join(LAUNCH_AGENT_DIR, 'com.woa.hitl-mcp.hil-server.plist');
const LEGACY_WORKER_PLIST = join(LAUNCH_AGENT_DIR, 'com.woa.hitl-mcp.ilink-worker.plist');

// Linux systemd --user
const SYSTEMD_USER_DIR = join(homedir(), '.config', 'systemd', 'user');
const HITL_SERVER_SERVICE_NAME = 'hitl-mcp-server.service';
const HITL_SERVER_SERVICE_PATH = join(SYSTEMD_USER_DIR, HITL_SERVER_SERVICE_NAME);

/** monorepo 根：从本文件向上回溯 4 层（src -> mcp-server-ts -> packages -> hil-mcp） */
const REPO_ROOT = resolve(dirname(new URL(import.meta.url).pathname), '..', '..', '..');
const HITL_SERVER_DIR = join(REPO_ROOT, 'packages', 'hitl-server');
const HITL_SERVER_VENV_PY = join(HITL_SERVER_DIR, '.venv', 'bin', 'python');

// ── 小工具 ────────────────────────────────────────────────────────────────

function log(msg: string): void {
  console.error(`[setup] ${msg}`);
}

function step(n: number, total: number, msg: string): void {
  console.error(`\n[${n}/${total}] ${msg}`);
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

// ── 服务文件生成 ──────────────────────────────────────────────────────────

interface ServiceArgs {
  pythonPath: string;
  workingDir: string;
  port: string;
  tokenStorePath: string;
  logDir: string;
}

function buildHitlServerPlist(args: ServiceArgs): string {
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
      <key>ILINK_TOKEN_STORE_PATH</key><string>${args.tokenStorePath}</string>
      <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:${homedir()}/.local/bin</string>
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

function buildHitlServerSystemdUnit(args: ServiceArgs): string {
  return `[Unit]
Description=HITL MCP Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${args.workingDir}
ExecStart=${args.pythonPath} -m hitl_server.app
Restart=always
Environment="HITL_PORT=${args.port}"
Environment="ILINK_TOKEN_STORE_PATH=${args.tokenStorePath}"
StandardOutput=append:${args.logDir}/hitl-server.out.log
StandardError=append:${args.logDir}/hitl-server.err.log

[Install]
WantedBy=default.target
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

// ── macOS launchd ─────────────────────────────────────────────────────────

function stopExistingServicesMac(port: number): void {
  if (existsSync(HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', HITL_SERVER_PLIST]);
    log('已卸载旧 HITL Server plist');
  }
  if (existsSync(LEGACY_HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', LEGACY_HITL_SERVER_PLIST]);
    rmSync(LEGACY_HITL_SERVER_PLIST);
    log('已卸载改名前的旧 plist（hil-server）');
  }
  if (existsSync(LEGACY_WORKER_PLIST)) {
    run('launchctl', ['unload', LEGACY_WORKER_PLIST]);
    rmSync(LEGACY_WORKER_PLIST);
    log('已清理遗留 ilink-worker plist');
  }
  const pid = pidListeningOn(port);
  if (pid) {
    log(`端口 ${port} 被手动进程 PID=${pid} 占用，停掉...`);
    run('kill', [String(pid)]);
  }
}

function installHitlServerMac(args: ServiceArgs): void {
  mkdirSync(LAUNCH_AGENT_DIR, { recursive: true });
  writeFileSync(HITL_SERVER_PLIST, buildHitlServerPlist(args));
  log(`已写入 plist: ${HITL_SERVER_PLIST}`);
  const r = run('launchctl', ['load', HITL_SERVER_PLIST]);
  if (!r.ok) throw new Error(`launchctl load 失败: ${r.stderr}`);
  log('HITL Server 已加载（开机自启 + 崩溃自动重启）');
}

function uninstallMac(): void {
  if (existsSync(HITL_SERVER_PLIST)) {
    run('launchctl', ['unload', HITL_SERVER_PLIST]);
    rmSync(HITL_SERVER_PLIST);
    log('已卸载 HITL Server launchd 服务');
  } else {
    log('未找到 HITL Server plist，无需卸载');
  }
  for (const p of [LEGACY_WORKER_PLIST, LEGACY_HITL_SERVER_PLIST]) {
    if (existsSync(p)) {
      run('launchctl', ['unload', p]);
      rmSync(p);
      log(`已清理旧 plist: ${p}`);
    }
  }
}

// ── Linux systemd --user ──────────────────────────────────────────────────

function stopExistingServicesLinux(port: number): void {
  if (existsSync(HITL_SERVER_SERVICE_PATH)) {
    run('systemctl', ['--user', 'stop', HITL_SERVER_SERVICE_NAME]);
    log('已停止旧 HITL Server systemd 服务');
  }
  const pid = pidListeningOn(port);
  if (pid) {
    log(`端口 ${port} 被手动进程 PID=${pid} 占用，停掉...`);
    run('kill', [String(pid)]);
  }
}

function installHitlServerLinux(args: ServiceArgs): void {
  mkdirSync(SYSTEMD_USER_DIR, { recursive: true });
  writeFileSync(HITL_SERVER_SERVICE_PATH, buildHitlServerSystemdUnit(args));
  log(`已写入 service: ${HITL_SERVER_SERVICE_PATH}`);
  run('systemctl', ['--user', 'daemon-reload']);
  run('systemctl', ['--user', 'enable', HITL_SERVER_SERVICE_NAME]);
  const r = run('systemctl', ['--user', 'start', HITL_SERVER_SERVICE_NAME]);
  if (!r.ok) throw new Error(`systemctl start 失败: ${r.stderr}`);
  log('HITL Server 已启动（开机自启 + 崩溃自动重启）');
}

function uninstallLinux(): void {
  if (existsSync(HITL_SERVER_SERVICE_PATH)) {
    run('systemctl', ['--user', 'stop', HITL_SERVER_SERVICE_NAME]);
    run('systemctl', ['--user', 'disable', HITL_SERVER_SERVICE_NAME]);
    rmSync(HITL_SERVER_SERVICE_PATH);
    run('systemctl', ['--user', 'daemon-reload']);
    log('已卸载 HITL Server systemd user service');
  } else {
    log('未找到 systemd user service，无需卸载');
  }
}

// ── 通用等待 ──────────────────────────────────────────────────────────────

/** 等 HITL Server HTTP 就绪（管理台 API 可达即可，不依赖 iLink 引擎状态） */
async function waitReady(serviceUrl: string): Promise<void> {
  const base = serviceUrl.replace(/\/$/, '');
  const url = `${base}/admin/api/engines`;
  for (let i = 0; i < 40; i++) {
    const r = await httpGet(url, 3000);
    if (r !== null) {
      log('HITL Server 就绪');
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

/** 等待第一个用户给 bot 发消息（激活收件人），返回 from_user_id */
async function waitActivation(serviceUrl: string, botKey: string): Promise<string> {
  const base = serviceUrl.replace(/\/$/, '');
  const url = `${base}/api/ilink/login_status?bot_key=${encodeURIComponent(botKey)}`;
  console.error('  → 现在用手机微信给 bot 发一条任意消息（例如"hi"），激活收件人后无需填 chat-id。');
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2000);
    const r = await httpGet(url, 5000);
    const users = (r?.activated_users as Array<{ from_user_id: string }>) ?? [];
    if (users.length > 0) {
      log(`✅ 已激活！收件人: ${users[0].from_user_id}`);
      return users[0].from_user_id;
    }
  }
  throw new Error('等待激活超时（10 分钟内未收到用户消息）。请确保已扫码登录，然后在微信里给 bot 发一条消息后重试。');
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

function uninstallAll(): void {
  const plat = platform();
  if (plat === 'darwin') {
    uninstallMac();
  } else if (plat === 'linux') {
    uninstallLinux();
  }
  log(`凭证文件未删除（${HITL_DIR}），如需彻底清理请手动 rm -rf ~/.hitl`);
}

// ── 入口 ──────────────────────────────────────────────────────────────────

export interface SetupOptions {
  serviceUrl: string;
  tokenStorePath: string;
  uninstall: boolean;
}

export async function runSetup(opts: SetupOptions): Promise<void> {
  const plat = platform();
  if (plat !== 'darwin' && plat !== 'linux') {
    throw new Error('ilink-setup 目前支持 macOS 和 Linux。Windows 请手动管理进程。');
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

  const serviceArgs: ServiceArgs = {
    pythonPath: '',      // 步骤 1 填充
    workingDir: HITL_SERVER_DIR,
    port,
    tokenStorePath: opts.tokenStorePath,
    logDir: LOG_DIR,
  };

  const TOTAL_STEPS = 4;

  // 1. venv + 依赖
  step(1, TOTAL_STEPS, '检查 hitl-server 环境...');
  serviceArgs.pythonPath = ensureHitlServerVenv();

  // 2. 停旧服务 + 写服务文件 + 启动
  const svcLabel = plat === 'darwin' ? 'launchd' : 'systemd --user';
  step(2, TOTAL_STEPS, `启动 HITL Server（${svcLabel} 服务化）...`);
  if (plat === 'darwin') {
    stopExistingServicesMac(parseInt(port, 10));
    await sleep(2000);
    installHitlServerMac(serviceArgs);
  } else {
    stopExistingServicesLinux(parseInt(port, 10));
    await sleep(1000);
    installHitlServerLinux(serviceArgs);
  }

  // 3. 等 HITL Server HTTP 就绪
  step(3, TOTAL_STEPS, '等待 HITL Server 启动...');
  await waitReady(opts.serviceUrl);

  // 4. 打开管理台（引导扫码、激活、复制配置）
  step(4, TOTAL_STEPS, '打开管理台...');
  const consoleUrl = opts.serviceUrl.replace(/\/$/, '') + '/admin';
  const opener = plat === 'darwin' ? 'open' : 'xdg-open';
  run(opener, [consoleUrl]);
  log(`管理台已打开: ${consoleUrl}`);

  console.error('\n========================================');
  console.error('✅ 后台服务已就绪！接下来在浏览器管理台里：');
  console.error('  1. 点击「启动引擎」');
  console.error('  2. 扫码登录微信（二维码自动显示）');
  console.error('  3. 用微信给 bot 发一条消息激活收件人');
  console.error('  4. 管理台展示 Cursor MCP 配置 → 一键复制');
  console.error('========================================\n');
  console.error(`管理台: ${consoleUrl}`);
  console.error(`日志:   ${LOG_DIR}`);
  console.error('卸载:   npx hitl-mcp ilink-setup --uninstall\n');
}
