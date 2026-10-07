import { apiClient, useMock, wait } from './client'
import { mockArticles } from '../data/mockArticles'
import type { Article } from '../types/article'
export async function getArticles(): Promise<Article[]> { if (!useMock) return (await apiClient.get<Article[]>('/api/v1/articles')).data; await wait(200); return mockArticles }
export async function getArticle(id: string): Promise<Article | undefined> { if (!useMock) return (await apiClient.get<Article>(`/api/v1/articles/${id}`)).data; await wait(120); return mockArticles.find((article) => article.id === id) }
