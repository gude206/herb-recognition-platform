"""Compare one existing base and one local adapter on the same held-out examples."""
import argparse,json,os,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--adapter-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if not args.model_dir.is_dir() or not (args.adapter_dir/'adapter_config.json').is_file():p.error('需要已有基座目录和已训练的适配器；不会下载模型')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig
    from peft import PeftModel
    if not torch.cuda.is_available():raise SystemExit('本量化评估脚本需要兼容CUDA环境')
    tokenizer=AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(args.model_dir,local_files_only=True,trust_remote_code=False,
          device_map={'':0},quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4'))
    rows=json.loads((Path(__file__).parent/'data/agent_test_data.json').read_text(encoding='utf-8'))
    def evaluate(current):
        results=[];current.eval()
        for row in rows:
            prompt=tokenizer.apply_chat_template([{'role':'user','content':row['instruction']+'\n'+row['input']}],tokenize=False,add_generation_prompt=True)
            inputs=tokenizer(prompt,return_tensors='pt').to(current.device)
            torch.cuda.synchronize();start=time.perf_counter()
            with torch.inference_mode():generated=current.generate(**inputs,max_new_tokens=24,do_sample=False,pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize();elapsed=(time.perf_counter()-start)*1000
            text=tokenizer.decode(generated[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True).strip().strip('。．\n ')
            results.append(dict(plant_id=row['plant_id'],expected=row['output'],predicted=text,correct=text==row['output'],elapsed_ms=round(elapsed,2)))
        return dict(samples=results,accuracy=sum(x['correct'] for x in results)/len(results),mean_elapsed_ms=sum(x['elapsed_ms'] for x in results)/len(results))
    before=evaluate(model)
    after=evaluate(PeftModel.from_pretrained(model,args.adapter_dir,local_files_only=True))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'label_basis':'source-field weak labels','before':before,'after':after},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
