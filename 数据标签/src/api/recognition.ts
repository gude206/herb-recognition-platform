import axios from 'axios'
import { apiClient, wait } from './client'
import { mockHerbs } from '../data/mockHerbs'
import type { RecognitionResult, RecognitionSample, TopPrediction } from '../types/recognition'

// Recognition uses the real model by default; other pages can retain mock data.
export const useMockRecognition = import.meta.env.VITE_MOCK_RECOGNITION === 'true'

export function findKnowledgeHerb(prediction?: TopPrediction) {
  if (!prediction) return undefined
  const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '')
  return mockHerbs.find(herb => herb.id === prediction.herb_id || (
    prediction.latin_name && normalize(herb.latinName) === normalize(prediction.latin_name)
  ))
}

export function recognitionError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (typeof error.response?.data?.detail === 'string') return error.response.data.detail
    if (!error.response) return '无法连接识别服务，请启动 TCMP-300 中的 start-api.ps1 后重试'
  }
  return error instanceof Error ? error.message : '识别失败，请重新选择图片后重试'
}

export async function getRecognitionSamples(): Promise<RecognitionSample[]> {
  if (useMockRecognition) return mockHerbs.slice(0, 4).map(herb => ({herb_id: herb.id, name: herb.name, image_url: herb.image}))
  const { data } = await apiClient.get<RecognitionSample[]>('/api/v1/recognition/samples')
  return data.map(sample => ({ ...sample, image_url: new URL(sample.image_url, apiClient.defaults.baseURL).href }))
}

export async function predictHerb(file: File): Promise<RecognitionResult> {
  if (!useMockRecognition) {
    const body = new FormData()
    body.append('file', file)
    return (await apiClient.post<RecognitionResult>('/api/v1/predict', body, {timeout: 60000})).data
  }
  await wait(1400)
  const herb = mockHerbs.find(item => file.name.includes(item.name)) || mockHerbs[0]
  const alternatives = mockHerbs.filter(item => item.id !== herb.id).slice(0, 4)
  return {
    prediction: {herb_id: herb.id, name: herb.name, latin_name: herb.latinName, confidence: 0.928},
    top_k: [{herb_id: herb.id, name: herb.name, confidence: 0.928}, ...alternatives.map((item, index) => (
      {herb_id: item.id, name: item.name, confidence: [0.041, 0.018, 0.008, 0.005][index]}
    ))],
  }
}
