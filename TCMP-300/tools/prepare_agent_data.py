"""Derive auditable field-topic examples; split by plant identity, never by row alone."""
import argparse,csv,hashlib,json,random,re,sys,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import publication_policy as policy

def clean(text):
    # Botanical names/numbers/punctuation carry meaning; do not remove negation.
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text)).strip()

def prepare(source,output):
    rows=list(csv.DictReader(source.open(encoding='utf-8-sig',newline='')))
    random.Random(20261114).shuffle(rows)
    candidates=[]
    for row in rows:
        evidence=policy.botanical_evidence(row)
        if not policy.plant_is_public(row,evidence):continue
        samples=[]
        for label,fields in [('植物形态',['叶特征','花特征','生长形态','果实特征']),('分布生境',['分布地区','生境']),('分类名称',['规范中文名','规范学名','规范科名','属名'])]:
            parts=[policy.botanical_value(evidence,f) for f in fields]
            text=clean('；'.join(p for p in parts if p))
            if len(text)<12:continue
            urls=sorted({item['url'] for f in fields for item in evidence.get(f,[])})
            samples.append(dict(instruction='将植物科普文本分类为：植物形态、分布生境、分类名称、本草文化、其他。仅输出类别。',
                                input=text[:3000],output=label,plant_id=row['植物ID'],sources=urls,
                                labeling_method='由来源字段生成主题弱标签，需人工复核'))
        if samples:candidates.append(samples)
    # Species-disjoint test/validation/training. These labels are not human gold.
    test=[x for group in candidates[:4] for x in group][:10]
    validation=[x for group in candidates[4:8] for x in group][:10]
    train=[x for group in candidates[8:] for x in group][:100]
    if len(train)!=100 or len(test)!=10 or len(validation)!=10:raise ValueError('有来源的可用文本不足120条')
    assert not ({x['plant_id'] for x in train}&{x['plant_id'] for x in test+validation})
    output.mkdir(parents=True,exist_ok=True)
    for name,data in [('agent_finetune_data.json',train),('agent_test_data.json',test),('agent_validation_data.json',validation)]:
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=dict(source_name=source.name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),source_rows=len(rows),
                  seed=20261114,counts=dict(train=100,validation=10,test=10),split_by='plant_id',
                  label_status='source-field weak supervision, not independently human reviewed',
                  cleaning='NFKC and whitespace normalization; retain botanical punctuation and negation',
                  missing_training_classes=['本草文化','其他'],excluded='未公开资料、药效、毒性和身份冲突记录')
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();prepare(args.source,args.output)
