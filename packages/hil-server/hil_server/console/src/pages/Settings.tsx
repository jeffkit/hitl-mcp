import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Save, Plus, X, Users, AlertCircle, Check, Loader2 } from 'lucide-react';
import { getAuthToken } from '@/api/client';

interface AdminUser {
  value: string;
  isNew?: boolean;
}

export default function SettingsPage() {
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [newUser, setNewUser] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    fetchAdminUsers();
  }, []);

  const fetchAdminUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const token = getAuthToken();
      const response = await fetch('/admin/api/forward/proxy/admin/system/admin-users', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await response.json();
      
      if (data.success) {
        setAdminUsers(data.admin_users.map((u: string) => ({ value: u })));
      } else {
        setError(data.error || '获取管理员列表失败');
      }
    } catch (err) {
      setError('获取管理员列表失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  const handleAddUser = () => {
    const trimmedUser = newUser.trim();
    if (!trimmedUser) return;
    
    // 检查是否已存在
    if (adminUsers.some(u => u.value === trimmedUser)) {
      setError('该用户已在管理员列表中');
      return;
    }
    
    setAdminUsers([...adminUsers, { value: trimmedUser, isNew: true }]);
    setNewUser('');
    setError(null);
    setSuccess(null);
  };

  const handleRemoveUser = (index: number) => {
    setAdminUsers(adminUsers.filter((_, i) => i !== index));
    setSuccess(null);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);
      
      const token = getAuthToken();
      const response = await fetch('/admin/api/forward/proxy/admin/system/admin-users', {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          admin_users: adminUsers.map(u => u.value)
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        setSuccess(data.message || '保存成功');
        // 刷新数据，清除 isNew 标记
        setAdminUsers(data.admin_users.map((u: string) => ({ value: u })));
      } else {
        setError(data.error || '保存失败');
      }
    } catch (err) {
      setError('保存失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setSaving(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddUser();
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">系统设置</h1>
        <p className="text-muted-foreground">配置 Forward Service 的系统参数</p>
      </div>

      {/* 管理员配置卡片 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            管理员用户
          </CardTitle>
          <CardDescription>
            配置可以使用 <code className="bg-muted px-1 rounded">/ping</code> 和 <code className="bg-muted px-1 rounded">/status</code> 命令的用户。
            <br />
            支持填写用户的 <strong>user_id</strong> 或 <strong>别名 (alias)</strong>。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 错误提示 */}
          {error && (
            <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-md">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm">{error}</span>
            </div>
          )}
          
          {/* 成功提示 */}
          {success && (
            <div className="flex items-center gap-2 p-3 bg-green-500/10 text-green-600 rounded-md">
              <Check className="h-4 w-4" />
              <span className="text-sm">{success}</span>
            </div>
          )}
          
          {/* 加载状态 */}
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground">加载中...</span>
            </div>
          ) : (
            <>
              {/* 添加用户输入框 */}
              <div className="flex gap-2">
                <div className="flex-1">
                  <Input
                    id="new-admin"
                    placeholder="输入用户 ID 或别名"
                    value={newUser}
                    onChange={(e) => setNewUser(e.target.value)}
                    onKeyPress={handleKeyPress}
                  />
                </div>
                <Button onClick={handleAddUser} variant="outline">
                  <Plus className="h-4 w-4 mr-1" />
                  添加
                </Button>
              </div>
              
              {/* 管理员列表 */}
              <div className="border rounded-md">
                {adminUsers.length === 0 ? (
                  <div className="p-4 text-center text-muted-foreground">
                    暂无管理员用户
                  </div>
                ) : (
                  <ul className="divide-y">
                    {adminUsers.map((user, index) => (
                      <li key={index} className="flex items-center justify-between p-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono">{user.value}</span>
                          {user.isNew && (
                            <Badge variant="outline" className="text-xs">新增</Badge>
                          )}
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveUser(index)}
                          className="text-muted-foreground hover:text-destructive"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              
              {/* 保存按钮 */}
              <div className="flex justify-end">
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      保存中...
                    </>
                  ) : (
                    <>
                      <Save className="h-4 w-4 mr-2" />
                      保存配置
                    </>
                  )}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      
      {/* 命令说明 */}
      <Card>
        <CardHeader>
          <CardTitle>可用命令</CardTitle>
          <CardDescription>
            管理员可以在企微中使用以下命令
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-md">
              <code className="bg-primary/10 text-primary px-2 py-1 rounded font-mono text-sm">/ping</code>
              <div>
                <p className="font-medium">健康检查</p>
                <p className="text-sm text-muted-foreground">快速检测服务响应，返回延迟时间</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-md">
              <code className="bg-primary/10 text-primary px-2 py-1 rounded font-mono text-sm">/status</code>
              <div>
                <p className="font-medium">系统状态</p>
                <p className="text-sm text-muted-foreground">查看详细的服务状态，包括 Bot 数量、今日消息统计、成功率等</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
