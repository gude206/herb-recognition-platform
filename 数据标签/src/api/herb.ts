import { apiClient } from './client'
import type { Herb, HerbFilters, HerbListResponse, HerbQuery } from '../types/herb'
import { readRecentHerbs } from '../utils/history'

const withImageURL = (herb: Herb): Herb => ({
  ...herb, image: herb.image ? new URL(herb.image, apiClient.defaults.baseURL).href : '',
})

// Public plant data only: share concurrent requests and short-lived results
// between gallery/detail visits. Failed requests are always retryable.
const requests = new Map<string, { expires: number; promise: Promise<unknown> }>()
function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
  const existing = requests.get(key)
  if (existing && existing.expires > Date.now()) return existing.promise as Promise<T>
  const entry = { expires: Infinity, promise: Promise.resolve().then(load) as Promise<unknown> }
  requests.delete(key)
  requests.set(key, entry)
  if (requests.size > 40) requests.delete(requests.keys().next().value!)
  entry.promise = entry.promise.then(value => { entry.expires = Date.now() + 10000; return value }, error => {
    if (requests.get(key) === entry) requests.delete(key)
    throw error
  })
  return entry.promise as Promise<T>
}

export async function getHerbs(params: HerbQuery = {}): Promise<HerbListResponse> {
  const query = Object.fromEntries(Object.entries(params)
    .filter(([key, value]) => value !== undefined && value !== '' && (key !== 'recent_ids' || params.sort === 'recent'))
    .sort(([a], [b]) => a.localeCompare(b)))
  return cached('list:' + JSON.stringify(query), async () => {
    const {data} = await apiClient.get<HerbListResponse>('/api/v1/herbs', {params: query})
    return {...data, items: data.items.map(withImageURL)}
  })
}

export async function getHerbFilters(): Promise<HerbFilters> {
  return cached('filters', async () => (await apiClient.get<HerbFilters>('/api/v1/herbs/filters')).data)
}

export async function getHerb(id: string): Promise<Herb | undefined> {
  return cached('detail:' + id, async () => {
    const {data} = await apiClient.get<Herb>('/api/v1/herbs/'+encodeURIComponent(id))
    return withImageURL(data)
  })
}

export async function getRecentHistory(limit = 5): Promise<Herb[]> {
  const records = await Promise.all(readRecentHerbs().slice(0, limit).map(id => getHerb(id).catch(() => undefined)))
  return records.filter((herb): herb is Herb => Boolean(herb))
}
