import { useEffect, useState } from 'react'
import { RefreshCw, TrendingUp, Users, Clock, CheckCircle, XCircle, Bot } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getAuthToken } from '@/api/client'

interface StatsData {
  success: boolean
  period_days: number
  total_count: number
  period_count: number
  status_counts: Record<string, number>
  success_rate: number
  avg_duration_ms: number
  bot_stats: { bot_name: string; bot_key: string; count: number }[]
  daily_stats: { date: string; count: number }[]
  top_users: { user_name: string; count: number }[]
  error?: string
}

export function StatsPage() {
  const [stats, setStats] = useState<StatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(7)

  useEffect(() => {
    loadStats()
  }, [days])

  const loadStats = async () => {
    setLoading(true)
    try {
      const token = getAuthToken()
      const response = await fetch(`/admin/api/forward/proxy/admin/stats?days=${days}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      const data = await response.json()
      setStats(data)
    } catch (error) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    )
  }

  if (!stats || !stats.success) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          加载统计数据失败: {stats?.error || '未知错误'}
        </div>
      </div>
    )
  }

  const maxDailyCount = Math.max(...stats.daily_stats.map(d => d.count), 1)

  return (
    <div className="p-6 space-y-6">
      {/* 头部 */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">消息统计</h1>
          <p className="text-gray-500">Forward Service 消息处理统计</p>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="border rounded-lg px-3 py-2"
          >
            <option value={7}>最近 7 天</option>
            <option value={14}>最近 14 天</option>
            <option value={30}>最近 30 天</option>
          </select>
          <Button onClick={loadStats} disabled={loading} variant="outline" size="sm">
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </div>
      </div>

      {/* 概览卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">总消息数</CardTitle>
            <TrendingUp className="h-4 w-4 text-gray-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total_count.toLocaleString()}</div>
            <p className="text-xs text-gray-500">
              近 {days} 天: {stats.period_count.toLocaleString()}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">成功率</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">{stats.success_rate}%</div>
            <p className="text-xs text-gray-500">
              成功: {stats.status_counts.success || 0} / 失败: {(stats.status_counts.error || 0) + (stats.status_counts.timeout || 0)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">平均响应时间</CardTitle>
            <Clock className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {stats.avg_duration_ms > 1000 
                ? `${(stats.avg_duration_ms / 1000).toFixed(1)}s`
                : `${Math.round(stats.avg_duration_ms)}ms`
              }
            </div>
            <p className="text-xs text-gray-500">Agent 处理耗时</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">活跃 Bot</CardTitle>
            <Bot className="h-4 w-4 text-purple-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.bot_stats.length}</div>
            <p className="text-xs text-gray-500">
              消息最多: {stats.bot_stats[0]?.bot_name || '-'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 每日趋势图 */}
      <Card>
        <CardHeader>
          <CardTitle>每日消息量趋势</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48 flex items-end gap-1">
            {stats.daily_stats.map((day, index) => (
              <div key={index} className="flex-1 flex flex-col items-center">
                <div 
                  className="w-full bg-blue-500 rounded-t transition-all hover:bg-blue-600"
                  style={{ 
                    height: `${(day.count / maxDailyCount) * 100}%`,
                    minHeight: day.count > 0 ? '4px' : '0'
                  }}
                  title={`${day.date}: ${day.count} 条消息`}
                />
                <span className="text-xs text-gray-400 mt-1 rotate-45 origin-left">
                  {day.date.slice(5)}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bot 统计 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              Bot 消息分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            {stats.bot_stats.length === 0 ? (
              <p className="text-gray-500 text-center py-4">暂无数据</p>
            ) : (
              <div className="space-y-3">
                {stats.bot_stats.map((bot, index) => {
                  const maxBotCount = Math.max(...stats.bot_stats.map(b => b.count), 1)
                  return (
                    <div key={index} className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="font-medium">{bot.bot_name}</span>
                        <span className="text-gray-500">{bot.count} 条</span>
                      </div>
                      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-purple-500 rounded-full"
                          style={{ width: `${(bot.count / maxBotCount) * 100}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 活跃用户 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              活跃用户 Top 10
            </CardTitle>
          </CardHeader>
          <CardContent>
            {stats.top_users.length === 0 ? (
              <p className="text-gray-500 text-center py-4">暂无数据</p>
            ) : (
              <div className="space-y-2">
                {stats.top_users.map((user, index) => (
                  <div key={index} className="flex items-center justify-between py-2 border-b last:border-0">
                    <div className="flex items-center gap-3">
                      <span className={`
                        w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
                        ${index === 0 ? 'bg-yellow-100 text-yellow-700' : 
                          index === 1 ? 'bg-gray-100 text-gray-600' :
                          index === 2 ? 'bg-orange-100 text-orange-700' : 'bg-gray-50 text-gray-500'}
                      `}>
                        {index + 1}
                      </span>
                      <span className="font-medium">{user.user_name}</span>
                    </div>
                    <span className="text-gray-500">{user.count} 条</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 状态分布 */}
      <Card>
        <CardHeader>
          <CardTitle>处理状态分布</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-6 flex-wrap">
            {Object.entries(stats.status_counts).map(([status, count]) => (
              <div key={status} className="flex items-center gap-2">
                {status === 'success' ? (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
                <span className="font-medium capitalize">{status}</span>
                <span className="text-gray-500">({count})</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
