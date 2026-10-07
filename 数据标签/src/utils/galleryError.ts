import { isAxiosError } from 'axios'

export function galleryError(error: unknown): string {
  if (isAxiosError(error)) {
    if (error.response?.status === 422) return '搜索或筛选参数无效，请将关键词控制在 200 字以内，或重置筛选后重试。'
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return '植物资料加载超时，请稍后重新加载。'
    if (!error.response) return '无法连接植物资料服务，请检查网络，并确认本地数据服务已启动。'
    if (error.response.status >= 500) return '植物资料服务暂时出现错误，请稍后重新加载。'
  }
  return '植物资料加载失败，请重新加载或重置筛选后重试。'
}
