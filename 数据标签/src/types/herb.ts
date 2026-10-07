export interface Herb {
  id: string
  name: string
  latinName: string
  aliases: string[]
  family: string
  medicinalPart: string[]
  property: string
  flavor: string[]
  meridians: string[]
  effects: string[]
  description: string
  image: string
  morphology: string
  traditionalUses: string[]
  precautions: string[]
  background: string
  classId?: number
  originalLatinName?: string
  acceptedLatinName?: string
  genus?: string
  familyChinese?: string
  genusChinese?: string
  properties?: string[]
  distribution?: string
  distributionStatus?: string
  habitat?: string
  growthForm?: string
  identityStatus?: string
  identityConflict?: boolean
  reviewStatus?: string
  imageStatus?: 'dataset_reference' | 'missing'
  toxicity?: string
  elevation?: string
  flowering?: string
  fruiting?: string
  sporeSeason?: string
  features?: {label: string; value: string}[]
  completeIntroduction?: string
  medicinalIntroduction?: string
  medicinalRegions?: string
  materials?: Record<string, string>[]
  traditionalEffects?: string
  natureText?: string
  flavorText?: string
  meridianText?: string
  confusion?: string
  differences?: string
  confusionRisk?: string
  confusionStatus?: string
  taxonomySystem?: string
  taxonomyStatus?: string
  notes?: string
  fieldReview?: Record<string, string>
  sources?: {name: string; url: string; version: string; locator: string}[]
  updatedAt?: string
}

export interface HerbQuery {
  q?: string
  effect?: string
  property?: string
  part?: string
  family?: string
  genus?: string
  region?: string
  recent_ids?: string
  letter?: string
  sort?: string
  page?: number
  page_size?: number
}

export interface HerbListResponse { total: number; collectionTotal?: number; page?: number; pageSize?: number; items: Herb[] }
export interface HerbFilters { total: number; distributionCount: number; families: string[]; genera: string[]; regions: string[]; properties: string[]; parts: string[]; effects: string[] }
