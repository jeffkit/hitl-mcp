import { Link, useLocation } from 'react-router-dom'
import { Plug, MessageSquare } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/engines', label: '引擎管理', icon: Plug },
  { path: '/sessions', label: '会话调试', icon: MessageSquare },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  return (
    <div className="min-h-screen bg-background">
      {/* 侧边栏 */}
      <aside className="fixed left-0 top-0 bottom-0 w-64 border-r border-border bg-card">
        {/* Logo */}
        <div className="h-16 flex items-center px-6 border-b border-border">
          <div className="w-8 h-8 bg-gradient-to-br from-purple-500 to-blue-500 rounded-lg flex items-center justify-center mr-3">
            <Plug className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-lg">HIL Console</span>
        </div>

        {/* 导航菜单 */}
        <nav className="p-4 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  'flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            )
          })}
        </nav>
      </aside>

      {/* 主内容区 */}
      <main className="ml-64 min-h-screen">
        {children}
      </main>
    </div>
  )
}
