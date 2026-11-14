import assert from 'node:assert/strict'
import test from 'node:test'
import { loadSource } from './load-source.mjs'

const { apiClient } = await loadSource('src/api/client.ts')
const { getHerbs, getHerb, getHerbFilters } = await loadSource('src/api/herb.ts')
const response = (config, data = {total:299,items:[{id:'tcmp-298',image:'/plant.jpg'}]}) =>
  ({config,data,status:200,statusText:'OK',headers:{}})

test('concurrent and repeated equivalent gallery requests share one HTTP call', async () => {
  const original = apiClient.defaults.adapter
  let calls = 0
  apiClient.defaults.adapter = async config => {calls++;return response(config)}
  try {
    const [first,second] = await Promise.all([
      getHerbs({q:'cache-query',sort:'featured',recent_ids:'tcmp-001'}),
      getHerbs({sort:'featured',q:'cache-query',family:''}),
    ])
    await getHerbs({q:'cache-query',sort:'featured',recent_ids:'tcmp-298'})
    assert.equal(calls,1)
    assert.deepEqual(first,second)
    assert.equal(first.items[0].image,'http://localhost:8000/plant.jpg')
    await getHerbs({q:'cache-query',sort:'recent',recent_ids:'tcmp-001'})
    await getHerbs({q:'cache-query',sort:'recent',recent_ids:'tcmp-298'})
    assert.equal(calls,3,'recent ordering remains sensitive to the actual recent IDs')
  } finally {apiClient.defaults.adapter=original}
})

test('detail and filter requests also deduplicate without mixing response types', async () => {
  const original = apiClient.defaults.adapter
  const calls = []
  apiClient.defaults.adapter = async config => {
    calls.push(config.url)
    return response(config,config.url.endsWith('/filters') ? {total:299,families:['Lamiaceae']} : {id:'cache-detail',image:'/detail.jpg'})
  }
  try {
    const [detail,filters] = await Promise.all([getHerb('cache-detail'),getHerbFilters(),getHerb('cache-detail'),getHerbFilters()])
    assert.equal(calls.length,2)
    assert.equal(detail.id,'cache-detail')
    assert.deepEqual(filters.families,['Lamiaceae'])
  } finally {apiClient.defaults.adapter=original}
})

test('failed plant loads do not poison retry requests', async () => {
  const original=apiClient.defaults.adapter
  let calls=0
  apiClient.defaults.adapter=async config=>{if(++calls===1)throw new Error('temporary outage');return response(config)}
  try {
    await assert.rejects(getHerbs({q:'retry-cache'}),/temporary outage/)
    assert.equal((await getHerbs({q:'retry-cache'})).total,299)
    assert.equal(calls,2)
  } finally {apiClient.defaults.adapter=original}
})

test('cached public data expires and the cache is bounded', async () => {
  const original=apiClient.defaults.adapter,clock=Date.now
  let now=clock(),calls=0
  Date.now=()=>now
  apiClient.defaults.adapter=async config=>{calls++;return response(config)}
  try {
    await getHerbs({q:'expiry-cache'})
    now+=10001
    await getHerbs({q:'expiry-cache'})
    assert.equal(calls,2)
    for(let n=0;n<41;n++)await getHerbs({q:'bounded-cache-'+n})
    await getHerbs({q:'bounded-cache-0'})
    assert.equal(calls,44,'old query entries are evicted')
  } finally {apiClient.defaults.adapter=original;Date.now=clock}
})
