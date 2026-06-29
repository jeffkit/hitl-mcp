import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { EnginesPage } from '@/pages/Engines'
import { SessionsPage } from '@/pages/Sessions'

function App() {
  return (
    <BrowserRouter basename="/console">
      <Routes>
        <Route path="/" element={<Navigate to="/engines" replace />} />
        <Route
          path="/engines"
          element={
            <Layout>
              <EnginesPage />
            </Layout>
          }
        />
        <Route
          path="/sessions"
          element={
            <Layout>
              <SessionsPage />
            </Layout>
          }
        />
        <Route path="*" element={<Navigate to="/engines" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
