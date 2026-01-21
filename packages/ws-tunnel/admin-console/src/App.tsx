import { useState, useEffect } from 'react'
import { Layout, Menu, Card, Input, Button, message } from 'antd'
import {
  DashboardOutlined,
  CloudServerOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { Dashboard } from './pages/Dashboard'
import { Tunnels } from './pages/Tunnels'
import { setApiKey } from './api/client'
import type { MenuProps } from 'antd'

const { Header, Content, Sider } = Layout

type MenuItem = Required<MenuProps>['items'][number]

const menuItems: MenuItem[] = [
  {
    key: 'dashboard',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: 'tunnels',
    icon: <CloudServerOutlined />,
    label: '隧道管理',
  },
]

function App() {
  const [selectedKey, setSelectedKey] = useState('dashboard')
  const [apiKey, setApiKeyState] = useState<string | null>(
    localStorage.getItem('tunely_api_key')
  )
  const [apiKeyInput, setApiKeyInput] = useState('')

  useEffect(() => {
    // 检查是否有 API Key
    const stored = localStorage.getItem('tunely_api_key')
    if (stored) {
      setApiKeyState(stored)
    }
  }, [])

  const handleSetApiKey = () => {
    if (!apiKeyInput.trim()) {
      message.warning('请输入 API Key')
      return
    }
    setApiKey(apiKeyInput.trim())
    setApiKeyState(apiKeyInput.trim())
    setApiKeyInput('')
    message.success('API Key 已设置')
  }

  const handleClearApiKey = () => {
    setApiKey(null)
    setApiKeyState(null)
    message.success('API Key 已清除')
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ color: '#fff', fontSize: 18, fontWeight: 'bold' }}>
          Tunely Server - 管理台
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {apiKey ? (
            <>
              <span style={{ color: '#fff', marginRight: 8 }}>
                API Key: <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: 2 }}>
                  {apiKey.substring(0, 10)}...
                </code>
              </span>
              <Button size="small" onClick={handleClearApiKey}>
                清除
              </Button>
            </>
          ) : (
            <>
              <Input
                placeholder="输入 API Key"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                onPressEnter={handleSetApiKey}
                style={{ width: 200 }}
                size="small"
              />
              <Button type="primary" size="small" onClick={handleSetApiKey}>
                设置
              </Button>
            </>
          )}
        </div>
      </Header>
      <Layout>
        <Sider width={200} style={{ background: '#fff' }}>
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems}
            onClick={({ key }) => setSelectedKey(key)}
            style={{ height: '100%', borderRight: 0 }}
          />
        </Sider>
        <Layout style={{ padding: '24px' }}>
          <Content
            style={{
              background: '#fff',
              padding: 24,
              margin: 0,
              minHeight: 280,
            }}
          >
            {selectedKey === 'dashboard' && <Dashboard />}
            {selectedKey === 'tunnels' && <Tunnels />}
          </Content>
        </Layout>
      </Layout>
    </Layout>
  )
}

export default App
