import { apiClient, wait } from './client'
import { mockHerbs, effectOptions, partOptions, propertyOptions } from '../data/mockHerbs'
import type { Herb, HerbFilters, HerbListResponse, HerbQuery } from '../types/herb'
import { readRecentHerbs } from '../utils/history'
import { matchesHerbQuery } from '../utils/herbSearch'

const useMockHerbs = import.meta.env.VITE_MOCK_HERBS === 'true'
const withImageURL = (herb: Herb): Herb => ({
  ...herb, image: herb.image ? new URL(herb.image, apiClient.defaults.baseURL).href : '',
})

export async function getHerbs(params: HerbQuery = {}): Promise<HerbListResponse> {
  if (!useMockHerbs) {
    const {data} = await apiClient.get<HerbListResponse>('/api/v1/herbs', {params})
    return {...data, items: data.items.map(withImageURL)}
  }
  await wait(150)
  const q = params.q?.trim().toLowerCase()
  let items = mockHerbs.filter(h => matchesHerbQuery(h,q)
    && (!params.family || h.family === params.family) && (!params.effect || h.effects.includes(params.effect))
    && (!params.property || h.property === params.property) && (!params.part || h.medicinalPart.includes(params.part)))
  if (params.sort === 'name') items = [...items].sort((a,b) => a.name.localeCompare(b.name, 'zh-CN'))
  const total = items.length, size = params.page_size || 24, page = Math.min(params.page || 1, Math.max(1, Math.ceil(total / size)))
  return {total, collectionTotal: mockHerbs.length, page, pageSize: size, items: items.slice((page-1)*size, page*size)}
}

export async function getHerbFilters(): Promise<HerbFilters> {
  if (!useMockHerbs) return (await apiClient.get<HerbFilters>('/api/v1/herbs/filters')).data
  return {total: mockHerbs.length, distributionCount: 0, families: [...new Set(mockHerbs.map(h => h.family))],
    genera: [], regions: [], properties: propertyOptions, parts: partOptions, effects: effectOptions}
}

export async function getHerb(id: string): Promise<Herb | undefined> {
  if (useMockHerbs) return mockHerbs.find(h => h.id === id)
  const {data} = await apiClient.get<Herb>('/api/v1/herbs/'+encodeURIComponent(id))
  return withImageURL(data)
}

export async function getRecentHistory(limit = 5): Promise<Herb[]> {
  const records = await Promise.all(readRecentHerbs().slice(0, limit).map(id => getHerb(id).catch(() => undefined)))
  return records.filter((herb): herb is Herb => Boolean(herb))
}
