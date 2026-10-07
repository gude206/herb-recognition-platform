export function readRecentHerbs(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem('herb-recent') || '[]')
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string').slice(0, 10) : []
  } catch { return [] }
}

export function addRecentHerb(id: string) {
  const history = readRecentHerbs()
  localStorage.setItem('herb-recent', JSON.stringify([id, ...history.filter((item) => item !== id)].slice(0, 10)))
}
