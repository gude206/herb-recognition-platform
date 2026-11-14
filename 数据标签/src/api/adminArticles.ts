import { apiClient } from './client'
import type { Article } from '../types/article'

export interface AdminArticle extends Article { version: number; displayOrder: number; deleted: boolean; coverPath: string }
export interface ArticleForm {
  title: string; category: string; excerpt: string; body: string; status: 'draft' | 'published'
  reviewStatus: string; sourceKind: 'course_example' | 'editorial'; sourceNote: string; displayOrder: number
}
export interface AdminArticlePage { items: AdminArticle[]; total: number; page: number; pageSize: number }
const imageURL = (article: AdminArticle) => ({ ...article, image: article.image ? new URL(article.image, apiClient.defaults.baseURL).href : '' })

export async function getAdminArticles(q: string, status: string, page: number): Promise<AdminArticlePage> {
  const { data } = await apiClient.get<AdminArticlePage>('/api/v1/admin/articles', { params: { q, status, page, page_size: 10 } })
  return { ...data, items: data.items.map(imageURL) }
}
export async function getAdminArticle(id: string) {
  return imageURL((await apiClient.get<AdminArticle>('/api/v1/admin/articles/' + encodeURIComponent(id))).data)
}
export async function saveAdminArticle(form: ArticleForm, article?: AdminArticle) {
  const response = article
    ? await apiClient.put<AdminArticle>('/api/v1/admin/articles/' + encodeURIComponent(article.id), { ...form, expectedVersion: article.version })
    : await apiClient.post<AdminArticle>('/api/v1/admin/articles', form)
  return imageURL(response.data)
}
export async function deleteAdminArticle(article: AdminArticle) {
  await apiClient.delete('/api/v1/admin/articles/' + encodeURIComponent(article.id), { data: { expectedVersion: article.version } })
}
export async function restoreAdminArticle(article: AdminArticle) {
  await apiClient.post('/api/v1/admin/articles/' + encodeURIComponent(article.id) + '/restore', { expectedVersion: article.version })
}
export async function uploadAdminCover(article: AdminArticle, file: File) {
  const data = new FormData()
  data.append('file', file)
  return imageURL((await apiClient.post<AdminArticle>('/api/v1/admin/articles/' + encodeURIComponent(article.id) + '/cover', data,
    { params: { expectedVersion: article.version }, timeout: 30000 })).data)
}
