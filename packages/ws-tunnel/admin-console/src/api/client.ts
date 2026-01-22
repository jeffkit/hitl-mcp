import axios from 'axios'
import type {
  Tunnel,
  CreateTunnelRequest,
  UpdateTunnelRequest,
  ServerInfo,
  CheckAvailabilityResponse,
  RegenerateTokenResponse,
  TunnelLogsResponse,
} from '../types'

// 支持环境变量配置 API 地址
// VITE_API_BASE_URL: 完整的 API 基础 URL（如 https://tunely.example.com/api）
// 如果未设置，则使用相对路径（通过 Vite 代理或 Nginx）
// 如果设置了 base path，需要包含在路径中
// 优先使用 localStorage 中配置的 API Base URL
const BASE_PATH = import.meta.env.BASE_URL || ''
const getStoredApiBaseUrl = () => {
  const stored = localStorage.getItem('tunely_api_base_url')
  if (stored) return stored
  return import.meta.env.VITE_API_BASE_URL || `${BASE_PATH.replace(/\/$/, '')}/api`
}
const API_BASE_URL = getStoredApiBaseUrl()

// 从 localStorage 获取 API Key
function getApiKey(): string | null {
  return localStorage.getItem('tunely_api_key')
}

// 设置 API Key
export function setApiKey(apiKey: string | null) {
  if (apiKey) {
    localStorage.setItem('tunely_api_key', apiKey)
  } else {
    localStorage.removeItem('tunely_api_key')
  }
}

// 动态创建 client，支持运行时更新 baseURL
function createClient() {
  const baseURL = getStoredApiBaseUrl()
  const newClient = axios.create({
    baseURL: baseURL,
    headers: {
      'Content-Type': 'application/json',
    },
  })

  // 请求拦截器：添加 API Key
  newClient.interceptors.request.use((config) => {
    const apiKey = getApiKey()
    if (apiKey) {
      config.headers['x-api-key'] = apiKey
    }
    return config
  })

  // 响应拦截器：处理错误
  newClient.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        // API Key 无效，清除
        setApiKey(null)
      }
      return Promise.reject(error)
    }
  )

  return newClient
}

let client = createClient()

// 导出函数用于更新 API Base URL
export function updateApiBaseUrl(newBaseUrl: string) {
  localStorage.setItem('tunely_api_base_url', newBaseUrl)
  client = createClient()
  // 触发页面刷新以使用新的 client
  window.location.reload()
}

export const api = {
  // 服务器信息
  async getServerInfo(): Promise<ServerInfo> {
    const response = await client.get('/info')
    return response.data
  },

  // 隧道管理
  async listTunnels(): Promise<Tunnel[]> {
    const response = await client.get('/tunnels')
    return response.data
  },

  async getTunnel(domain: string): Promise<Tunnel> {
    const response = await client.get(`/tunnels/${domain}`)
    return response.data
  },

  async createTunnel(data: CreateTunnelRequest): Promise<Tunnel & { token: string }> {
    const response = await client.post('/tunnels', data)
    return response.data
  },

  async updateTunnel(domain: string, data: UpdateTunnelRequest): Promise<Tunnel> {
    const response = await client.put(`/tunnels/${domain}`, data)
    return response.data
  },

  async deleteTunnel(domain: string): Promise<void> {
    await client.delete(`/tunnels/${domain}`)
  },

  async regenerateToken(domain: string): Promise<RegenerateTokenResponse> {
    const response = await client.post(`/tunnels/${domain}/regenerate-token`)
    return response.data
  },

  async checkAvailability(name: string): Promise<CheckAvailabilityResponse> {
    const response = await client.get('/tunnels/check-availability', {
      params: { name },
    })
    return response.data
  },

  // 请求历史
  async getTunnelLogs(
    domain: string,
    limit: number = 100,
    offset: number = 0
  ): Promise<TunnelLogsResponse> {
    const response = await client.get(`/tunnels/${domain}/logs`, {
      params: { limit, offset },
    })
    return response.data
  },
}
