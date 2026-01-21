import { useEffect, useRef } from 'react'
import { useTunnels } from './useTunnels'

/**
 * 实时更新隧道状态
 * 通过轮询方式获取最新状态
 */
export function useRealtime(interval: number = 5000) {
  const { loadTunnels } = useTunnels()
  const intervalRef = useRef<number | null>(null)

  useEffect(() => {
    // 立即加载一次
    loadTunnels()

    // 设置定时轮询
    intervalRef.current = window.setInterval(() => {
      loadTunnels()
    }, interval)

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current)
      }
    }
  }, [loadTunnels, interval])
}
