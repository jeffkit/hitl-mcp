import axios from 'axios'
import type {
  Tunnel,
  CreateTunnelRequest,
  UpdateTunnelRequest,
  ServerInfo,
  CheckAvailabilityResponse,
  RegenerateTokenResponse,
} from '../types'

// 支持环境变量配置 API 地址
// VITE_API_BASE_URL: 完整的 API 基础 URL（如 https://tunely.example.com/api）
// 如果未设置，则使用相对路径 /api（通过 Vite 代理）
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

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

// 请求拦截器：添加 API Key
client.interceptors.request.use((config) => {
  const apiKey = getApiKey()
  if (apiKey) {
    config.headers['x-api-key'] = apiKey
  }
  return config
})

// 响应拦截器：处理错误
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // API Key 无效，清除
      setApiKey(null)
    }
    return Promise.reject(error)
  }
)

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
}
