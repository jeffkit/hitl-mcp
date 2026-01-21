import { useState, useEffect, useCallback } from 'react'
import { message } from 'antd'
import { api } from '../api/client'
import type { Tunnel, CreateTunnelRequest, UpdateTunnelRequest } from '../types'

export function useTunnels() {
  const [tunnels, setTunnels] = useState<Tunnel[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadTunnels = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listTunnels()
      setTunnels(data)
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || '加载失败'
      setError(errorMsg)
      message.error(`加载隧道列表失败: ${errorMsg}`)
    } finally {
      setLoading(false)
    }
  }, [])

  const createTunnel = useCallback(async (data: CreateTunnelRequest) => {
    try {
      const result = await api.createTunnel(data)
      await loadTunnels()
      message.success(`隧道 ${result.domain} 创建成功`)
      return result
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || '创建失败'
      message.error(`创建隧道失败: ${errorMsg}`)
      throw err
    }
  }, [loadTunnels])

  const updateTunnel = useCallback(async (domain: string, data: UpdateTunnelRequest) => {
    try {
      const result = await api.updateTunnel(domain, data)
      await loadTunnels()
      message.success(`隧道 ${domain} 更新成功`)
      return result
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || '更新失败'
      message.error(`更新隧道失败: ${errorMsg}`)
      throw err
    }
  }, [loadTunnels])

  const deleteTunnel = useCallback(async (domain: string) => {
    try {
      await api.deleteTunnel(domain)
      await loadTunnels()
      message.success(`隧道 ${domain} 删除成功`)
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || '删除失败'
      message.error(`删除隧道失败: ${errorMsg}`)
      throw err
    }
  }, [loadTunnels])

  const regenerateToken = useCallback(async (domain: string) => {
    try {
      const result = await api.regenerateToken(domain)
      return result
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || '重新生成失败'
      message.error(`重新生成 Token 失败: ${errorMsg}`)
      throw err
    }
  }, [])

  useEffect(() => {
    loadTunnels()
  }, [loadTunnels])

  return {
    tunnels,
    loading,
    error,
    loadTunnels,
    createTunnel,
    updateTunnel,
    deleteTunnel,
    regenerateToken,
  }
}
