// A detail page can return only to the local gallery, never to arbitrary URLs.
export function galleryReturnTo(value: unknown): string {
  if (typeof value !== 'string' || /[\\\u0000-\u0020]/.test(value)) return '/herbs'
  try {
    const url = new URL(value, 'https://gallery.invalid')
    if (url.origin !== 'https://gallery.invalid' || url.pathname !== '/herbs') return '/herbs'
    if (!value.startsWith('/herbs') || url.hash) return '/herbs'
    return url.pathname + url.search
  } catch { return '/herbs' }
}

export function returnToFromState(state: unknown): string {
  return galleryReturnTo(state && typeof state === 'object' && 'galleryReturnTo' in state
    ? state.galleryReturnTo : undefined)
}
