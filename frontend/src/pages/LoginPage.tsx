import { type FormEvent, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { ApiError, createTenant } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { stashRevealedApiKey } from '../auth/session'

export function LoginPage() {
  const { session, signIn, error: restoreError } = useAuth()
  const [workspace, setWorkspace] = useState('')
  const [pastedKey, setPastedKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(restoreError)

  if (session) {
    return <Navigate to="/endpoints" replace />
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await createTenant(workspace)
      stashRevealedApiKey(created.api_key)
      await signIn(created.api_key)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Could not create a tenant.')
    } finally {
      setBusy(false)
    }
  }

  async function onPaste(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(pastedKey)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in with that key.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <div className="gate-card">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <strong>RelayFlow</strong>
            <span>Sign in with a tenant API key</span>
          </div>
        </div>
        {error ? (
          <div className="banner danger" role="alert">
            {error}
          </div>
        ) : null}
        <form onSubmit={onCreate} className="stack">
          <h2>Create a workspace</h2>
          <label>
            Tenant name
            <input
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              placeholder="acme"
              autoComplete="organization"
              required
            />
          </label>
          <button type="submit" disabled={busy || !workspace.trim()}>
            Create tenant
          </button>
        </form>
        <form onSubmit={onPaste} className="stack">
          <h2>Use an existing key</h2>
          <label>
            API key
            <input
              value={pastedKey}
              onChange={(e) => setPastedKey(e.target.value)}
              placeholder="rfk_…"
              autoComplete="off"
              spellCheck={false}
              required
            />
          </label>
          <button type="submit" className="secondary" disabled={busy || !pastedKey.trim()}>
            Sign in
          </button>
        </form>
      </div>
    </div>
  )
}
