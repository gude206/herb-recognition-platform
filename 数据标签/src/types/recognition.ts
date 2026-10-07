export interface PredictionIdentity {
  identity_conflict?: boolean
  identity_status?: string
  review_status?: string
  original_latin_name?: string
  accepted_latin_name?: string
}
export interface Prediction extends PredictionIdentity {
  herb_id: string
  name: string
  latin_name: string
  confidence: number
  family?: string
  class_id?: number
  image_url?: string
}
export interface TopPrediction extends PredictionIdentity {
  herb_id: string
  name: string
  confidence: number
  latin_name?: string
  family?: string
  class_id?: number
}
export interface ModelInfo {
  name: string
  run: string
  epoch: number
  classes: number
  device: string
  test_top1_accuracy?: number
  test_top5_accuracy?: number
  test_images?: number
}
export interface RecognitionResult { prediction: Prediction; top_k: TopPrediction[]; model?: ModelInfo }
export interface RecognitionSample { herb_id: string; name: string; image_url: string }
