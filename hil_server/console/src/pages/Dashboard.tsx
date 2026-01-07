import { useEffect, useState } from 'react'
import { Bot, MessageSquare, Send, Users } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getOverview } from '@/api/client'

interface OverviewData {
  mode: string
  hil_server: {
    sessions: { active: number; total: number }
  }
  forward_service?: {
    config: { bots_count: number }
    stats: { total_requests: number; recent_success: number; recent_error: number }
  }
  worker?: {
    connected: number
  }
}

export function DashboardPage() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    try {
      const result = await getOverview()
      setData(result as unknown as OverviewData)
    } catch (error) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-48" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-32 bg-muted rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">概览</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Bot 数量
            </CardTitle>
            <Bot className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.forward_service?.config.bots_count || 0}</div>
            <p className="text-xs text-muted-foreground">
              Forward Service 配置
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              HIL 会话
            </CardTitle>
            <MessageSquare className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.hil_server?.sessions.total || 0}</div>
            <p className="text-xs text-muted-foreground">
              {data?.hil_server?.sessions.active || 0} 个活跃中
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              转发请求
            </CardTitle>
            <Send className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{data?.forward_service?.stats.total_requests || 0}</div>
            <p className="text-xs text-muted-foreground">
              成功 {data?.forward_service?.stats.recent_success || 0} / 失败 {data?.forward_service?.stats.recent_error || 0}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              运行模式
            </CardTitle>
            <Users className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold capitalize">{data?.mode || 'N/A'}</div>
            <p className="text-xs text-muted-foreground">
              {data?.mode === 'direct' ? '直连模式' : '转发模式'}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>HIL 会话统计</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">总会话</span>
                <span className="font-medium">{data?.hil_server?.sessions.total || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">活跃中</span>
                <span className="font-medium text-green-500">{data?.hil_server?.sessions.active || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Forward 服务统计</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Bot 数量</span>
                <span className="font-medium">{data?.forward_service?.config.bots_count || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">总请求数</span>
                <span className="font-medium">{data?.forward_service?.stats.total_requests || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">成功</span>
                <span className="font-medium text-green-500">{data?.forward_service?.stats.recent_success || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">失败</span>
                <span className="font-medium text-red-500">{data?.forward_service?.stats.recent_error || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
