import { useEffect, useState, useRef, useCallback } from 'react'
import {
  QrCode,
  Plug,
  Power,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Loader2,
  Smartphone,
  MessageSquare,
  Send,
  RadioTower,
  ArrowRight,
  CircleDot,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import {
  engineApi,
  type EngineStatus,
  type IlinkQrResponse,
} from '@/api/client'

function StatusBadge({ on, onText = '运行中', offText = '未运行' }: { on: boolean; onText?: string; offText?: string }) {
  return on ? (
    <Badge className="bg-green-500/10 text-green-600 border-green-500/20 hover:bg-green-500/10">
      <CheckCircle2 className="w-3 h-3 mr-1" /> {onText}
    </Badge>
  ) : (
    <Badge variant="secondary">
      <XCircle className="w-3 h-3 mr-1" /> {offText}
    </Badge>
  )
}

// ── 引擎状态引导 ──────────────────────────────────────────────────────────────
// 每个引擎按当前状态归入一个 step，配以颜色、动画、明确的“下一步”指引。

type Tone = 'idle' | 'connecting' | 'waiting' | 'ready'

interface Step {
  index: number          // ①②③④
  tone: Tone
  title: string          // 状态标题
  hint: string           // 下一步动作描述
  glow?: 'amber' | 'blue' // 需要用户操作时给卡片加流光
}

const TONE_STYLES: Record<Tone, { bg: string; ring: string; text: string; dot: string; icon: typeof Send }> = {
  idle:       { bg: 'bg-zinc-500/10',  ring: 'border-zinc-500/20',  text: 'text-zinc-300',  dot: '',                 icon: CircleDot },
  connecting: { bg: 'bg-blue-500/10',  ring: 'border-blue-500/25',  text: 'text-blue-300',  dot: 'hitl-pulse-blue',  icon: RadioTower },
  waiting:    { bg: 'bg-amber-500/10', ring: 'border-amber-500/25', text: 'text-amber-200', dot: 'hitl-breath-dot',  icon: Send },
  ready:      { bg: 'bg-green-500/10', ring: 'border-green-500/25', text: 'text-green-300', dot: '',                 icon: CheckCircle2 },
}

function StepBanner({ step }: { step: Step }) {
  const s = TONE_STYLES[step.tone]
  const Icon = s.icon
  const animated = step.tone === 'connecting' || step.tone === 'waiting'
  return (
    <div className={`flex items-start gap-3 rounded-lg border ${s.ring} ${s.bg} px-4 py-3`}>
      <div className="relative flex h-5 w-5 shrink-0 items-center justify-center mt-0.5">
        {animated ? (
          <span className={`h-2.5 w-2.5 rounded-full ${s.dot} ${step.tone === 'waiting' ? 'bg-amber-400' : 'bg-blue-400'}`} />
        ) : (
          <Icon className={`h-5 w-5 ${s.text}`} />
        )}
      </div>
      <div className="min-w-0">
        <div className={`text-sm font-medium ${s.text}`}>
          <span className="mr-1.5 opacity-60">步骤 {step.index}</span>
          {step.title}
        </div>
        <div className={`text-xs mt-0.5 ${animated ? 'hitl-text-soft ' + s.text : 'text-muted-foreground'}`}>
          {step.hint}
        </div>
      </div>
    </div>
  )
}

// iLink 状态机
function computeIlinkStep(ilink?: EngineStatus): Step {
  if (!ilink || !ilink.running) {
    return { index: 1, tone: 'idle', title: '启动引擎', hint: '点击下方「启动引擎」，开始维持微信长轮询。' }
  }
  if (!ilink.logged_in) {
    return { index: 2, tone: 'connecting', title: '扫码登录微信', hint: '点击「显示二维码登录」，用个人微信扫码完成登录。', glow: 'blue' }
  }
  const hasUsers = (ilink.activated_users?.length ?? 0) > 0
  if (!hasUsers) {
    return {
      index: 3,
      tone: 'waiting',
      title: '等待你在微信给 bot 发一条消息',
      hint: '在微信里向 bot 发任意一条消息以激活收件人；激活后即可在 Cursor 中使用，无需填 chat-id。',
      glow: 'amber',
    }
  }
  return { index: 4, tone: 'ready', title: '就绪，可在 Cursor 中使用', hint: 'iLink 通道已就绪，收件人已激活。' }
}

// WeCom AI Bot 状态机
function computeWecomStep(wecom?: EngineStatus): Step {
  if (!wecom || !wecom.running) {
    return { index: 1, tone: 'idle', title: '填写凭证并启动', hint: '填写 Bot ID / Bot Secret，点击「启动引擎」。' }
  }
  if (!wecom.connected) {
    return { index: 2, tone: 'connecting', title: '正在连接企业微信…', hint: '引擎正在建立 WebSocket 长连接并订阅，稍候即自动就绪。', glow: 'blue' }
  }
  const hasRecipients = (wecom.known_recipients?.length ?? 0) > 0
  if (!hasRecipients) {
    return {
      index: 3,
      tone: 'waiting',
      title: '等待你在企业微信给 bot 发一条消息',
      hint: '在企业微信里单聊私聊 bot（或在群里 @bot）发任意一条消息以激活收件人；激活后即可在 Cursor 中使用。',
      glow: 'amber',
    }
  }
  return { index: 4, tone: 'ready', title: '就绪，可在 Cursor 中使用', hint: '企业微信 AI Bot 通道已就绪，收件人已激活。' }
}

export function EnginesPage() {
  const [engines, setEngines] = useState<EngineStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // iLink 二维码
  const [qrOpen, setQrOpen] = useState(false)
  const [qr, setQr] = useState<IlinkQrResponse | null>(null)
  const [qrLoading, setQrLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // wecom 表单
  const [wecomForm, setWecomForm] = useState({ bot_id: '', bot_secret: '', bot_key: 'wecom-aibot-1' })
  const [wecomTouched, setWecomTouched] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const res = await engineApi.list()
      setEngines(res.engines)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  const ilink = engines.find((e) => e.worker_type === 'ilink')
  const wecom = engines.find((e) => e.worker_type === 'wecom-aibot')
  const ilinkStep = computeIlinkStep(ilink)
  const wecomStep = computeWecomStep(wecom)

  // 已运行引擎的凭证回显：用户未手动编辑表单时，把后端返回的 bot_id / bot_key 同步进表单。
  // secret 出于安全不在状态接口返回，无法回显（保持空，由占位提示说明）。
  useEffect(() => {
    if (wecomTouched) return
    if (wecom?.bot_id && wecom.bot_id !== wecomForm.bot_id) {
      setWecomForm((f) => ({ ...f, bot_id: wecom.bot_id!, bot_key: wecom.bot_key || f.bot_key }))
    }
  }, [wecom, wecomTouched, wecomForm.bot_id])

  // ── iLink ──────────────────────────────────────────────
  const startIlink = async () => {
    setBusy('ilink-start')
    setError(null)
    try {
      await engineApi.ilinkStart(ilink?.bot_key)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const showQr = async () => {
    setQrOpen(true)
    setQr(null)
    setQrLoading(true)
    setError(null)
    try {
      const res = await engineApi.ilinkQr(ilink?.bot_key)
      setQr(res)
      if (res.status === 'pending') {
        startLoginPoll()
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setQrLoading(false)
    }
  }

  const startLoginPoll = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const st = await engineApi.ilinkStatus(ilink?.bot_key)
        if (st.login_status === 'success' || st.logged_in) {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          setQrOpen(false)
          await refresh()
        }
      } catch {
        /* ignore */
      }
    }, 2500)
  }

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  // ── WeCom AI Bot ───────────────────────────────────────
  const startWecom = async () => {
    if (!wecomForm.bot_id) {
      setError('请填写 Bot ID')
      return
    }
    setBusy('wecom-start')
    setError(null)
    try {
      // Secret 留空时后端从持久化 store 补齐（重启场景）
      await engineApi.wecomStart(wecomForm.bot_id, wecomForm.bot_secret, wecomForm.bot_key)
      setWecomTouched(false)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const stopWecom = async () => {
    setBusy('wecom-stop')
    setError(null)
    try {
      await engineApi.wecomStop(wecom?.bot_key)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-48" />
          <div className="h-32 bg-muted rounded-xl" />
          <div className="h-32 bg-muted rounded-xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">引擎管理</h1>
          <p className="text-sm text-muted-foreground mt-1">
            配置本地 HITL Server 的内置消息引擎。iLink 扫码登录，企业微信 AI Bot 填写凭证。
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCw className="w-4 h-4 mr-2" /> 刷新
        </Button>
      </div>

      {error && (
        <div className="bg-red-500/10 text-red-600 border border-red-500/20 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="grid gap-6">
        {/* iLink 卡 */}
        <Card className={ilinkStep.glow === 'amber' ? 'hitl-glow-amber' : ilinkStep.glow === 'blue' ? 'hitl-glow-blue' : ''}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 bg-green-500/10 rounded-lg flex items-center justify-center">
                  <Smartphone className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <CardTitle>iLink（个人微信）</CardTitle>
                  <CardDescription>扫码登录后，引擎维持长轮询收发消息</CardDescription>
                </div>
              </div>
              <StatusBadge on={!!ilink?.running} onText="轮询中" offText="未启动" />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <StepBanner step={ilinkStep} />

            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="text-muted-foreground">登录状态：</span>
              {ilink?.logged_in ? (
                <Badge className="bg-green-500/10 text-green-600 border-green-500/20 hover:bg-green-500/10">
                  <CheckCircle2 className="w-3 h-3 mr-1" /> 已登录
                </Badge>
              ) : (
                <Badge variant="secondary">未登录</Badge>
              )}
              {ilink?.bot_key && (
                <span className="text-muted-foreground">bot_key: <code className="text-foreground">{ilink.bot_key}</code></span>
              )}
            </div>

            {ilink?.activated_users && ilink.activated_users.length > 0 && (
              <div className="text-sm">
                <div className="text-muted-foreground mb-1">已激活用户（{ilink.activated_users.length}）：</div>
                <div className="flex flex-wrap gap-2">
                  {ilink.activated_users.map((u) => (
                    <Badge key={u.from_user_id} variant="outline" className="font-mono">
                      {u.from_user_id.slice(0, 16)}…
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3">
              {!ilink?.running ? (
                <Button onClick={startIlink} disabled={busy === 'ilink-start'}>
                  {busy === 'ilink-start' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plug className="w-4 h-4 mr-2" />}
                  启动引擎
                </Button>
              ) : (
                <Button onClick={showQr} disabled={qrLoading}>
                  {qrLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <QrCode className="w-4 h-4 mr-2" />}
                  {ilink.logged_in ? '重新扫码' : '显示二维码登录'}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* WeCom AI Bot 卡 */}
        <Card className={wecomStep.glow === 'amber' ? 'hitl-glow-amber' : wecomStep.glow === 'blue' ? 'hitl-glow-blue' : ''}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 bg-blue-500/10 rounded-lg flex items-center justify-center">
                  <MessageSquare className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <CardTitle>企业微信 AI Bot</CardTitle>
                  <CardDescription>填写 Bot 凭证，引擎建立 WebSocket 长连接</CardDescription>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {wecom && <StatusBadge on={!!wecom.connected} onText="已连接" offText={wecom.running ? '连接中' : '未运行'} />}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <StepBanner step={wecomStep} />

            {wecom?.bot_id && (
              <div className="text-sm text-muted-foreground">
                当前 Bot ID: <code className="text-foreground">{wecom.bot_id}</code>
                <span className="ml-3">bot_key: <code className="text-foreground">{wecom.bot_key}</code></span>
              </div>
            )}

            {wecom?.running && (
              <div className="text-sm">
                <div className="text-muted-foreground mb-1">已知收件人（{wecom.known_recipients?.length ?? 0}）：</div>
                {wecom.known_recipients && wecom.known_recipients.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {wecom.known_recipients.map((r) => (
                      <Badge key={r.recipient} variant="outline" className="font-mono" title={r.recipient}>
                        {r.chat_type === 'group' ? '群' : '单'} · {r.from_user || r.recipient.slice(0, 12)}…
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/20 rounded px-3 py-2 flex items-center gap-2">
                    <ArrowRight className="w-3.5 h-3.5 shrink-0" />
                    <span>请在<strong className="mx-1">企业微信里给 bot 发一条消息</strong>（单聊私聊 bot，或在群里 @bot）以激活收件人。</span>
                  </div>
                )}
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">Bot ID</label>
                <Input
                  value={wecomForm.bot_id}
                  onChange={(e) => { setWecomTouched(true); setWecomForm({ ...wecomForm, bot_id: e.target.value }) }}
                  placeholder="填写 Bot ID"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">Bot Secret</label>
                <Input
                  type="password"
                  value={wecomForm.bot_secret}
                  onChange={(e) => { setWecomTouched(true); setWecomForm({ ...wecomForm, bot_secret: e.target.value }) }}
                  placeholder={wecom?.running ? '已保存，无需重填；如需更换请输入新值' : '填写 Bot Secret'}
                />
                {wecom?.running && (
                  <p className="text-xs text-muted-foreground">凭证已保存到本地，重启自动恢复；仅当需要更换时才在此输入新 Secret。</p>
                )}
              </div>
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">Bot Key（路由标识）</label>
                <Input
                  value={wecomForm.bot_key}
                  onChange={(e) => { setWecomTouched(true); setWecomForm({ ...wecomForm, bot_key: e.target.value }) }}
                  placeholder="wecom-aibot-1"
                />
              </div>
            </div>
            <div className="flex gap-3">
              <Button onClick={startWecom} disabled={busy === 'wecom-start'}>
                {busy === 'wecom-start' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Plug className="w-4 h-4 mr-2" />}
                {wecom ? '重启引擎' : '启动引擎'}
              </Button>
              {wecom && (
                <Button variant="outline" onClick={stopWecom} disabled={busy === 'wecom-stop'}>
                  {busy === 'wecom-stop' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Power className="w-4 h-4 mr-2" />}
                  停止
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              提示：启动并在企微给 bot 发条消息激活后，Cursor MCP 配置只需
              <code className="mx-1">--engine wecom-aibot --bot-key {wecomForm.bot_key || 'wecom-aibot-1'}</code>
              ——无需带凭证、无需填 chat-id。
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 二维码弹窗 */}
      <Dialog open={qrOpen} onOpenChange={(o) => { setQrOpen(o); if (!o && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>扫码登录 iLink</DialogTitle>
            <DialogDescription>用个人微信扫描下方二维码完成登录，登录成功后窗口自动关闭</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col items-center gap-3 py-2">
            {qrLoading && <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />}
            {!qrLoading && qr?.status === 'pending' && qr.qr_base64 && (
              <img src={`data:image/png;base64,${qr.qr_base64}`} alt="QR" className="w-64 h-64 rounded-lg border" />
            )}
            {!qrLoading && qr?.status === 'error' && (
              <div className="text-red-600 text-sm">{qr.error}</div>
            )}
            {qr?.status === 'pending' && (
              <div className="text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> 等待扫码确认…
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
