"""Zero-shot field-topic baseline through the API, using only the held-out split."""
import argparse,json,secrets,time
from pathlib import Path
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument('--api',default='http://127.0.0.1:8000');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();rows=json.loads((Path(__file__).parent/'data/agent_test_data.json').read_text(encoding='utf-8'))
    results=[]
    with httpx.Client(base_url=args.api,timeout=180,trust_env=False,headers={'X-History-Token':secrets.token_hex(32)}) as client:
        for row in rows:
            start=time.perf_counter();response=client.post('/api/v1/text/classify',json={'text':row['input']})
            prediction=response.json().get('result',{});prediction=prediction or {}
            results.append(dict(plant_id=row['plant_id'],expected=row['output'],predicted=prediction.get('label'),
                correct=prediction.get('label')==row['output'],status=response.status_code,elapsed_ms=round((time.perf_counter()-start)*1000,2)))
            print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    report={'label_basis':'source-field weak labels, not human gold','samples':results,
            'accuracy':sum(x['correct'] for x in results)/len(results),
            'mean_elapsed_ms':sum(x['elapsed_ms'] for x in results)/len(results)}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
