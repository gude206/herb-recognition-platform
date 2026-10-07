import { ArrowRight, CheckCircle2, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { RecognitionResult as ResultType } from '../../types/recognition'
import { IdentityWarning } from '../herb/HerbIdentity'

const formatConfidence = (score: number) => score > 0 && score < 0.0001 ? '<0.01%' : `${(score * 100).toFixed(2)}%`

export function RecognitionResult({result, preview}: {result?: ResultType; preview?: string}) {
  return <section className="paper-card recognition-result">
    <div className="mini-heading"><Sparkles size={20}/><h3>识别结果</h3>{result && <span className="success-label"><CheckCircle2 size={14}/>识别完成</span>}</div>
    {result ? <>
      <div className="result-main">
        {preview && <img src={preview} alt="识别上传图片"/>}
        <div className="result-copy">
          <div className="name-score"><h2>{result.prediction.name}</h2><span>置信度 {formatConfidence(result.prediction.confidence)}</span></div>
          <p className="latin">{result.prediction.latin_name}</p>
          {result.prediction.family && <p>科属：{result.prediction.family}</p>}
          <div className="tag-row prediction-status"><span className="tag">模型候选 · 待核实</span><span className="tag">{result.prediction.review_status || '审核状态未提供'}</span></div>
          {result.prediction.identity_conflict && <IdentityWarning className="prediction-warning" originalLatinName={result.prediction.original_latin_name} acceptedLatinName={result.prediction.accepted_latin_name}/>}
          {result.prediction.identity_status && <p className="prediction-identity">身份资料：{result.prediction.identity_status}</p>}
          <Link to={'/herbs/'+result.prediction.herb_id} className="text-link">查看植物分布与完整资料 <ArrowRight size={15}/></Link>
        </div>
      </div>
      <div className="top-predictions"><strong>Top 5 候选结果 · 置信度</strong>
        {result.top_k.slice(0, 5).map((item, index) => <div className="prediction-row" key={item.herb_id}>
          <b className={`rank rank-${index + 1}`}>{index + 1}</b><span className="prediction-candidate"><Link to={'/herbs/'+item.herb_id}>{item.name}</Link><small className={item.identity_conflict ? 'candidate-conflict' : ''} title={[item.identity_status,item.review_status].filter(Boolean).join(' · ')}>{item.identity_conflict ? '身份冲突 · 待核实' : '候选 · 待核实'}</small></span><strong>{formatConfidence(item.confidence)}</strong>
        </div>)}
      </div>
    </> : <div className="result-placeholder"><Sparkles size={25}/><strong>等待识别</strong><span>上传植物图片，查看前五个预测类别和置信度</span></div>}
  </section>
}
