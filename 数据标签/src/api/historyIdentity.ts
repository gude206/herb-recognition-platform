const TOKEN_KEY = 'herbal-knowledge-history-token-v1'
let memoryToken = ''

export function getHistoryToken(): string {
  if (memoryToken) return memoryToken
  try {
    const saved = localStorage.getItem(TOKEN_KEY)
    if (saved && /^[a-f0-9]{64}$/.test(saved)) return (memoryToken = saved)
  } catch { /* Requests can still use a temporary identity when storage is unavailable. */ }
  memoryToken = Array.from(crypto.getRandomValues(new Uint8Array(32)), value => value.toString(16).padStart(2, '0')).join('')
  try { localStorage.setItem(TOKEN_KEY, memoryToken) } catch { /* Temporary identity lasts until refresh. */ }
  return memoryToken
}

export function rotateHistoryToken() {
  memoryToken = ''
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* Browser storage may be disabled. */ }
  return getHistoryToken()
}
