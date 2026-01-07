import { useEffect, useState } from 'react'
import { RefreshCw, Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getHILSessions, type HILSession } from '@/api/client'

export function SessionsPage() {
  const [sessions, setSessions] = useState<HILSession[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSessions()
    // 每 10 秒自动刷新
    const interval = setInterval(loadSessions, 10000)
    return () => clearInterval(interval)
  }, [])

  const loadSessions = async () => {
    try {
      const data = await getHILSessions()
      setSessions(data.sessions || [])
    } catch (error) {
      console.error('Failed to load sessions:', error)
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending':
        return <Clock className="w-4 h-4 text-yellow-500" />
      case 'replied':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'timeout':
        return <XCircle className="w-4 h-4 text-red-500" />
      default:
        return <AlertCircle className="w-4 h-4 text-muted-foreground" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'pending':
        return <Badge variant="warning">等待中</Badge>
      case 'replied':
        return <Badge variant="success">已回复</Badge>
      case 'timeout':
        return <Badge variant="destructive">已超时</Badge>
      default:
        return <Badge variant="outline">{status}</Badge>
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
          <h1 className="text-2xl font-bold">HIL 会话</h1>
          <p className="text-muted-foreground text-sm mt-1">查看和管理 Human-in-the-Loop 会话</p>
        </div>
        <Button variant="outline" onClick={loadSessions} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading && sessions.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">加载中...</div>
          ) : sessions.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">暂无会话</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>状态</TableHead>
                  <TableHead>会话 ID</TableHead>
                  <TableHead>Chat ID</TableHead>
                  <TableHead>项目</TableHead>
                  <TableHead>消息内容</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead>过期时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow key={session.session_id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {getStatusIcon(session.status)}
                        {getStatusBadge(session.status)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <code className="text-xs bg-muted px-2 py-1 rounded font-mono">
                        {session.session_id.slice(0, 8)}...
                      </code>
                    </TableCell>
                    <TableCell>
                      <code className="text-xs text-muted-foreground font-mono">
                        {session.chat_id.slice(0, 16)}...
                      </code>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{session.project_name || '默认'}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[200px] truncate text-sm" title={session.message}>
                        {session.message}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatTime(session.created_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatTime(session.expires_at)}
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
