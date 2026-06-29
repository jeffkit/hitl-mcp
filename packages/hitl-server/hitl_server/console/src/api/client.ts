// API 基础配置
// 本地 HITL Server 管理台：只绑 127.0.0.1，无需登录鉴权，开箱即用。
const API_BASE = '/admin/api'

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  const data = await response.json()

  if (!response.ok) {
    throw new Error(data.detail || data.error || `请求失败: ${response.status}`)
  }

  return data
}

export const api = {
  get: <T>(endpoint: string) => request<T>(endpoint, { method: 'GET' }),
  post: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(endpoint: string) => request<T>(endpoint, { method: 'DELETE' }),
}

// HIL Sessions API（会话调试）
export interface HILSession {
  session_id: string
  short_id?: string
  chat_id: string
  chat_type?: string
  project_name: string
  status: string
  message: string
  replies_count?: number
  created_at: string
  expire_at?: string
  expires_at?: string
}

export async function getHILSessions() {
  return api.get<{ total: number; sessions: HILSession[] }>('/hil/sessions')
}

// Engines API（内置引擎管理：iLink 扫码、WeCom AI Bot 凭证）
export interface EngineStatus {
  worker_type: string
  bot_key: string
  running: boolean
  // ilink 专属
  logged_in?: boolean
  login_status?: string
  activated_users?: { from_user_id: string; has_context_token: boolean }[]
  // wecom-aibot 专属
  bot_id?: string
  connected?: boolean
  known_recipients?: { recipient: string; chat_type: string; from_user: string; last_active: number }[]
}

export interface EnginesListResponse {
  engines: EngineStatus[]
}

export interface IlinkQrResponse {
  status: string
  qr_url?: string
  qr_base64?: string
  qrcode_key?: string
  error?: string
}

export const engineApi = {
  list: () => api.get<EnginesListResponse>('/engines'),
  ilinkStart: (botKey?: string) =>
    api.post<{ success: boolean; engine: EngineStatus }>('/engines/ilink/start', { bot_key: botKey ?? null }),
  ilinkQr: (botKey?: string) =>
    api.get<IlinkQrResponse>(`/engines/ilink/qr${botKey ? `?bot_key=${botKey}` : ''}`),
  ilinkStatus: (botKey?: string) =>
    api.get<EngineStatus>(`/engines/ilink/status${botKey ? `?bot_key=${botKey}` : ''}`),
  wecomStart: (botId: string, botSecret: string, botKey?: string) =>
    api.post<{ success: boolean; engine: EngineStatus }>('/engines/wecom-aibot/start', {
      bot_id: botId,
      bot_secret: botSecret,
      bot_key: botKey ?? 'wecom-aibot-1',
    }),
  wecomStop: (botKey?: string) =>
    api.post<{ success: boolean; error?: string }>(
      `/engines/wecom-aibot/stop${botKey ? `?bot_key=${botKey}` : ''}`,
      {},
    ),
}
