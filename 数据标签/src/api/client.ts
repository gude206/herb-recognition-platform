import axios from 'axios'
import { getHistoryToken } from './historyIdentity'
import { getSession, setSession } from './session'

function apiBaseURL() {
  const configured = import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000'
  if (typeof window === 'undefined') return configured
  const url = new URL(configured, window.location.origin)
  if (['localhost','127.0.0.1'].includes(url.hostname) && ['localhost','127.0.0.1'].includes(window.location.hostname)) url.hostname = window.location.hostname
  return url.href.replace(/\/$/, '')
}

export const apiClient = axios.create({
  baseURL: apiBaseURL(),
  timeout: 15000,
  withCredentials: true,
})

apiClient.interceptors.request.use(config => {
  if (config.url?.startsWith('/api/v1/history') || config.url === '/api/v1/chat' || config.url?.startsWith('/api/v1/agent/chat') || config.url === '/api/v1/text/classify' || config.url === '/api/v1/predict'
    || config.url === '/api/v1/auth/login' || config.url === '/api/v1/auth/register') {
    config.headers.set('X-History-Token', getHistoryToken())
  }
  const session = getSession()
  if (session.csrfToken && !['get','head','options'].includes(config.method || 'get')) config.headers.set('X-CSRF-Token', session.csrfToken)
  return config
})

apiClient.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401 && getSession().user) setSession(null)
  return Promise.reject(error)
})

export const useMock = import.meta.env?.VITE_USE_MOCK !== 'false'
export const wait = (ms = 500) => new Promise((resolve) => window.setTimeout(resolve, ms))
