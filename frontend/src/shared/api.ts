import axios from 'axios'

export const apiBase =
  import.meta.env.VITE_API_BASE ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

const USER_ID_KEY = 'tts_user_id'

const fallbackUuid = (): string => {
  const now = Date.now().toString(16)
  const rand = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0')
  return `${now}-${rand()}-${rand()}-${rand()}`
}

export const getOrCreateUserId = (): string => {
  if (typeof window === 'undefined') return fallbackUuid()

  const existing = window.localStorage.getItem(USER_ID_KEY)
  if (existing) return existing

  const generated = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : fallbackUuid()

  window.localStorage.setItem(USER_ID_KEY, generated)
  return generated
}

export const buildAuthHeaders = (headers?: HeadersInit): Headers => {
  const merged = new Headers(headers)
  merged.set('X-User-Id', getOrCreateUserId())
  return merged
}

export const apiClient = axios.create({
  baseURL: apiBase,
})

apiClient.interceptors.request.use((config) => {
  config.headers = config.headers ?? {}
  config.headers['X-User-Id'] = getOrCreateUserId()
  return config
})

export const apiFetch = (path: string, init?: RequestInit): Promise<Response> => {
  const url = path.startsWith('http') ? path : `${apiBase}${path.startsWith('/') ? path : `/${path}`}`
  return fetch(url, {
    ...init,
    headers: buildAuthHeaders(init?.headers),
  })
}
