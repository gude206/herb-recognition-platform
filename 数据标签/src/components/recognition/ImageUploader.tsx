import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ImagePlus, LoaderCircle, RotateCcw, UploadCloud } from 'lucide-react'
import { predictHerb, recognitionError } from '../../api/recognition'
import type { RecognitionResult } from '../../types/recognition'

export function ImageUploader({onResult, onStart}: {onResult: (result: RecognitionResult, preview: string) => void; onStart: () => void}) {
  const input = useRef<HTMLInputElement>(null)
  const busy = useRef(false)
  const previewUrl = useRef('')
  const mounted = useRef(true)
  const [preview, setPreview] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current)
    }
  }, [])

  const upload = async (file: File) => {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('请选择 JPG、PNG 或 WEBP 图片')
    if (file.size > 10 * 1024 * 1024) throw new Error('图片大小不能超过 10MB')
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current)
    const url = URL.createObjectURL(file)
    previewUrl.current = url
    setPreview(url)
    const result = await predictHerb(file)
    if (mounted.current) onResult(result, url)
  }

  const recognize = async (file?: File) => {
    if (!file || busy.current) return
    busy.current = true
    setLoading(true)
    setError('')
    onStart()
    try {
      await upload(file)
    } catch (error) {
      if (mounted.current) setError(recognitionError(error))
    } finally {
      busy.current = false
      if (mounted.current) setLoading(false)
    }
  }
  const drop = (event: DragEvent<HTMLDivElement>) => {event.preventDefault(); void recognize(event.dataTransfer.files[0])}

  return <div className="upload-layout"><div className="upload-input"><div className={`drop-zone ${preview ? 'has-preview' : ''}`} onDragOver={event => event.preventDefault()} onDrop={drop} aria-busy={loading}>
    {preview ? <img className="upload-preview" src={preview} alt="待识别草药预览"/> : <><span className="upload-symbol"><ImagePlus size={28}/></span><strong>拖拽图片到此处，或点击上传</strong><small>支持 JPG、PNG、WEBP · 不超过 10MB</small><button disabled={loading} type="button" className="button button-primary" onClick={() => input.current?.click()}><UploadCloud size={16}/>选择图片</button></>}
    <input ref={input} hidden disabled={loading} type="file" accept="image/png,image/jpeg,image/webp" aria-label="上传植物图片" onChange={event => {void recognize(event.target.files?.[0]); event.target.value = ''}}/>
    {loading && <div className="upload-loading" role="status"><LoaderCircle className="spin"/><span>正在分析植物特征…</span></div>}
  </div>{preview && <div className="upload-actions"><button type="button" disabled={loading} className="button button-light" onClick={() => input.current?.click()}><RotateCcw size={15}/>更换图片</button></div>}</div>
    {error && <p className="form-error recognition-error" role="alert">{error}</p>}
  </div>
}
