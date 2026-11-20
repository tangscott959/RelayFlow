import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { ApiError, readMe } from '../api/client'
import type { Tenant } from '../api/types'
import { clearStoredApiKey, loadStoredApiKey, persistApiKey } from './session'

type AuthState = {
  apiKey: string
  tenant: Tenant
}

type AuthContextValue = {
  ready: boolean
  session: AuthState | null
  error: string | null
  signIn: (apiKey: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [session, setSession] = useState<AuthState | null>(null)
  const [error, setError] = useState<string | null>(null)

  const signIn = useCallback(async (apiKey: string) => {
    const trimmed = apiKey.trim()
    const tenant = await readMe(trimmed)
    persistApiKey(trimmed)
    setSession({ apiKey: trimmed, tenant })
    setError(null)
  }, [])

  const signOut = useCallback(() => {
    clearStoredApiKey()
    setSession(null)
    setError(null)
  }, [])

  useEffect(() => {
    const stored = loadStoredApiKey()
    if (!stored) {
      setReady(true)
      return
    }
    void readMe(stored)
      .then((tenant) => {
        setSession({ apiKey: stored, tenant })
      })
      .catch((err: unknown) => {
        clearStoredApiKey()
        if (err instanceof ApiError && err.status === 401) {
          setError('Stored API key was rejected. Sign in again.')
        } else {
          setError('Could not reach the API. Is the web service running?')
        }
      })
      .finally(() => {
        setReady(true)
      })
  }, [])

  const value = useMemo(
    () => ({ ready, session, error, signIn, signOut }),
    [ready, session, error, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
