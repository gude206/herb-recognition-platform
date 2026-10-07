import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  timeout: 15000,
})

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
export const wait = (ms = 500) => new Promise((resolve) => window.setTimeout(resolve, ms))
