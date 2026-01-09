import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, RefreshCw, Copy, Check, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog'
import { botApi, type Bot } from '@/api/client'

export function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [editingBot, setEditingBot] = useState<Bot | null>(null)
  const [deletingBot, setDeletingBot] = useState<Bot | null>(null)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    bot_key: '',
    url_template: '',  // 继续使用 url_template，但 UI 显示为"目标 URL"
    api_key: '',
    timeout: 1200,
    access_mode: 'allow_all' as 'allow_all' | 'whitelist' | 'blacklist',
    enabled: true,
    whitelist: [] as string[],
    blacklist: [] as string[],
  })
  const [newListItem, setNewListItem] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadBots()
  }, [])

  const loadBots = async () => {
    setLoading(true)
    try {
      const data = await botApi.list()
      if (data.success) {
        setBots(data.bots)
      }
    } catch (error) {
      console.error('Failed to load bots:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = () => {
    setEditingBot(null)
    setFormData({
      name: '',
      description: '',
      bot_key: crypto.randomUUID(),
      url_template: '',
      api_key: '',
      timeout: 1200,
      access_mode: 'allow_all',
      enabled: true,
      whitelist: [],
      blacklist: [],
    })
    setNewListItem('')
    setDialogOpen(true)
  }

  const handleEdit = async (bot: Bot) => {
    // 加载完整的 bot 详情（包含黑白名单）
    try {
      const detail = await botApi.get(bot.bot_key)
      if (detail.success && detail.bot) {
        setEditingBot(bot)
        // 后端返回的黑白名单是对象数组 {id, chat_id, remark}，需要提取 chat_id
        const whitelist = (detail.bot.whitelist || []).map((item: string | { chat_id: string }) => 
          typeof item === 'string' ? item : item.chat_id
        )
        const blacklist = (detail.bot.blacklist || []).map((item: string | { chat_id: string }) => 
          typeof item === 'string' ? item : item.chat_id
        )
        setFormData({
          name: detail.bot.name,
          description: detail.bot.description || '',
          bot_key: detail.bot.bot_key,
          url_template: detail.bot.url_template?.replace('{agent_id}', detail.bot.agent_id || '') || '',
          api_key: detail.bot.api_key || '',
          timeout: detail.bot.timeout,
          access_mode: detail.bot.access_mode,
          enabled: detail.bot.enabled,
          whitelist,
          blacklist,
        })
        setNewListItem('')
        setDialogOpen(true)
      }
    } catch (error) {
      console.error('Failed to load bot detail:', error)
      alert('加载 Bot 详情失败')
    }
  }

  const handleDelete = (bot: Bot) => {
    setDeletingBot(bot)
    setDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingBot) return
    try {
      const result = await botApi.delete(deletingBot.bot_key)
      if (result.success) {
        await loadBots()
      } else {
        alert('删除失败: ' + (result.error || '未知错误'))
      }
    } catch (error) {
      alert('删除失败')
    } finally {
      setDeleteDialogOpen(false)
      setDeletingBot(null)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      if (editingBot) {
        const result = await botApi.update(editingBot.bot_key, formData)
        if (!result.success) {
          alert('保存失败: ' + (result.error || '未知错误'))
          return
        }
      } else {
        const result = await botApi.create(formData)
        if (!result.success) {
          alert('创建失败: ' + (result.error || '未知错误'))
          return
        }
      }
      await loadBots()
      setDialogOpen(false)
    } catch (error) {
      alert('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const copyBotKey = (key: string) => {
    navigator.clipboard.writeText(key)
    setCopiedKey(key)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const addListItem = (listType: 'whitelist' | 'blacklist') => {
    if (!newListItem.trim()) return
    const list = formData[listType]
    if (!list.includes(newListItem.trim())) {
      setFormData({
        ...formData,
        [listType]: [...list, newListItem.trim()],
      })
    }
    setNewListItem('')
  }

  const removeListItem = (listType: 'whitelist' | 'blacklist', item: string) => {
    setFormData({
      ...formData,
      [listType]: formData[listType].filter((i) => i !== item),
    })
  }

  const accessModeLabels = {
    allow_all: '允许所有',
    whitelist: '白名单',
    blacklist: '黑名单',
  }

  const currentList = formData.access_mode === 'whitelist' ? 'whitelist' : 'blacklist'
  const showListEditor = formData.access_mode !== 'allow_all'

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Bot 管理</h1>
          <p className="text-muted-foreground text-sm mt-1">管理企微机器人配置和转发规则</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={loadBots} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          <Button onClick={handleAdd}>
            <Plus className="w-4 h-4 mr-2" />
            添加 Bot
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground">加载中...</div>
          ) : bots.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">暂无 Bot 配置</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>Bot Key</TableHead>
                  <TableHead>转发 URL</TableHead>
                  <TableHead>访问模式</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bots.map((bot) => (
                  <TableRow key={bot.bot_key}>
                    <TableCell>
                      <div>
                        <div className="font-medium">{bot.name || '未命名'}</div>
                        {bot.description && (
                          <div className="text-xs text-muted-foreground">{bot.description}</div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <code className="text-xs bg-muted px-2 py-1 rounded font-mono">
                          {bot.bot_key.slice(0, 16)}...
                        </code>
                        <button
                          onClick={() => copyBotKey(bot.bot_key)}
                          className="p-1 hover:bg-muted rounded transition-colors"
                          title="复制完整 Bot Key"
                        >
                          {copiedKey === bot.bot_key ? (
                            <Check className="w-3.5 h-3.5 text-green-500" />
                          ) : (
                            <Copy className="w-3.5 h-3.5 text-muted-foreground" />
                          )}
                        </button>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[250px] truncate text-xs text-muted-foreground" title={bot.url_template}>
                        {bot.url_template}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {accessModeLabels[bot.access_mode]}
                        {bot.access_mode === 'whitelist' && bot.whitelist_count ? ` (${bot.whitelist_count})` : ''}
                        {bot.access_mode === 'blacklist' && bot.blacklist_count ? ` (${bot.blacklist_count})` : ''}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={bot.enabled ? 'success' : 'outline'}>
                        {bot.enabled ? '启用' : '禁用'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="ghost" size="sm" onClick={() => handleEdit(bot)}>
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(bot)}>
                          <Trash2 className="w-4 h-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 编辑/添加对话框 */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" onClose={() => setDialogOpen(false)}>
          <DialogHeader>
            <DialogTitle>{editingBot ? '编辑 Bot' : '添加 Bot'}</DialogTitle>
            <DialogDescription>
              配置企微机器人的转发规则和访问控制
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">名称 *</label>
                <Input
                  placeholder="Bot 名称"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Bot Key</label>
                <Input
                  value={formData.bot_key}
                  onChange={(e) => setFormData({ ...formData, bot_key: e.target.value })}
                  disabled={!!editingBot}
                  className="font-mono text-xs"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">描述</label>
              <Input
                placeholder="Bot 描述（可选）"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">目标 URL *</label>
              <Input
                placeholder="https://example.com/a2a/your-agent-id/messages"
                value={formData.url_template}
                onChange={(e) => setFormData({ ...formData, url_template: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">Agent 的完整请求地址</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">API Key</label>
              <Input
                type="password"
                placeholder="Agent API Key（可选）"
                value={formData.api_key}
                onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">超时时间(秒)</label>
                <Input
                  type="number"
                  value={formData.timeout}
                  onChange={(e) => setFormData({ ...formData, timeout: parseInt(e.target.value) || 1200 })}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">访问模式</label>
                <select
                  className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                  value={formData.access_mode}
                  onChange={(e) => setFormData({ ...formData, access_mode: e.target.value as typeof formData.access_mode })}
                >
                  <option value="allow_all">允许所有</option>
                  <option value="whitelist">白名单</option>
                  <option value="blacklist">黑名单</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">状态</label>
                <select
                  className="w-full h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                  value={formData.enabled ? 'true' : 'false'}
                  onChange={(e) => setFormData({ ...formData, enabled: e.target.value === 'true' })}
                >
                  <option value="true">启用</option>
                  <option value="false">禁用</option>
                </select>
              </div>
            </div>

            {/* 黑白名单编辑器 */}
            {showListEditor && (
              <div className="space-y-3 border border-border rounded-lg p-4">
                <label className="text-sm font-medium">
                  {formData.access_mode === 'whitelist' ? '白名单' : '黑名单'} 
                  <span className="text-muted-foreground ml-2">
                    ({formData[currentList].length} 个 Chat ID)
                  </span>
                </label>
                <div className="flex gap-2">
                  <Input
                    placeholder="输入 Chat ID"
                    value={newListItem}
                    onChange={(e) => setNewListItem(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addListItem(currentList)
                      }
                    }}
                  />
                  <Button type="button" onClick={() => addListItem(currentList)} variant="secondary">
                    添加
                  </Button>
                </div>
                {formData[currentList].length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {formData[currentList].map((item) => (
                      <div
                        key={item}
                        className="flex items-center gap-1 bg-muted px-2 py-1 rounded text-sm"
                      >
                        <span className="font-mono text-xs">{item}</span>
                        <button
                          type="button"
                          onClick={() => removeListItem(currentList, item)}
                          className="p-0.5 hover:bg-background rounded"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  {formData.access_mode === 'whitelist'
                    ? '只有名单中的 Chat ID 可以使用此 Bot'
                    : '名单中的 Chat ID 将被禁止使用此 Bot'}
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button onClick={handleSave} disabled={saving || !formData.name || !formData.url_template}>
              {saving ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent onClose={() => setDeleteDialogOpen(false)}>
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              确定要删除 Bot "{deletingBot?.name}" 吗？此操作无法撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>取消</Button>
            <Button variant="destructive" onClick={confirmDelete}>删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
