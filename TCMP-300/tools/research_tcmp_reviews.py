"""Recover documented missing fields and distinguish unavailable from inapplicable."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

import enrich_tcmp_metadata as enrich
from prepare_live_plant_csv import clean_plant_distribution, render_fields

DATA=enrich.DATA
BACKUP=DATA/'before_review_completion_20260930'
CACHE=DATA/'review_research_20260930'
CACHE.mkdir(exist_ok=True)
FILES=['tcmp-info-20250329.csv','tcmp-medicinal-materials.csv','tcmp-image-candidates.csv',
       'tcmp-field-sources.csv','tcmp-review-queue.csv']
FERNS={'68','83','87','99','134','175','220','244','246','272','297'}

def read(name,directory=DATA):
    with (directory/name).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        return reader.fieldnames,list(reader)

def record(url):
    path=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    response=enrich.fetch(url)
    path.write_text(json.dumps(response,ensure_ascii=False),encoding='utf-8')
    return response

def getjson(url):
    try: return json.loads(record(url).get('body',''))
    except ValueError: return {}

def foc_matches(foc, name):
    title=enrich.compact(enrich.text_of(foc.get('contenttitle','')))
    query=enrich.canonical(name).lower()
    return bool(query and re.search(r'(?<![a-z])'+re.escape(query)+r'(?![a-z])',title.lower()))

def english_sentences(text):
    # Decimal points and abbreviations such as ca. and diam. are not boundaries.
    return [s.strip() for s in re.split(r'(?<!ca)(?<!diam)\.\s+(?=[A-Z])',text) if s.strip()]

def collect():
    _,rows=read(FILES[0])
    jobs=[]
    for row in rows:
        if row['No']=='51': continue
        if any(not row[f] for f in ['根特征','叶特征','花特征','果实特征','生境','花期','果期']):
            name=row['植物智学名'] or enrich.canonical(row['Latin Name'])
            jobs.append('https://www.iplant.cn/ashx/getfoc.ashx?'+urllib.parse.urlencode({'key':name}))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(record,u) for u in dict.fromkeys(jobs)]
        done=0
        for future in as_completed(futures):
            future.result();done+=1
            if done%30==0: print('Flora of China retrieved',done,'/',len(futures),flush=True)
    print('Collected',len(futures),'Flora of China entries',flush=True)

def make(output):
    BACKUP.mkdir(exist_ok=True)
    for name in FILES:
        if not (BACKUP/name).exists(): shutil.copy2(DATA/name,BACKUP/name)
    columns,plants=read(FILES[0],BACKUP)
    medcols,meds=read(FILES[1],BACKUP)
    _,images=read(FILES[2],BACKUP)
    sourcecols,sources=read(FILES[3],BACKUP)
    reviewcols,reviews=read(FILES[4],BACKUP)
    source_groups=defaultdict(list)
    for source in sources:source_groups[source['No']].append(source)
    edits=[]
    def put(row,field,value,source_name,url,locator,version='网页版本未声明',replace=False,status='原文核对补充，未经过人工审核'):
        if not value or (row.get(field) and not replace) or row.get(field)==value:return
        old=row.get(field,'');row[field]=value
        if old:
            for previous in source_groups[row['No']]:
                if previous['field']==field:
                    previous['status']='旧版提取或参考证据；当前采用值见字段来源JSON对应的新证据'
        eid='review-'+hashlib.sha256((row['No']+field+value+url).encode()).hexdigest()[:24]
        evidence={'No':row['No'],'field':field,'value':value,'source_name':source_name,'url':url,
                  'version':version,'locator':locator,'status':status,'retrieved_date':'2026-09-30','evidence_id':eid}
        sources.append(evidence);source_groups[row['No']].append(evidence)
        mapping=json.loads(row['字段来源JSON']);mapping[field]=[eid];row['字段来源JSON']=json.dumps(mapping,ensure_ascii=False)
        edits.append({'No':row['No'],'field':field,'old':old,'new':value,'url':url,'status':status})
    for row in plants:
        number=row['No']
        if number=='51':
            row['身份核对状态']='中文名/科名与原始学名冲突；7张训练图片抽样支持地肤候选，尚不足以确认全部图片身份'
            row['待核实说明']='已检查7张训练图片；不能按Geranium wilfordii采用植物资料。候选Bassia scoparia的资料仅存候选字段，未作为该类别的正式药材信息。'
            candidate_url='https://www.iplant.cn/ashx/getfrps.ashx?key=Kochia%20scoparia'
            candidate=getjson(candidate_url)
            row['候选植物资料JSON']=json.dumps({'候选中文名':'地肤','候选学名':'Bassia scoparia',
                '植物志采用名':'Kochia scoparia (L.) Schrad.','来源':candidate_url,
                '候选原文':enrich.compact(enrich.text_of(candidate.get('frpsdesc',''))),
                '采用状态':'仅供核实原始标签，不用于确认该训练类身份'},ensure_ascii=False)
            continue
        name=row['植物智学名'] or enrich.canonical(row['Latin Name'])
        foc_url='https://www.iplant.cn/ashx/getfoc.ashx?'+urllib.parse.urlencode({'key':name})
        foc=getjson(foc_url)
        if not foc_matches(foc,name):foc={}
        # getfoc separates geographic/ecological paragraphs from morphology.
        foc_text={key:enrich.compact(enrich.text_of(value)) for key,value in foc.items()
                  if isinstance(value,str) and key not in ['parsublist','sublist','imgtxt','genpdf','familypdf','Synonym']}
        foc_morph=enrich.compact(enrich.text_of(foc.get('Description','')))
        version='Flora of China '+enrich.compact(enrich.text_of(foc.get('vol','')))+foc.get('volyear','')
        if foc_morph:
            english_patterns={
                '根特征':r'^(?:Roots?|Rhizomes?|Rootstock|Taproot)\b',
                '叶特征':r'^(?:(?:Basal |Cauline )?[Ll]eaves|Leaf blades?)\b',
                '花特征':r'^Flowers\b',
                '果实特征':r'^(?:Capsules?|Drupe|Drupelets?|Berries|Berry|Achenes?|Fruits?|Legumes?|Nuts?)\b',
                '茎特征':r'^Stems?\b',
                '种子特征':r'^Seeds?\b',
            }
            for field,pattern in english_patterns.items():
                found=[s for s in english_sentences(foc_morph) if re.search(pattern,s)]
                if found and not (field in ['花特征','果实特征'] and number in FERNS):
                    put(row,field,'Flora of China英文原文：'+'. '.join(found),'Flora of China（植物智数字版）',
                        foc_url,'Description中明确器官描述，保留英文供复查',version)
            for field,tag in [('花期','Fl.'),('果期','fr.')]:
                match=re.search(r'\b'+re.escape(tag)+r'\s+([A-Z][a-z]{2}(?:[^.;\[\]]{0,35}))',foc_morph)
                if match and number not in FERNS:
                    value=match.group(1).split(',')[0].strip()
                    months={'Jan':'1月','Feb':'2月','Mar':'3月','Apr':'4月','May':'5月','Jun':'6月',
                            'Jul':'7月','Aug':'8月','Sep':'9月','Oct':'10月','Nov':'11月','Dec':'12月'}
                    translated=re.sub(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',lambda m:months[m.group(0)],value)
                    translated=translated.replace(' and ','及').replace('-','–')
                    put(row,field,translated+'（Flora of China记载）','Flora of China（植物智数字版）',foc_url,'Description/'+tag,version)
            if not row['生境'] and foc.get('habait'):
                habitat=enrich.compact(enrich.text_of(foc['habait']))
                if habitat:put(row,'生境','Flora of China英文原文：'+habitat,
                               'Flora of China（植物智数字版）',foc_url,'habait完整生境与分布原文，英文保留',version)
        refs=[e for e in source_groups[number] if e['field'] in ['形态描述','植物志原文','药用植物形态原文']]
        # Source texts are already tied to this exact botanical identity.
        for source in refs:
            text=source['value'];url=source['url'];version=source['version'];sn=source['source_name']
            # Only the first morphology block is used; retain existing authoritative raw texts.
            if source['field']=='植物志原文' and row['形态描述']:
                text=row['形态描述']
            sentences=[s.strip() for s in re.split(r'(?<=[。；])',text) if s.strip()]
            patterns={'叶特征':r'(?:^|[；。])\s*(?:叶|叶片|小叶|单叶|复叶|基生叶|茎生叶|鳞叶|叶退化)',
                      '根特征':r'(?:^|[；。])\s*(?:根|主根|肉质根|块根|根状茎|根茎|地下根)',
                      '花特征':r'(?:^|[；。])\s*(?:花|雄花|雌花|总状花序|聚伞花序|头状花序)',
                      '果实特征':r'(?:^|[；。])\s*(?:果|蒴果|瘦果|核果|浆果|坚果|荚果|颖果)',
                      '茎特征':r'(?:^|[；。])\s*(?:茎|地上茎)',
                      '种子特征':r'(?:^|[；。])\s*种子'}
            for field,pattern in patterns.items():
                found=[s for s in sentences if re.search(pattern,s)]
                if found:put(row,field,' '.join(found),sn,url,'现有形态原文中的明确器官句',version)
            for field,label in [('花期','花期'),('果期','果期'),('孢子期','孢子(?:成熟)?期')]:
                m=re.search(label+r'([^。；]+)',text)
                if m:put(row,field,m.group(1).strip(),sn,url,'现有形态原文中明确的物候',version)
            joint=re.search(r'花[、，]?果期([^。；]+)',text)
            if joint:
                for field in ['花期','果期']:put(row,field,'来源合记花果期：'+joint.group(1),sn,url,'来源共同记载花果期，不拆分月份',version)
        # The full plant-database sections include pharmacology, contraindications, and examples.
        university_urls=list(dict.fromkeys(e['url'] for e in source_groups[number] if '/mpid/detail.php' in e['url']))
        for url in university_urls:
            fields,_=enrich.hk_fields(enrich.fetch(url).get('body',''))
            if not fields:continue
            for field,key in [('传统应用','主治用法'),('使用注意','使用注意'),('使用注意','注意事项'),('使用注意','禁忌')]:
                if fields.get(key):put(row,field,fields[key],'香港浸会大学药用植物图像数据库',url,'【'+key+'】')
            for key in ['性味功能','药理作用','主治用法','应用举例']:
                text=fields.get(key,'')
                # Treating poisoning is an indication, not evidence of this plant's toxicity.
                toxic=list(dict.fromkeys(s.strip() for s in re.split(r'(?<=[。；])',text)
                    if re.search(r'有毒|大毒|小毒|无毒|肝毒性|肾毒性|(?:导致|引起|发生|出现)[^。；]{0,12}中毒',s)))
                if toxic:put(row,'毒性','来源记载：'+' '.join(toxic),'香港浸会大学药用植物图像数据库',url,'【'+key+'】明确毒性句')
                warnings=list(dict.fromkeys(s.strip() for s in re.split(r'(?<=[。；])',text) if re.search(r'禁用|禁服|慎用|慎服|不宜|忌用|忌服|不能服|不可服',s)))
                if number=='117' and key=='主治用法':warnings=['不宜久煎。' if '不宜久煎' in s else s for s in warnings]
                if warnings:put(row,'使用注意',' '.join(warnings),'香港浸会大学药用植物图像数据库',url,'【'+key+'】明确使用注意句')
                # “热病邪入心经” in indications is not a meridian attribution.
                mer=re.search(r'(?:归|入)([^。；]{1,70}经)',text) if key=='性味功能' else None
                if mer:put(row,'归经',mer.group(1),'香港浸会大学药用植物图像数据库',url,'【'+key+'】明确归经句')
            habitat=fields.get('生境分布','')
            hs=[s.strip() for s in re.split(r'[。；]',habitat) if re.match(r'生于|生长于|生长在|多生于',s.strip())]
            if hs:put(row,'生境','。'.join(hs),'香港浸会大学药用植物图像数据库',url,'【生境分布】明确生境句')
        # Recover geographic/ecological sentences in the saved flora paragraphs.
        raw=row['植物志原文']
        if number in {'37','298'} and not row['生境']:
            text=row['生境分布原文'].split('。')[0]+'。'
            if '栽培' in text:
                url=next(e['url'] for e in source_groups[number] if e['field']=='生境分布原文')
                put(row,'生境',text+'（来源仅说明栽培状况，未给出具体自然生境条件。）',
                    '香港浸会大学药用植物图像数据库',url,'【生境分布】栽培状况；不推断土壤或气候')
        if not row['生境']:
            hs=re.findall(r'(?:^|。)\s*((?:生于|生长于|生长在|生海拔|生山地)[^。；]+)',raw)
            if hs:
                url=next((e['url'] for e in source_groups[number] if e['field']=='植物志原文'),'')
                put(row,'生境',hs[0]+'。','中国植物志（植物智数字版）',url,'首个明确的生境句，未从器官着生位置推断',row['植物志引用'])
        if number in FERNS:
            url=next((e['url'] for e in source_groups[number] if e['field'] in ['植物志原文','孢子囊特征','果实特征']),foc_url)
            if row['果实特征'] and re.search(r'孢子|能育叶',row['果实特征']):
                if not row['孢子囊特征']:put(row,'孢子囊特征',row['果实特征'],'中国植物志（植物智数字版）',url,'原误归入果实字段的孢子结构描述，移至正确字段')
            for field in ['花特征','花期','果实特征','果期']:
                put(row,field,'不适用：蕨类或石松类植物，以孢子繁殖；参见孢子囊特征及孢子期。',
                    '植物志类群与生殖结构核对',url,'孢子植物的花/果字段不适用',replace=True,status='已确认字段不适用；原文及类群归属已核对')
        row.setdefault('候选植物资料JSON','{}')
        # English FOC paragraphs are retained without inventing translations during extraction.
        if foc_morph:
            row['补充植物志原文']=foc_morph
            row['补充植物志来源']=foc_url
        else:
            row['补充植物志原文']='';row['补充植物志来源']=''
    # FOC provides a complete documented entry for the previously empty Viola japonica.
    row=next(r for r in plants if r['No']=='143')
    url='https://www.iplant.cn/ashx/getfoc.ashx?key=Viola%20japonica'
    foc=getjson(url)
    if foc.get('contenttitle') and 'Viola japonica' in foc['contenttitle']:
        sn='Flora of China（植物智数字版）';version='Vol.13 (2007), Viola japonica 物种条目'
        values={
            '规范中文名':'犁头草','规范学名':'Viola japonica Langsd. ex DC.',
            '生长形态':'多年生草本。','根特征':'根状茎短而粗；根多数，白色，细长而粗壮。',
            '叶特征':'叶基生；叶片卵形、宽卵形或三角状卵形，长3–8厘米、宽3–5.5厘米；基部深心形或宽心形，边缘密生圆齿，先端锐尖或稍钝；叶面疏被短柔毛或近无毛。',
            '花特征':'花浅紫色或淡紫白色；花梗不超过叶；距圆筒形，长6–8毫米。',
            '果实特征':'蒴果椭圆形，长约1厘米。','花期':'来源记载为3月及10月（Fl. Mar and Oct）。','果期':'5–10月。',
            '简短介绍':'犁头草为堇菜科堇菜属多年生草本。叶基生，叶片卵形至三角状卵形，基部心形；花浅紫色或淡紫白色，蒴果椭圆形。植物身份资料依据Flora of China物种条目，GBIF名称疑问状态仍保留说明。'}
        values['生境']='低地向阳或半阴处；海拔1100米以下。'
        values['分布地区']='中国安徽、重庆、福建、贵州、湖北、湖南、江苏、江西、四川、浙江；日本、朝鲜半岛。'
        for field,value in values.items():put(row,field,value,sn,url,'英文物种条目对应字段的中文转述；未改变原始训练标签',version,replace=field in ['根特征','叶特征','花特征','果实特征','花期','果期','生境'])
        row['分类接受状态']='Flora of China收录；GBIF原匹配仍为DOUBTFUL'
        row['分类体系']='Flora of China (2007) 物种条目；GBIF Backbone 原匹配为疑问名称'
        row['身份核对状态']='原始学名与Flora of China犁头草条目一致；分类数据库差异已注明，未经过人工审核'
        row['待核实说明']='已依据Flora of China补充植物形态与物候；GBIF DOUBTFUL与植物志收录存在差异，未宣称完成现行分类学审定。'
        # Print remaining structured FOC fields for the geographic translation step.
    row=next(r for r in plants if r['No']=='185')
    url='https://www.iplant.cn/ashx/getfoc.ashx?key=Viola+diffusa'
    foc=getjson(url)
    if foc_matches(foc,'Viola diffusa'):
        put(row,'规范学名','Viola diffusa Gingins','Flora of China（植物智数字版）',url,
            'contenttitle物种名称，采用该植物志体系；不宣称GBIF疑问状态已消除','Vol.13 (2007)')
        row['分类接受状态']='Flora of China收录；GBIF原匹配仍为DOUBTFUL'
        row['分类体系']='Flora of China (2007) 物种条目；GBIF Backbone 原匹配为疑问名称'
        row['身份核对状态']='原始学名与Flora of China七星莲条目一致；分类数据库差异已注明，未经过人工审核'
        row['待核实说明']='规范学名采用Flora of China (2007)体系；GBIF疑问状态保留。分布字段仍按原中国植物志原变种条目，不混入后附变种范围。'
    for row in plants:
        row.setdefault('补充植物志原文','');row.setdefault('补充植物志来源','');row.setdefault('候选植物资料JSON','{}')
    by_number={r['No']:r for r in plants}
    def from_existing(number,field,value,original_field,locator,replace=False):
        row=by_number[number]
        evidence=next(e for e in source_groups[number] if e['field']==original_field and e['value'])
        put(row,field,value,evidence['source_name'],evidence['url'],locator,evidence['version'],replace=replace)

    # A species page can include subordinate varieties. Select the requested main taxon.
    row=by_number['172']
    raw=row['植物志原文']
    if '木质藤本；' in raw and '1a. 木防己' in raw:
        morphology='木质藤本；'+raw.split('木质藤本；',1)[1].split('我国大部分地区',1)[0].strip()
        from_existing('172','形态描述',morphology,'植物志原文','物种总描述；不使用后附毛木防己变种的鉴别句',replace=True)
        from_existing('172','生长形态','木质藤本。','植物志原文','物种总描述开头',replace=True)
        from_existing('172','简短介绍','木防己为防己科木质藤本。叶形变化较大，常有3条掌状脉；聚伞花序，花单性；核果近球形，红色至紫红色。','植物志原文','物种总描述的中文摘要，排除后附毛木防己变种',replace=True)
        for field,prefix in [('叶特征','叶片纸质'),('花特征','聚伞花序少花'),('果实特征','核果近球形')]:
            value=prefix+morphology.split(prefix,1)[1].split('。',1)[0]+'。'
            from_existing('172',field,value,'植物志原文','物种总描述的对应器官句')
        value='我国大部分地区都有分布（西北部和西藏尚未见过），以长江流域中下游及其以南各省区常见。广布于亚洲东南部和东部以及夏威夷群岛。'
        from_existing('172','分布地区',value,'植物志原文','物种及原变种的分布句；排除后附毛木防己变种范围',replace=True)
        from_existing('172','生境','生于灌丛、村边、林缘等处。','植物志原文','物种及原变种的生境句',replace=True)
    raw=by_number['37']['植物志原文']
    leaf='茎下部叶'+raw.split('茎下部叶',1)[1].split('复伞形花序',1)[0].strip()
    from_existing('37','叶特征',leaf,'植物志原文','茎下部叶至复伞形花序前的完整叶部描述')
    raw=by_number['85']['形态描述']
    leaf='茎下部叶'+raw.split('茎下部叶',1)[1].split('头状花序',1)[0].strip()
    from_existing('85','叶特征',leaf,'形态描述','主形态描述的叶部句，保留位置及复叶特征')
    from_existing('229','叶特征','茎直立，无绿叶，下部被数枚膜质鞘。','药用植物形态原文','明确无绿叶的原文；不把缺少绿叶视为资料缺失')
    from_existing('242','叶特征','茎缠绕，黄色，纤细，直径约1毫米，无叶。','植物志原文','明确无叶的原文')
    for number in ['175','246']:
        raw=by_number[number]['药用植物形态原文']
        details=[s.strip() for s in re.split(r'(?<=[。；])',raw) if '鞘筒' in s or '鞘齿' in s]
        from_existing(number,'叶特征','叶鞘部位（来源原文称鞘筒、鞘齿）：'+' '.join(details),'药用植物形态原文','鞘筒、鞘齿的明确描述')
    from_existing('199','规范中文名','拳参','植物志原文','物种条目中文名；原始学名缩写的关联依据保留')
    from_existing('226','生境','来源记载的栽培状况：多栽培于庭园；江苏、浙江及华北各地多栽于盆中，冬季置于温室过冬。','生境分布原文','明确的栽培环境及越冬条件，不推断野生生境')
    for number in ['29','95','226','275']:
        row=by_number[number]
        rawfield='植物志原文' if row['植物志原文'] else '药用植物形态原文'
        old=row['果实特征']
        value='不适用：裸子植物不形成真正的果实，参见种子及球花特征。'
        if old:value+=' 来源中原列的生殖结构描述：'+old
        from_existing(number,'果实特征',value,rawfield,'植物志类群和种子结构核对；球果、假种皮不作为真正果实',replace=True)
    # Preserve the established 球花 terminology, with its botanical scope explicit.
    from_existing('226','花特征','裸子植物的生殖结构：雄球花圆柱形，长30–70厘米，直径8–15厘米；雌性大孢子叶扁平，密生绒毛，其下方两侧着生数枚近球形胚珠。','药用植物形态原文','雄球花及大孢子叶原文的中文转述')
    states=defaultdict(dict)
    for item in reviews:
        row=by_number[item['No']]
        field=item['问题说明'].split('：',1)[0]
        if field in row:
            if row[field].startswith('不适用：'):
                item['处理状态']='已确认不适用';states[item['No']][field]='不适用（已核对类群及原文）'
            elif row[field]:
                item['处理状态']='已按来源补充或核对，未经过人工审核';states[item['No']][field]='已取得来源资料'
            else:
                item['处理状态']='已复查现有来源，尚无可靠对应资料';states[item['No']][field]='已复查现有来源，尚无可靠对应资料'
        elif item['No']=='51':
            item['处理状态']='已进行7张图片抽样及植物志候选核查；训练类身份仍待逐图确认'
        elif item['No']=='200':
            item['处理状态']='已核对：西洋参为不同植物，不采用其药材资料'
        elif item['No'] in {'15','199'}:
            item['处理状态']='已有来源支持的异名或缩写关联；保留原始标签，未经过人工审核'
        else:
            item['处理状态']='已核对来源差异并保留说明，未经过人工审核'
    for row in plants:
        row['字段核对状态JSON']=json.dumps(states[row['No']],ensure_ascii=False,separators=(',',':'))
    def groups(rows):
        out=defaultdict(list)
        for row in rows:out[row['No']].append(row)
        return out
    mg,ig,sg,rg=map(groups,[meds,images,sources,reviews])
    for row in plants:
        n=row['No']
        row['活体植物分布地区']=clean_plant_distribution(row['分布地区'])
        row['分布资料状态']='有来源记载，已进行来源复查；未经过人工审核' if row['活体植物分布地区'] else '已检索，暂无可靠分布资料' if n!='51' else '身份冲突，暂不采用分布信息'
        row['药材记录JSON']=json.dumps(mg[n],ensure_ascii=False,separators=(',',':'))
        row['图片候选JSON']=json.dumps(ig[n],ensure_ascii=False,separators=(',',':'))
        row['字段证据JSON']=json.dumps(sg[n],ensure_ascii=False,separators=(',',':'))
        row['待核实事项JSON']=json.dumps(rg[n],ensure_ascii=False,separators=(',',':'))
        row['活体识别特征']=render_fields(row,['生长形态','株高特征','叶特征','花特征','果实特征','种子特征','茎特征','枝特征','根特征','孢子囊特征','雄球花特征','雌球花特征','识别要点'])
        row['药材完整介绍']=render_fields(row,['药材名称','药用部位','加工状态','药性','药味','归经','传统功效','传统应用','毒性','使用注意','药用部位原文','采收加工原文','性味功能原文','药材审核状态'])
        if mg[n]:row['药材完整介绍']+='\n\n对应药材详细记录\n'+ '\n\n'.join(render_fields(m,list(m)) for m in mg[n])
        row['资料来源名称']='；'.join(dict.fromkeys(e['source_name'] for e in sg[n]))
        row['资料来源链接']='；'.join(dict.fromkeys(e['url'] for e in sg[n]))
        row['活体植物完整介绍']='\n\n'.join(filter(None,[
            '植物名称：'+row['活体植物名称'],'识别对象：活体植物',
            render_fields(row,['原始学名','规范学名','植物别名','学名异名','规范科名','属名','资料科名中文','资料属名中文','身份核对状态','简短介绍']),
            '植物分布地区：'+(row['活体植物分布地区'] or row['分布资料状态']),
            render_fields(row,['分布资料状态','生境','海拔','花期','果期','孢子期','物候原文']),
            row['活体识别特征'],row['形态描述'],row['补充植物志原文'],
            render_fields(row,['易混淆植物','主要区别','易混淆风险','易混淆审核状态']),
            row['药材完整介绍'],render_fields(row,['药材产区','资料来源名称','资料来源链接','人工审核状态','待核实说明'])]))
    extra=['候选植物资料JSON','补充植物志原文','补充植物志来源','字段核对状态JSON']
    cols=columns+[c for c in extra if c not in columns]
    datasets={FILES[0]:{'columns':cols,'rows':[[r.get(c,'') for c in cols] for r in plants]},
              FILES[3]:{'columns':sourcecols,'rows':[[r[c] for c in sourcecols] for r in sources]},
              FILES[4]:{'columns':reviewcols,'rows':[[r[c] for c in reviewcols] for r in reviews]}}
    Path(output).write_text(json.dumps(datasets,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    result={'status':'PREPARED','changed_fields':len({(e['No'],e['field']) for e in edits}),
            'edit_operations':len(edits),'columns':len(cols),'evidence_records':len(sources),
            'review_records':len(reviews),'review_states':dict(Counter(r['处理状态'] for r in reviews)),
            'edits':edits,'coverage':{f:sum(bool(r[f]) and not r[f].startswith('不适用：') for r in plants)
            for f in ['根特征','叶特征','花特征','果实特征','生境','花期','果期','规范学名','简短介绍','毒性','使用注意','归经']}}
    (CACHE/'review_completion_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='edits'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--collect',action='store_true');parser.add_argument('--output')
    args=parser.parse_args()
    if args.collect:collect()
    if args.output:make(args.output)
