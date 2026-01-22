import { useState, useEffect } from 'react'
import { Layout, Menu, Input, Button, message, Modal, Form } from 'antd'
import {
  DashboardOutlined,
  CloudServerOutlined,
  HistoryOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { Dashboard } from './pages/Dashboard'
import { Tunnels } from './pages/Tunnels'
import { RequestLogs } from './pages/RequestLogs'
import { setApiKey, updateApiBaseUrl } from './api/client'
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
  {
    key: 'logs',
    icon: <HistoryOutlined />,
    label: '请求历史',
  },
]

function App() {
  const [selectedKey, setSelectedKey] = useState('dashboard')
  const [selectedTunnelDomain, setSelectedTunnelDomain] = useState<string | null>(null)
  const [apiKey, setApiKeyState] = useState<string | null>(
    localStorage.getItem('tunely_api_key')
  )
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [apiBaseUrl, setApiBaseUrl] = useState<string>(
    localStorage.getItem('tunely_api_base_url') || ''
  )
  const [apiBaseUrlInput, setApiBaseUrlInput] = useState('')
  const [configModalVisible, setConfigModalVisible] = useState(false)

  useEffect(() => {
    // 检查是否有 API Key
    const stored = localStorage.getItem('tunely_api_key')
    if (stored) {
      setApiKeyState(stored)
    }
    // 检查是否有 API Base URL
    const storedBaseUrl = localStorage.getItem('tunely_api_base_url')
    if (storedBaseUrl) {
      setApiBaseUrl(storedBaseUrl)
    }
  }, [])


  const handleSaveConfig = () => {
    if (apiBaseUrlInput.trim()) {
      updateApiBaseUrl(apiBaseUrlInput.trim())
      setApiBaseUrl(apiBaseUrlInput.trim())
      message.success('后端服务地址已更新，请刷新页面')
    }
    if (apiKeyInput.trim()) {
      setApiKey(apiKeyInput.trim())
      setApiKeyState(apiKeyInput.trim())
      message.success('API Key 已设置')
    }
    setConfigModalVisible(false)
    setApiBaseUrlInput('')
    setApiKeyInput('')
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ color: '#fff', fontSize: 18, fontWeight: 'bold' }}>
          Tunely Server - 管理台
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {apiBaseUrl && (
            <span style={{ color: '#fff', marginRight: 8, fontSize: 12 }}>
              后端: <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: 2 }}>
                {apiBaseUrl.length > 30 ? apiBaseUrl.substring(0, 30) + '...' : apiBaseUrl}
              </code>
            </span>
          )}
          {apiKey && (
            <span style={{ color: '#fff', marginRight: 8, fontSize: 12 }}>
              Key: <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: 2 }}>
                {apiKey.substring(0, 10)}...
              </code>
            </span>
          )}
          <Button
            size="small"
            icon={<SettingOutlined />}
            onClick={() => {
              setApiBaseUrlInput(apiBaseUrl)
              setApiKeyInput(apiKey || '')
              setConfigModalVisible(true)
            }}
          >
            配置
          </Button>
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
            {selectedKey === 'tunnels' && (
              <Tunnels onViewLogs={(domain) => {
                setSelectedTunnelDomain(domain)
                setSelectedKey('logs')
              }} />
            )}
            {selectedKey === 'logs' && <RequestLogs tunnelDomain={selectedTunnelDomain} />}
          </Content>
        </Layout>
      </Layout>

      <Modal
        title="配置后端服务"
        open={configModalVisible}
        onOk={handleSaveConfig}
        onCancel={() => {
          setConfigModalVisible(false)
          setApiBaseUrlInput('')
          setApiKeyInput('')
        }}
        okText="保存"
        cancelText="取消"
      >
        <Form layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="后端服务地址（API Base URL）">
            <Input
              placeholder="例如: http://21.6.243.90:8083/api 或 /tun-console/api"
              value={apiBaseUrlInput}
              onChange={(e) => setApiBaseUrlInput(e.target.value)}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
              留空则使用默认值（相对路径）
            </div>
          </Form.Item>
          <Form.Item label="API Key">
            <Input.Password
              placeholder="输入 API Key"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default App
