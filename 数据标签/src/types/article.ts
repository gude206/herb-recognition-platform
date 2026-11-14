import type { ImageCredit } from './media'

export interface Article {
  imageCredit?: ImageCredit | null
  id: string; title: string; category: string; excerpt: string; image: string; reads: string; body: string
  readCount?: number; reviewStatus?: string; sourceKind?: string; sourceNote?: string
  status?: 'draft' | 'published'; storageSource?: 'mysql' | 'seed'; updatedAt?: string
}
