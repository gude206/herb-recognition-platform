import type { ImageCredit } from '../../types/media'

export function PhotoCredit({credit, linked=false}: {credit?: ImageCredit | null; linked?: boolean}) {
  if (!credit) return null
  return <span className="photo-credit" title={`${credit.title} · ${credit.author} · ${credit.license}`}>
    {linked ? <><a href={credit.sourceUrl} target="_blank" rel="noreferrer">摄影：{credit.author}</a><span> · </span><a href={credit.licenseUrl} target="_blank" rel="noreferrer">{credit.license}</a>{credit.attribution && <span> · {credit.attribution}</span>}</>
      : <>摄影：{credit.author} · {credit.license}</>}
  </span>
}
