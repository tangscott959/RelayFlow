const API_KEY_STORAGE = 'relayflow.apiKey'
const REVEALED_KEY_STORAGE = 'relayflow.revealedApiKey'

export function loadStoredApiKey(): string | null {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE)
  } catch {
    return null
  }
}

export function persistApiKey(apiKey: string): void {
  window.localStorage.setItem(API_KEY_STORAGE, apiKey)
}

export function clearStoredApiKey(): void {
  window.localStorage.removeItem(API_KEY_STORAGE)
  window.sessionStorage.removeItem(REVEALED_KEY_STORAGE)
}

export function stashRevealedApiKey(apiKey: string): void {
  window.sessionStorage.setItem(REVEALED_KEY_STORAGE, apiKey)
}

export function peekRevealedApiKey(): string | null {
  return window.sessionStorage.getItem(REVEALED_KEY_STORAGE)
}

export function clearRevealedApiKey(): void {
  window.sessionStorage.removeItem(REVEALED_KEY_STORAGE)
}
