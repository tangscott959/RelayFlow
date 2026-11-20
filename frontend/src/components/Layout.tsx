import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { clearRevealedApiKey, peekRevealedApiKey } from '../auth/session'

export function Layout() {
  const { session, signOut } = useAuth()
  const [revealedKey, setRevealedKey] = useState<string | null>(() => peekRevealedApiKey())
  if (!session) {
    return null
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <strong>RelayFlow</strong>
            <span>Operator console</span>
          </div>
        </div>
        <nav>
          <NavLink to="/endpoints">Endpoints</NavLink>
          <NavLink to="/ingest">Ingest</NavLink>
          <NavLink to="/deliveries">Deliveries</NavLink>
        </nav>
        <div className="tenant-card">
          <span className="muted">Workspace</span>
          <strong>{session.tenant.name}</strong>
          <code>{session.tenant.api_key_prefix}</code>
          <button type="button" className="linkish" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="main">
        {revealedKey ? (
          <div className="banner warn" role="status">
            Tenant API key (store it now; the server will not show it again): <code>{revealedKey}</code>{' '}
            <button
              type="button"
              className="linkish"
              onClick={() => {
                clearRevealedApiKey()
                setRevealedKey(null)
              }}
            >
              Dismiss
            </button>
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  )
}
