export const CHAT_PROMPT_POOL = [
  '金银花的植物特征是什么？',
  '黄芪有哪些传统记载？',
  '如何识别常见本草？',
  '紫苏的叶片有哪些辨认特征？',
  '薄荷和紫苏的外形有什么区别？',
  '银杏的叶片有哪些特点？',
  '忍冬的花为什么有白色和黄色？',
  '鱼腥草的白色部分是花瓣吗？',
  '蒲公英怎样传播种子？',
  '车前通常生长在什么环境？',
  '马齿苋有哪些形态特点？',
  '栀子的花和果实有什么特征？',
  '观察植物时怎样判断叶序？',
  '拍摄植物识别照片要注意什么？',
  '植物的学名和别名有什么区别？',
] as const

const STORAGE_KEY = 'herbal-chat-suggested-prompts-v1'

export function selectSuggestedPrompts(previous: readonly string[] = [], random = Math.random): string[] {
  const remaining = CHAT_PROMPT_POOL.filter(item => !previous.includes(item))
  const candidates: string[] = [...(remaining.length >= 3 ? remaining : CHAT_PROMPT_POOL)]
  for (let i = candidates.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1))
    ;[candidates[i], candidates[j]] = [candidates[j], candidates[i]]
  }
  return candidates.slice(0, 3)
}

export function initialSuggestedPrompts(): string[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')
    return selectSuggestedPrompts(Array.isArray(saved) ? saved.filter((x): x is string => typeof x === 'string') : [])
  } catch { return selectSuggestedPrompts() }
}

export function rememberSuggestedPrompts(prompts: string[]) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(prompts)) } catch { /* Random suggestions still work without storage. */ }
}
