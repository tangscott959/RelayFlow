import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider, useAuth } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { DeliveriesPage } from './pages/DeliveriesPage'
import { EndpointsPage } from './pages/EndpointsPage'
import { IngestPage } from './pages/IngestPage'
import { LoginPage } from './pages/LoginPage'

function Guard({ children }: { children: ReactNode }) {
  const { ready, session } = useAuth()
  if (!ready) {
    return <p className="boot">Loading session…</p>
  }
  if (!session) {
    return <Navigate to="/login" replace />
  }
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <Guard>
                <Layout />
              </Guard>
            }
          >
            <Route index element={<Navigate to="/endpoints" replace />} />
            <Route path="endpoints" element={<EndpointsPage />} />
            <Route path="ingest" element={<IngestPage />} />
            <Route path="deliveries" element={<DeliveriesPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
