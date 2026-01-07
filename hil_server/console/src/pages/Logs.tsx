import { useEffect, useState } from 'react'
import { RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getForwardLogs, type ForwardLog } from '@/api/client'

export function LogsPage() {
  const [logs, setLogs] = useState<ForwardLog[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadLogs()
  }, [])

  const loadLogs = async () => {
    setLoading(true)
    try {
      const data = await getForwardLogs()
      if (data.success) {
        setLogs(data.logs || [])
      }
    } catch (error) {
      console.error('Failed to load logs:', error)
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Forward 日志</h1>
          <p className="text-muted-foreground text-sm mt-1">查看消息转发请求日志</p>
        </div>
        <Button variant="outline" onClick={loadLogs} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading && logs.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">加载中...</div>
          ) : logs.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">暂无日志</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>发送者</TableHead>
                  <TableHead>内容</TableHead>
                  <TableHead>目标 URL</TableHead>
                  <TableHead>耗时</TableHead>
                  <TableHead>响应/错误</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log, index) => (
                  <TableRow key={index}>
                    <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                      {formatTime(log.timestamp)}
                    </TableCell>
                    <TableCell>
                      {log.status === 'success' ? (
                        <Badge variant="success" className="gap-1">
                          <CheckCircle className="w-3 h-3" />
                          成功
                        </Badge>
                      ) : (
                        <Badge variant="destructive" className="gap-1">
                          <XCircle className="w-3 h-3" />
                          失败
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{log.from_user}</TableCell>
                    <TableCell>
                      <div className="max-w-[150px] truncate text-sm" title={log.content}>
                        {log.content}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[200px] truncate text-xs text-muted-foreground" title={log.target_url}>
                        {log.target_url}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {log.duration_ms}ms
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[150px] truncate text-xs" title={log.response || log.error}>
                        {log.status === 'success' ? (
                          <span className="text-muted-foreground">{log.response?.slice(0, 50)}...</span>
                        ) : (
                          <span className="text-destructive">{log.error}</span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
