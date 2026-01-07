// API 基础配置
const API_BASE = '/admin/api'

let authToken: string | null = localStorage.getItem('auth_token')

export function setAuthToken(token: string | null) {
  authToken = token
  if (token) {
    localStorage.setItem('auth_token', token)
  } else {
    localStorage.removeItem('auth_token')
  }
}

export function getAuthToken() {
  return authToken
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  const data = await response.json()

  if (!response.ok) {
    if (response.status === 401 && endpoint !== '/login') {
      setAuthToken(null)
      window.location.href = '/console/'
    }
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

// Auth APIs
export async function login(username: string, password: string) {
  try {
    const data = await api.post<{ token: string; expires_at: string }>('/login', {
      username,
      password,
    })
    if (data.token) {
      setAuthToken(data.token)
      return { success: true, token: data.token }
    }
    return { success: false, error: '登录失败' }
  } catch (error: unknown) {
    const err = error as { message?: string }
    return { success: false, error: err.message || '登录失败' }
  }
}

export async function verifyToken() {
  return api.get<{ valid: boolean; username?: string }>('/verify')
}

export function logout() {
  setAuthToken(null)
}

// Bot APIs (通过 forward-service 代理)
export interface Bot {
  id: number
  bot_key: string
  name: string
  description: string
  url_template: string
  agent_id: string
  api_key: string
  timeout: number
  access_mode: 'allow_all' | 'whitelist' | 'blacklist'
  enabled: boolean
  whitelist_count?: number
  blacklist_count?: number
  created_at: string
  updated_at: string
}

export interface BotListResponse {
  success: boolean
  bots: Bot[]
  error?: string
}

export interface BotDetailResponse {
  success: boolean
  bot: Bot & {
    whitelist: string[]
    blacklist: string[]
  }
  error?: string
}

export const botApi = {
  list: () => api.get<BotListResponse>('/forward/proxy/admin/bots'),
  get: (botKey: string) => api.get<BotDetailResponse>(`/forward/proxy/admin/bots/${botKey}`),
  create: (bot: Partial<Bot>) => api.post<{ success: boolean; bot?: Bot; error?: string }>('/forward/proxy/admin/bots', bot),
  update: (botKey: string, bot: Partial<Bot>) => api.put<{ success: boolean; error?: string }>(`/forward/proxy/admin/bots/${botKey}`, bot),
  delete: (botKey: string) => api.delete<{ success: boolean; error?: string }>(`/forward/proxy/admin/bots/${botKey}`),
}

// Forward Mode API
export async function getForwardMode() {
  return api.get<{ mode: string; supports_bot_api: boolean; version: string }>('/forward/proxy/admin/mode')
}

// Overview API
export async function getOverview() {
  return api.get<{
    hil_stats: { total: number; pending: number; replied: number; timeout: number }
    forward_stats: { total_bots: number; enabled_bots: number; total_rules: number; total_logs: number; recent_logs: number }
    worker_stats: { connected: number; total_registered: number }
  }>('/overview')
}

// HIL Sessions API
export interface HILSession {
  session_id: string
  chat_id: string
  project_name: string
  status: string
  message: string
  created_at: string
  expires_at: string
}

export async function getHILSessions() {
  return api.get<{ sessions: HILSession[] }>('/hil/sessions')
}

// Forward Logs API
export interface ForwardLog {
  timestamp: string
  chat_id: string
  from_user: string
  content: string
  target_url: string
  status: string
  response?: string
  error?: string
  duration_ms: number
}

export async function getForwardLogs() {
  return api.get<{ success: boolean; logs: ForwardLog[] }>('/forward/logs')
}
