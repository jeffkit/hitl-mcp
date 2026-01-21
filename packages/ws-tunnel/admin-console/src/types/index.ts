export interface Tunnel {
  domain: string
  name: string | null
  description: string | null
  enabled: boolean
  connected: boolean
  token?: string | null
  created_at: string | null
  last_connected_at: string | null
  total_requests: number
}

export interface CreateTunnelRequest {
  domain: string
  name?: string | null
  description?: string | null
}

export interface UpdateTunnelRequest {
  name?: string | null
  description?: string | null
  enabled?: boolean | null
}

export interface ServerInfo {
  name: string
  version: string
  domain: {
    pattern: string
    customizable: string
    suffix: string
  }
  websocket: {
    url: string
  }
  protocols: string[]
}

export interface CheckAvailabilityResponse {
  available: boolean
  name: string
  reason: string | null
}

export interface RegenerateTokenResponse {
  domain: string
  token: string
}
