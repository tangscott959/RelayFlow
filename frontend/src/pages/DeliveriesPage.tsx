import { useEffect, useState } from 'react'

import { ApiError, listDeliveries, listEndpoints, resendDelivery } from '../api/client'
import type { DeliveryAttempt, DeliveryStatus, Endpoint } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const PAGE_SIZE = 20

export function DeliveriesPage() {
  const { session } = useAuth()
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [endpointId, setEndpointId] = useState('')
  const [status, setStatus] = useState<DeliveryStatus | ''>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [items, setItems] = useState<DeliveryAttempt[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    if (!session) {
      return
    }
    void listEndpoints(session.apiKey)
      .then((rows) => {
        setEndpoints(rows)
        setEndpointId((current) => current || rows[0]?.id || '')
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : 'Failed to load endpoints.')
      })
  }, [session])

  useEffect(() => {
    if (!session || !endpointId) {
      setItems([])
      setTotal(0)
      return
    }
    void listDeliveries(session.apiKey, endpointId, {
      page,
      page_size: PAGE_SIZE,
      status,
    })
      .then((payload) => {
        setItems(payload.items)
        setTotal(payload.total)
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : 'Failed to load deliveries.')
      })
  }, [session, endpointId, page, status])

  if (!session) {
    return null
  }
  const apiKey = session.apiKey

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  async function onResend(attempt: DeliveryAttempt) {
    setBusyId(attempt.id)
    setError(null)
    setNotice(null)
    try {
      const replay = await resendDelivery(apiKey, attempt.id)
      setNotice(`Requeued as attempt ${replay.attempt_number} (${replay.id}).`)
      const payload = await listDeliveries(apiKey, endpointId, {
        page,
        page_size: PAGE_SIZE,
        status,
      })
      setItems(payload.items)
      setTotal(payload.total)
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Resend failed.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section>
      <header className="page-head">
        <div>
          <h1>Deliveries</h1>
          <p className="muted">Paginated attempt log. Failed rows can be resent from the dead-letter queue.</p>
        </div>
      </header>
      {error ? (
        <div className="banner danger" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="banner ok" role="status">
          {notice}
        </div>
      ) : null}

      <div className="toolbar">
        <label>
          Endpoint
          <select
            value={endpointId}
            onChange={(e) => {
              setEndpointId(e.target.value)
              setPage(1)
            }}
          >
            {endpoints.length === 0 ? <option value="">No endpoints</option> : null}
            {endpoints.map((endpoint) => (
              <option key={endpoint.id} value={endpoint.id}>
                {endpoint.target_url}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as DeliveryStatus | '')
              setPage(1)
            }}
          >
            <option value="">All</option>
            <option value="pending">pending</option>
            <option value="delivered">delivered</option>
            <option value="failed">failed</option>
            <option value="retrying">retrying</option>
          </select>
        </label>
      </div>

      <div className="panel">
        {items.length === 0 ? (
          <p className="muted">No delivery attempts for this filter.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>HTTP</th>
                <th>Duration</th>
                <th>Event</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{attempt.attempt_number}</td>
                  <td>
                    <span className={`pill ${attempt.status}`}>{attempt.status}</span>
                  </td>
                  <td>{attempt.http_status ?? '—'}</td>
                  <td>{attempt.duration_ms != null ? `${attempt.duration_ms} ms` : '—'}</td>
                  <td>
                    <code>{attempt.event_id.slice(0, 8)}</code>
                  </td>
                  <td>{new Date(attempt.created_at).toLocaleString()}</td>
                  <td>
                    {attempt.status === 'failed' ? (
                      <button
                        type="button"
                        className="secondary"
                        disabled={busyId === attempt.id}
                        onClick={() => void onResend(attempt)}
                      >
                        Resend
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="pager">
          <span className="muted">
            {total} total · page {page} / {pageCount}
          </span>
          <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <button
            type="button"
            className="secondary"
            disabled={page >= pageCount}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  )
}
