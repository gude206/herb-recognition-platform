"""Offline-only LoRA/SFT entry point. No model retrieval or training on import."""
import argparse,json,os
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--train',action='store_true')
    p.add_argument('--data-dir',type=Path,default=Path(__file__).parent/'data');p.add_argument('--output',type=Path,default=Path(__file__).parent/'artifacts/adapter')
    args=p.parse_args()
    if not args.model_dir.is_dir() or not (args.model_dir/'config.json').is_file():p.error('必须提供已有模型目录；本脚本不会下载基座模型')
    train=json.loads((args.data_dir/'agent_finetune_data.json').read_text(encoding='utf-8'))
    valid=json.loads((args.data_dir/'agent_validation_data.json').read_text(encoding='utf-8'))
    test=json.loads((args.data_dir/'agent_test_data.json').read_text(encoding='utf-8'))
    groups=[{x['plant_id'] for x in data} for data in [train,valid,test]]
    if any(groups[i]&groups[j] for i,j in [(0,1),(0,2),(1,2)]):p.error('植物ID跨数据划分，拒绝训练')
    config=dict(quantization='NF4 4-bit double quantization',gradient_accumulation_steps=8,batch_size=1,
                epochs=3,lora_r=8,lora_alpha=16,lora_dropout=.05,target_modules='all-linear',seed=20261114,max_length=512)
    print(json.dumps({'config':config,'examples':len(train),'will_train':args.train},ensure_ascii=False))
    if not args.train:return
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig
    from peft import LoraConfig,prepare_model_for_kbit_training
    from datasets import Dataset
    from trl import SFTConfig,SFTTrainer
    if not torch.cuda.is_available():raise SystemExit('4-bit训练需要兼容CUDA环境，尚未开始训练')
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer=AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False)
    if not tokenizer.chat_template:raise SystemExit('模型缺少对话模板，需先验证模型适配')
    if tokenizer.pad_token is None:tokenizer.pad_token=tokenizer.eos_token
    model=AutoModelForCausalLM.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False,
        device_map={'':0},quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
        bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=dtype))
    model=prepare_model_for_kbit_training(model)
    def dataset(rows):return Dataset.from_list([{'messages':[{'role':'user','content':x['instruction']+'\n'+x['input']},
                                                           {'role':'assistant','content':x['output']}]} for x in rows])
    args.output.mkdir(parents=True,exist_ok=True)
    trainer=SFTTrainer(model=model,processing_class=tokenizer,train_dataset=dataset(train),eval_dataset=dataset(valid),
        peft_config=LoraConfig(r=8,lora_alpha=16,lora_dropout=.05,target_modules='all-linear',task_type='CAUSAL_LM'),
        args=SFTConfig(output_dir=str(args.output),per_device_train_batch_size=1,per_device_eval_batch_size=1,
            gradient_accumulation_steps=8,num_train_epochs=3,learning_rate=2e-4,max_length=512,seed=20261114,
            bf16=dtype==torch.bfloat16,fp16=dtype==torch.float16,gradient_checkpointing=True,
            eval_strategy='epoch',save_strategy='epoch',logging_steps=1,report_to='none'))
    metrics=trainer.train().metrics;trainer.save_model(str(args.output));tokenizer.save_pretrained(args.output)
    (args.output/'training_metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    (args.output/'experiment_config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')

if __name__=='__main__':main()
