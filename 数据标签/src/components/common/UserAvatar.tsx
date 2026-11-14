import { useEffect, useState } from 'react'
import { apiClient } from '../../api/client'
import type { AccountUser } from '../../api/session'
import defaultAvatar from '../../assets/default-avatar.svg'

export function UserAvatar({ user, size = 42 }: { user: AccountUser; size?: number }) {
  const [image, setImage] = useState<{ key: string; url: string } | null>(null)
  const key = user.avatar_url || ''
  useEffect(() => {
    if (!key) return
    let alive = true, objectURL = ''
    const controller = new AbortController()
    void apiClient.get<Blob>(key, { responseType: 'blob', signal: controller.signal }).then(({ data }) => {
      if (alive) { objectURL = URL.createObjectURL(data); setImage({ key, url: objectURL }) }
    }).catch(() => {})
    return () => { alive = false; controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL) }
  }, [key])
  return <img className="user-avatar" src={image?.key === key ? image.url : defaultAvatar} width={size} height={size} alt={`${user.name}的头像`} />
}
