import type { Herb } from '../types/herb'

export function matchesHerbQuery(herb: Herb, query = ''): boolean {
  const q = query.trim().toLowerCase()
  return !q || [herb.name, herb.latinName, ...herb.aliases, ...herb.effects,
    ...(herb.materials?.map(material => material['药材名称'] || '') || [])]
    .join(' ').toLowerCase().includes(q)
}
