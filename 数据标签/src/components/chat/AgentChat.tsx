import { useEffect, useId, useRef, useState } from 'react'
import { apiClient } from '../../api/client'
import type { ToolCall, ChatMessage } from '../../api/chat'
import { loadRecognitionImage } from '../../api/history'

export function ChatUserMessage({message}:{message:ChatMessage}) {
  return <div className="chat-user-message">{message.image_record_id&&<ChatMessageImage recordId={message.image_record_id}/>}{message.content&&<div className="chat-bubble user-bubble">{message.content}</div>}</div>
}

export function ChatMessageImage({recordId}:{recordId:string}) {
  const [image,setImage]=useState(''),[failed,setFailed]=useState(false)
  useEffect(()=>{
    let alive=true,url='';setImage('');setFailed(false)
    void loadRecognitionImage(recordId).then(blob=>{
      if(alive){url=URL.createObjectURL(blob);setImage(url)}
    }).catch(()=>{if(alive)setFailed(true)})
    return()=>{alive=false;if(url)URL.revokeObjectURL(url)}
  },[recordId])
  return <div className="chat-message-image">{image?<img src={image} alt="发送的植物图片"/>:<span>{failed?'图片暂不可用':'正在加载图片…'}</span>}</div>
}

const toolNames: Record<string,string> = {search_plants:'检索植物资料',plant_details:'读取植物详情',recognize_plant_image:'识别植物图片',classify_plant_text:'分类植物文本'}
export function AgentToolCalls({calls}:{calls?:ToolCall[]}) {
  if(!calls?.length)return null
  return <div className="agent-tool-results" aria-label="工具执行结果">{calls.map((call,index)=><details key={call.id || index}>
    <summary>{toolNames[call.name] || '工具调用'} · {call.status==='success'?'已完成':'失败'}{call.elapsed_ms!==undefined?` · ${(call.elapsed_ms/1000).toFixed(2)}秒`:''}</summary>
    <pre>{JSON.stringify(call.result,null,2)}</pre>
  </details>)}</div>
}

export function AgentChat({conversationId,disabled,value,onAttachment,onUploading}:{conversationId:string;disabled:boolean;value?:string;onAttachment:(id?:string)=>void;onUploading?:(uploading:boolean)=>void}) {
  const [fileName,setFileName]=useState(''),[error,setError]=useState(''),[uploading,setUploading]=useState(false)
  const [preview,setPreview]=useState(''),[fileSize,setFileSize]=useState('')
  const fileInput=useRef<HTMLInputElement>(null),previewURL=useRef('')
  const descriptionId=useId()
  const controller=useRef<AbortController | null>(null)
  const uploadedId=useRef('')
  function clearPreview(){
    if(previewURL.current)URL.revokeObjectURL(previewURL.current)
    previewURL.current='';setPreview('');setFileName('');setFileSize('')
  }
  useEffect(()=>{
    clearPreview();uploadedId.current='';setError('');setUploading(false);onUploading?.(false);onAttachment(undefined)
    return()=>{controller.current?.abort();if(previewURL.current)URL.revokeObjectURL(previewURL.current);previewURL.current=''}
  },[conversationId])
  useEffect(()=>{
    if(!value){clearPreview();return}
    if(uploadedId.current===value&&previewURL.current)return
    let alive=true
    void loadRecognitionImage(value).then(blob=>{
      if(!alive)return
      clearPreview();uploadedId.current=value;previewURL.current=URL.createObjectURL(blob);setPreview(previewURL.current)
      setFileName('已上传的植物图片');setFileSize(`${Math.max(1,Math.round(blob.size/1024))} KB`)
    }).catch(()=>{if(alive){onAttachment(undefined);setError('图片恢复失败，请重新上传')}})
    return()=>{alive=false}
  },[value])
  async function upload(file?:File) {
    if(!file)return
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024){setError('请选择不超过10MB的 JPG、PNG 或 WEBP 图片');return}
    controller.current?.abort()
    const request=new AbortController();controller.current=request
    setUploading(true);onUploading?.(true);setError('');onAttachment(undefined);clearPreview()
    try {
      const form=new FormData();form.append('file',file)
      const {data}=await apiClient.post('/api/v1/predict',form,{signal:request.signal,timeout:60000})
      if(!request.signal.aborted){
        if(!data.result?.record_id)throw new Error('图片未保存，请检查历史记录数据库后重试')
        uploadedId.current=data.result.record_id;onAttachment(data.result.record_id);setFileName(file.name)
        previewURL.current=URL.createObjectURL(file);setPreview(previewURL.current)
        setFileSize(file.size>=1024*1024?`${(file.size/1024/1024).toFixed(1)} MB`:`${Math.max(1,Math.round(file.size/1024))} KB`)
      }
    } catch(reason) {if(!request.signal.aborted)setError(reason instanceof Error?reason.message:'图片上传失败，请重试')}
    finally {if(!request.signal.aborted){setUploading(false);onUploading?.(false)}}
  }
  return <div className="agent-attachment">
    <div className="agent-upload-row">
      <button className="agent-upload-button" type="button" disabled={disabled||uploading} aria-describedby={descriptionId}
        onClick={()=>fileInput.current?.click()}>{uploading?'正在上传…':fileName?'更换图片':'上传植物图片'}</button>
      <span id={descriptionId} className="agent-upload-hint">JPG、PNG、WEBP · 最大 10MB</span>
      <input ref={fileInput} hidden aria-label="选择植物图片" type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled||uploading}
        onChange={event=>{void upload(event.target.files?.[0]);event.target.value=''}}/>
    </div>
    {fileName&&<div className="agent-selected-image">
      <img src={preview} alt="已选择的植物图片"/>
      <div className="agent-selected-copy"><span title={fileName}>{fileName}</span><small>{fileSize} · 已上传</small></div>
      <button className="agent-remove-image" type="button" disabled={disabled} onClick={()=>{onAttachment(undefined);clearPreview();setError('')}}>移除</button>
    </div>}
    {uploading&&<span className="agent-upload-status" role="status">正在准备图片，请稍候…</span>}
    {error&&<p className="agent-upload-error" role="alert">{error}</p>}
  </div>
}
