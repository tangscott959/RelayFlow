import { type FormEvent, useEffect, useState } from 'react'

import { ApiError, createEndpoint, listEndpoints, patchEndpoint } from '../api/client'
import type { Endpoint, EndpointStatus } from '../api/types'
import { useAuth } from '../auth/AuthContext'

function parseEvents(raw: string): string[] {
  const parts = raw
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  return parts.length === 0 ? ['*'] : parts
}

function secretPreview(secret: string): string {
  if (secret.length <= 12) {
    return secret
  }
  return `${secret.slice(0, 8)}…${secret.slice(-4)}`
}

export function EndpointsPage() {
  const { session } = useAuth()
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [targetUrl, setTargetUrl] = useState('https://example.com/hooks')
  const [events, setEvents] = useState('*')
  const [rate, setRate] = useState(10)
  const [createdSecret, setCreatedSecret] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function refresh(apiKey: string) {
    const rows = await listEndpoints(apiKey)
    setEndpoints(rows)
  }

  useEffect(() => {
    if (!session) {
      return
    }
    void refresh(session.apiKey).catch((err: unknown) => {
      setError(err instanceof ApiError ? err.message : 'Failed to load endpoints.')
    })
  }, [session])

  if (!session) {
    return null
  }
  const apiKey = session.apiKey

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await createEndpoint(apiKey, {
        target_url: targetUrl.trim(),
        subscribed_events: parseEvents(events),
        rate_limit_per_sec: rate,
      })
      setCreatedSecret(created.secret_key)
      setTargetUrl('https://example.com/hooks')
      await refresh(apiKey)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Could not create the endpoint.')
    } finally {
      setBusy(false)
    }
  }

  async function setStatus(endpoint: Endpoint, status: EndpointStatus) {
    setError(null)
    try {
      await patchEndpoint(apiKey, endpoint.id, { status })
      await refresh(apiKey)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Could not update status.')
    }
  }

  return (
    <section>
      <header className="page-head">
        <div>
          <h1>Endpoints</h1>
          <p className="muted">Subscriber URLs that receive signed POSTs.</p>
        </div>
      </header>
      {error ? (
        <div className="banner danger" role="alert">
          {error}
        </div>
      ) : null}
      {createdSecret ? (
        <div className="banner warn" role="status">
          Signing secret shown after create. Copy it: <code>{createdSecret}</code>
        </div>
      ) : null}

      <form className="panel form-grid" onSubmit={onCreate}>
        <h2>Register endpoint</h2>
        <label>
          Target URL
          <input
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            placeholder="https://example.com/hooks"
            required
          />
        </label>
        <label>
          Subscribed events
          <input
            value={events}
            onChange={(e) => setEvents(e.target.value)}
            placeholder="* or agent.completed, order.created"
          />
        </label>
        <label>
          Rate limit / sec
          <input
            type="number"
            min={0}
            max={10000}
            value={rate}
            onChange={(e) => setRate(Number(e.target.value))}
          />
        </label>
        <button type="submit" disabled={busy}>
          Create endpoint
        </button>
      </form>

      <div className="panel">
        {endpoints.length === 0 ? (
          <p className="muted">No endpoints yet. Register one to start fan-out.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>URL</th>
                <th>Events</th>
                <th>Status</th>
                <th>Secret</th>
                <th>Rate</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {endpoints.map((endpoint) => (
                <tr key={endpoint.id}>
                  <td>
                    <code>{endpoint.target_url}</code>
                  </td>
                  <td>{endpoint.subscribed_events.join(', ')}</td>
                  <td>
                    <span className={`pill ${endpoint.status}`}>{endpoint.status}</span>
                  </td>
                  <td>
                    <code>{secretPreview(endpoint.secret_key)}</code>
                  </td>
                  <td>{endpoint.rate_limit_per_sec}/s</td>
                  <td className="actions">
                    {endpoint.status !== 'active' ? (
                      <button type="button" className="secondary" onClick={() => void setStatus(endpoint, 'active')}>
                        Resume
                      </button>
                    ) : null}
                    {endpoint.status !== 'paused' ? (
                      <button type="button" className="secondary" onClick={() => void setStatus(endpoint, 'paused')}>
                        Pause
                      </button>
                    ) : null}
                    {endpoint.status !== 'disabled' ? (
                      <button type="button" className="danger" onClick={() => void setStatus(endpoint, 'disabled')}>
                        Disable
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
