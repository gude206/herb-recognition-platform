import { isAxiosError } from 'axios'
import { apiClient } from './client'
import type { Article } from '../types/article'

const withImageURL = (article: Article): Article => ({ ...article,
  image: article.image ? new URL(article.image, apiClient.defaults.baseURL).href : '' })

export function knowledgeError(error: unknown): string {
  if (isAxiosError(error)) {
    if (typeof error.response?.data?.detail === 'string') return error.response.data.detail
    if (error.code === 'ECONNABORTED') return '科普资料加载超时，请稍后重试。'
    if (!error.response) return '无法连接科普资料服务，请检查后端和 MySQL 是否启动。'
  }
  return '科普资料暂时无法读取，请稍后重试。'
}

export async function getArticles(): Promise<Article[]> {
  return (await apiClient.get<Article[]>('/api/v1/articles')).data.map(withImageURL)
}

export async function getArticle(id: string): Promise<Article | undefined> {
  return withImageURL((await apiClient.get<Article>('/api/v1/articles/' + encodeURIComponent(id))).data)
}
