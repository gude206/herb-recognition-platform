"""Source-backed TCMP-300 enrichment; keep the four original label columns intact."""
from pathlib import Path
import argparse, base64, csv, hashlib, json, re, time, urllib.request, urllib.parse, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
from lxml import html as LH
from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'author_tcmp_300'
CACHE = DATA / 'enrichment_sources_20260930'
DATE = '2026-09-30'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def fetch(url):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    result = {'url': url, 'retrieved_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TCMP300-metadata-research/1.0 (educational; source attribution)'})
            with urllib.request.urlopen(req, timeout=22) as response:
                payload = response.read()
                result.update(status=response.status, body=payload.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'))
            break
        except Exception as exc:
            result.update(status=0, error=str(exc))
            if attempt == 0:
                time.sleep(1)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result

def text_of(html):
    if not html: return ''
    soup = LH.fromstring(html)
    for tag in soup.xpath('//script|//style'):
        tag.drop_tree()
    return '\n'.join(t.strip() for t in soup.itertext() if t.strip())

def probe():
    urls = {
      'iplant_z': 'https://www.iplant.cn/info/' + urllib.parse.quote('阿拉伯婆婆纳') + '?t=z',
      'iplant_frps': 'https://www.iplant.cn/info/' + urllib.parse.quote('阿拉伯婆婆纳') + '?t=frps',
      'iplant_js': 'https://www.iplant.cn/Scripts/plantinfo2.js?202510211604',
      'mpd_home': 'https://sys01.lib.hkbu.edu.hk/cmed/mpid/index.php?lang=chs',
      'mmd_home': 'https://sys01.lib.hkbu.edu.hk/cmed/mmid/index.php?lang=chs',
      'gbif': 'https://api.gbif.org/v1/species/match?name=Veronica%20persica',
    }
    for name, url in urls.items():
        rec = fetch(url)
        print('\nPROBE', name, rec.get('status'), rec.get('error',''), flush=True)
        body = rec.get('body', '')
        if name == 'iplant_js':
            print('\n'.join(line for line in body.splitlines() if re.search('ajax|url:|getJSON|spno|http|handler',line))[:14000])
        else:
            print(text_of(body)[:11000])
            soup = LH.fromstring(body) if body else LH.fromstring('<div/>')
            print('LINKS', [(a.text_content().strip(),a.get('href')) for a in soup.xpath('//a[@href]') if any(x in a.get('href','') for x in ['detail','search','list','species','browse'])][:30])
            print('FORMS', [LH.tostring(f,encoding='unicode')[:4000] for f in soup.xpath('//form')])
        (CACHE / (name + '_probe.html')).write_text(body,encoding='utf-8')

def probe2():
    urls = {
      'plant_desc': 'https://www.iplant.cn/ashx/plantinfo.ashx?spid=29834&type=descall',
      'plant_class': 'https://www.iplant.cn/ashx/getspinfos.ashx?spid=29834',
      'mpd_query': 'https://sys01.lib.hkbu.edu.hk/cmed/mpid/index.php?lang=chs&qry=' + urllib.parse.quote('Datura metel'),
      'mmd_query': 'https://sys01.lib.hkbu.edu.hk/cmed/mmid/index.php?lang=chs&qry=' + urllib.parse.quote('Datura metel'),
      'mpd_detail': 'https://sys01.lib.hkbu.edu.hk/cmed/mpid/detail.php?lang=chs&herb_id=D01304',
      'mmd_detail': 'https://sys01.lib.hkbu.edu.hk/cmed/mmid/detail.php?lang=chs&pid=B00238',
    }
    for name,url in urls.items():
        rec = fetch(url); body=rec.get('body','')
        print('\nPROBE2', name, rec.get('status'), rec.get('error',''),flush=True)
        print(text_of(body)[:16000])
        if body:
            doc=LH.fromstring(body)
            print('DETAIL LINKS', [(a.text_content().strip(),a.get('href')) for a in doc.xpath('//a[@href]') if 'detail.php' in a.get('href','')][:30])
        (CACHE / (name + '_probe.html')).write_text(body,encoding='utf-8')

def compact(value):
    return re.sub(r'\s+', ' ', value or '').strip()

def canonical(value):
    value=compact(value)
    m=re.match(r'([A-Z][a-z]+)\s+([a-z][a-z-]+)',value)
    if not m: return value
    name=m.group(0)
    infra=re.search(r'\b(var\.|subsp\.|f\.)\s+([a-z][a-z-]+)',value)
    if infra: name += ' ' + infra.group(0)
    return name

def json_fetch(url):
    rec=fetch(url)
    try: return json.loads(rec.get('body',''))
    except (ValueError,TypeError): return {}

def gbif_match(name):
    url='https://api.gbif.org/v1/species/match?' + urllib.parse.urlencode({'name':compact(name),'kingdom':'Plantae','strict':'true'})
    match=json_fetch(url)
    if match.get('matchType') not in ['EXACT','FUZZY'] or match.get('rank') not in ['SPECIES','SUBSPECIES','VARIETY','FORM'] or match.get('confidence',0)<90:
        return {},url
    if match.get('status')=='SYNONYM' and match.get('acceptedUsageKey'):
        accepted_url='https://api.gbif.org/v1/species/' + str(match['acceptedUsageKey'])
        accepted=json_fetch(accepted_url)
        if accepted: match['accepted_record']=accepted
    return match,url

def gbif_key(match):
    return match.get('acceptedUsageKey',match.get('usageKey'))

def hk_fields(body):
    if not body: return {},None
    doc=LH.fromstring(body)
    fields={}
    for td in doc.xpath('//td'):
        label=compact(td.text_content())
        if re.fullmatch('【[^】]+】',label):
            sibling=td.getnext()
            if sibling is not None:
                fields[label[1:-1]]=compact(sibling.text_content())
    return fields,doc

def hk_search(db,query):
    base='https://sys01.lib.hkbu.edu.hk/cmed/' + db + '/'
    url=base+'index.php?'+urllib.parse.urlencode({'lang':'chs','qry':query})
    rec=fetch(url)
    if not rec.get('body'): return []
    doc=LH.fromstring(rec['body']); links=[]
    for a in doc.xpath('//a[@href]'):
        href=a.get('href','')
        if 'detail.php' in href and ('herb_id=' in href if db=='mpid' else 'pid=' in href):
            qs=urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            key='herb_id' if db=='mpid' else 'pid'
            link=base+'detail.php?'+urllib.parse.urlencode({'lang':'chs',key:qs[key][0]})
            if link not in links: links.append(link)
    return links

def decode_desc(value):
    try: return compact(text_of(base64.b64decode(value).decode('utf-8')))
    except Exception: return ''

def collect_one(original):
    number=int(original['No']); row=dict(original); evidence=[]; issues=[]; meds=[]; pictures=[]
    original_name=compact(original['Latin Name'])
    match,gbif_url=gbif_match(original_name)
    if not match and canonical(original_name)!=original_name:
        match,gbif_url=gbif_match(canonical(original_name))
    candidate={}; desc={}; plant_url=''; plant_valid=False; mpd={}; mpd_url=''
    def put(field,value,source,url,locator='',status='来源已读取，自动提取待人工复核',version='网页，未声明版本'):
        if not value: return
        if field not in row or not row[field]: row[field]=value
        evidence.append({'No':original['No'],'field':field,'value':value,'source_name':source,'url':url,'version':version,'locator':locator,'status':status,'retrieved_date':DATE})
    row.update({'植物ID':f'tcmp-{number:03d}','原始学名':original['Latin Name'],'原始科名':original['Family'],'身份核对状态':'待核实','药材审核状态':'未找到匹配资料','毒性审核状态':'未核实','易混淆审核状态':'待人工核实','图片审核状态':'候选图片，器官与授权待核实','人工审核状态':'未人工审核','更新日期':DATE})
    if match:
        accepted=match.get('accepted_record',match)
        for field,key in [('规范学名','scientificName'),('规范科名','family'),('属名','genus')]:
            put(field,accepted.get(key),'GBIF Backbone Taxonomy',gbif_url,key,status='分类数据库匹配，植物身份待交叉核对',version='GBIF v1 species API，查询日期 '+DATE)
        put('分类数据库ID',str(gbif_key(match)),'GBIF Backbone Taxonomy',gbif_url,'acceptedUsageKey / usageKey')
        put('分类体系','GBIF Backbone Taxonomy','GBIF Backbone Taxonomy',gbif_url,'classification')
        put('学名匹配类型',match.get('matchType'),'GBIF Backbone Taxonomy',gbif_url,'matchType')
        put('学名匹配置信度',str(match.get('confidence','')),'GBIF Backbone Taxonomy',gbif_url,'confidence')
    else:
        issues.append('原始学名未获得可靠的GBIF种级匹配')
    queries=[original['Chinese Name'],canonical(original_name)]
    for query in dict.fromkeys(queries):
        url='https://www.iplant.cn/info/'+urllib.parse.quote(query)+'?t=z'
        rec=fetch(url); body=rec.get('body','')
        sp=re.search(r'var spno\s*=\s*"([^"]+)"',body)
        latin=re.search(r'var latin2\s*=\s*"([^"]+)"',body)
        cname=re.search(r'var spcname\s*=\s*"([^"]+)"',body)
        if not sp or not latin: continue
        candidate={'spid':sp.group(1),'latin':latin.group(1),'chinese':cname.group(1) if cname else '', 'url':url}
        source_match,source_gbif_url=gbif_match(candidate['latin'])
        same_name=canonical(candidate['latin']).lower()==canonical(original_name).lower()
        same_key=bool(match and source_match and gbif_key(match)==gbif_key(source_match))
        if number==51:
            issues.append('原始中文名地肤与原始学名Geranium wilfordii冲突；植物智中文名候选为'+candidate['latin']+'；须核查该类训练图片后确定植物身份')
            break
        if not (same_name or same_key):
            issues.append('植物智查询 '+query+' 返回 '+candidate['chinese']+' '+candidate['latin']+'，未通过学名一致性检查')
            continue
        plant_url=url; plant_valid=True
        row['身份核对状态']='学名与来源一致，待人工复核' if same_name else '分类数据库异名关联一致，待人工复核'
        put('规范中文名',candidate['chinese'],'植物智',url,'spcname')
        put('植物智学名',candidate['latin'],'植物智',url,'latin2')
        doc=LH.fromstring(body)
        aliases=doc.xpath('//div[contains(@class,"infomore")]//a/text()')
        put('植物别名','；'.join(dict.fromkeys(aliases)),'植物智',url,'俗名')
        desc_url='https://www.iplant.cn/ashx/plantinfo.ashx?'+urllib.parse.urlencode({'spid':candidate['spid'],'type':'descall'})
        desc=json_fetch(desc_url)
        flat={}
        for group in desc.get('spdesc',[]):
            for d in group.get('desclist',[]):
                if d.get('desc'):
                    flat[d['subname']]=(decode_desc(d['desc']),str(d.get('spdescid','')))
        mapping={'生活型':'生长形态','株':'株高特征','根':'根特征','茎':'茎特征','枝':'枝特征','叶':'叶特征','花':'花特征','果':'果实特征','种子':'种子特征','形态特征':'形态描述','识别要点':'识别要点','分布':'分布地区','产地':'产地描述','生境':'生境','海拔':'海拔','物候':'物候原文','分类讨论':'分类讨论','经济价值':'经济价值','孢子囊':'孢子囊特征','雄球花':'雄球花特征','雌球花':'雌球花特征'}
        for key,field in mapping.items():
            if key in flat: put(field,flat[key][0],'植物智',url,'结构化名片/'+key+'/spdescid='+flat[key][1])
        if not row.get('生境') and '产地描述' in row:
            habitat=re.findall(r'(?:生于|生长于|生长在|常见于|生在|多生于)[^。；]+',row['产地描述'])
            put('生境','；'.join(habitat),'植物智',url,'产地描述中明确生境句')
        phen=row.get('物候原文','')
        for label,field in [('花期','花期'),('果期','果期')]:
            m=re.search(label+r'([^。；，]+)',phen)
            if m: put(field,m.group(1).strip('：: '),'植物智',url,'物候/'+label)
        frps_url='https://www.iplant.cn/ashx/getfrps.ashx?'+urllib.parse.urlencode({'key':candidate['latin']})
        frps=json_fetch(frps_url)
        if frps.get('frpsdesc'):
            frps_text=compact(text_of(frps['frpsdesc']))
            put('植物志原文',frps_text,'中国植物志（植物智数字版）',url,'frpsdesc',version='来源条目所载版本；见原文及引用')
            put('植物志引用',compact(text_of(frps.get('frpslink',''))),'中国植物志（植物智数字版）',url,'frpslink')
        break
    if not plant_valid:
        row['身份核对状态']='中文名与学名冲突，待人工核实' if number==51 else '植物智身份未核对，待人工核实'
    if number!=51:
        lookup_names=[canonical(original_name)]
        if plant_valid: lookup_names.append(candidate['latin'])
        for lookup in dict.fromkeys(lookup_names):
            for url in hk_search('mpid',lookup)[:3]:
                rec=fetch(url); fields,doc=hk_fields(rec.get('body',''))
                latin=fields.get('拉丁学名','')
                exact=canonical(latin).lower()==canonical(original_name).lower()
                if not exact:
                    other,_=gbif_match(latin)
                    exact=bool(match and other and gbif_key(other)==gbif_key(match))
                if not exact: continue
                mpd,mpd_url=fields,url
                for field,key in [('药用植物形态原文','植物形态'),('生境分布原文','生境分布'),('药用部位原文','药用部位'),('采收加工原文','采收加工'),('性味功能原文','性味功能')]:
                    put(field,fields.get(key),'香港浸会大学药用植物图像数据库',url,'【'+key+'】')
                if not row.get('生长形态'):
                    m=re.match(r'((?:一年生|二年生|多年生|常绿|落叶)?(?:草本|乔木|灌木|藤本|攀援灌木|木质藤本|草质藤本))',fields.get('植物形态',''))
                    if m: put('生长形态',m.group(1),'香港浸会大学药用植物图像数据库',url,'【植物形态】开头')
                for field,label in [('花期','花期'),('果期','果期')]:
                    if not row.get(field):
                        m=re.search(label+r'([^。；，]+)',fields.get('植物形态',''))
                        if m: put(field,m.group(1),'香港浸会大学药用植物图像数据库',url,'【植物形态】/'+label)
                if doc is not None:
                    for img in doc.xpath('//img[@src]'):
                        src=img.get('src','')
                        if re.search(r'images/D\d+[^/]*\.(jpg|png|jpeg)',src,re.I):
                            pictures.append({'No':original['No'],'植物ID':row['植物ID'],'图片URL或路径':urllib.parse.urljoin(url,src),'图片类型':'植物资料图片候选，器官未审核','来源页面':url,'授权':'All rights reserved；需取得转载授权','审核状态':'待人工审核，未发布'})
                break
            if mpd: break
        # A medicinal material association must be supported by its own source definition.
        med_names=list(dict.fromkeys(lookup_names+([canonical(mpd.get('拉丁学名',''))] if mpd else [])))
        med_links=[]
        for name in med_names:
            if name:
                med_links.extend(hk_search('mmid',name))
                if med_links: break
        for url in list(dict.fromkeys(med_links))[:10]:
            rec=fetch(url); fields,doc=hk_fields(rec.get('body',''))
            source=fields.get('来源','')
            assoc_names=[canonical(original_name)]
            if mpd: assoc_names.append(canonical(mpd.get('拉丁学名','')))
            if plant_valid: assoc_names.append(candidate['latin'])
            supported=any(re.search(re.escape(name)+r'(?![a-z])',source,re.I) for name in assoc_names if name)
            if not supported:
                issues.append('中药材候选 '+fields.get('名称','')+' 未通过【来源】植物基原核对：'+url)
                continue
            med={'No':original['No'],'植物ID':row['植物ID'],'药材ID':urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['pid'][0],'药材名称':fields.get('名称',''),'药材来源原文':source,'药材类别':fields.get('类别',''),'性味原文':fields.get('性味',''),'传统功效原文':fields.get('功效',''),'炮制品原文':fields.get('炙品',fields.get('炮制','')),'来源链接':url,'药典核对状态':'未与2025年版药典核对','审核状态':'来源基原文字匹配，待人工复核'}
            nature=med['性味原文']; med['药性']='；'.join(dict.fromkeys(re.findall(r'微寒|微温|大热|大寒|寒|热|温|凉|平',nature)))
            med['药味']='；'.join(dict.fromkeys(re.findall(r'微苦|微甘|微辛|苦|甘|辛|酸|咸|涩|淡',nature)))
            toxic=re.search(r'(?:有大毒|有小毒|有毒|小毒|大毒|无毒)',nature)
            med['毒性记载']=toxic.group(0) if toxic else ''
            mer=re.search(r'归([^。；]+?经)',nature)
            med['归经']=mer.group(1) if mer else ''
            # Do not infer processed products' properties from a source herb.
            med['加工状态']= '干燥药材' if '干燥' in source else ''
            part=re.search(r'的(?:干燥)?((?:成熟|近成熟|未成熟)?[^。]+)',source)
            med['药用部位']=part.group(1) if part else ''
            warnings=[]
            for key,value in fields.items():
                for sent in re.split(r'(?<=[。；])',value):
                    if re.search(r'禁用|慎用|不宜|忌用|中毒|有毒|大毒|小毒',sent): warnings.append('【'+key+'】'+sent)
            med['使用注意原文']=' '.join(dict.fromkeys(warnings))
            # Split only explicitly marked traditional indications; retain full source separately.
            efficacy=fields.get('功效','')
            app=re.search(r'(用于[^。]+[。]?)',efficacy)
            med['传统应用']=app.group(1) if app else ''
            meds.append(med)
    if mpd and not meds:
        # The botanical database states medicinal use but may lack a material monograph.
        medicinal=mpd.get('药用部位','')
        if medicinal:
            row['药材审核状态']='仅植物资料记载药用部位，待药材基原与药典核实'
    if meds:
        row['药材审核状态']='有来源基原匹配，待药典及人工核验'
        for field in ['药材名称','药用部位','加工状态','药性','药味','归经','传统应用','毒性记载','使用注意原文']:
            values=[m['药材名称']+'：'+m[field] for m in meds if m.get(field)]
            if values:
                target={'毒性记载':'毒性','使用注意原文':'使用注意'}.get(field,field)
                row[target]='；'.join(values)
                for m in meds:
                    if m.get(field): evidence.append({'No':original['No'],'field':target,'value':m['药材名称']+'：'+m[field],'source_name':'香港浸会大学中药材图像数据库','url':m['来源链接'],'version':'网页，未声明版本','locator':'药材 '+m['药材名称']+' 对应字段','status':'来源已读取，未与2025药典核对','retrieved_date':DATE})
        row['传统功效']='；'.join(m['药材名称']+'：'+m['传统功效原文'] for m in meds if m['传统功效原文'])
        if row.get('毒性'): row['毒性审核状态']='数据库有明确记载，待药典和人工核验'
    if not row.get('毒性') and mpd:
        toxic=re.search(r'(?:有大毒|有小毒|有毒|小毒|大毒|无毒)',mpd.get('性味功能',''))
        if toxic:
            put('毒性','植物资料药用部位对应记载：'+toxic.group(0),'香港浸会大学药用植物图像数据库',mpd_url,'【性味功能】；对应【药用部位】')
            row['毒性审核状态']='植物资料有记载，待药典和人工核验'
    if plant_valid:
        snippets=[row.get(k,'') for k in ['生长形态','株高特征','茎特征','叶特征','花特征'] if row.get(k)]
        if snippets:
            summary=original['Chinese Name']+'（'+candidate['latin']+'）。'+''.join(snippets)
            if len(summary)>180: summary=summary[:179]+'…'
            put('简短介绍',summary,'植物智',plant_url,'已提取形态字段组合摘录；长度不超过180字符',status='来源摘录组合，待编辑复核')
    # Existing dataset image is only a class-labelled candidate, not an organ annotation.
    train=DATA/'images'/'tcmp-300'/'train'
    folders=list(train.glob(f'{number:03d}.*'))
    if folders:
        imgs=sorted(p for p in folders[0].iterdir() if p.suffix.lower() in ['.jpg','.jpeg','.png','.webp'])
        if imgs:
            local=imgs[0].relative_to(ROOT).as_posix()
            row['封面图候选']=local
            pictures.append({'No':original['No'],'植物ID':row['植物ID'],'图片URL或路径':local,'图片类型':'类别封面候选，器官未审核','来源页面':'https://huggingface.co/datasets/anzhulin/tcmp-300','授权':'数据集图像授权待核实','审核状态':'待人工审核，未发布'})
    if pictures:
        row['图片候选JSON']=json.dumps(pictures,ensure_ascii=False)
    row['药材记录JSON']=json.dumps(meds,ensure_ascii=False) if meds else ''
    row['待核实说明']='；'.join(dict.fromkeys(issues))
    urls=list(dict.fromkeys(e['url'] for e in evidence))
    row['资料来源链接']='；'.join(urls)
    row['资料来源名称']='；'.join(dict.fromkeys(e['source_name'] for e in evidence))
    row['字段来源JSON']=json.dumps(evidence,ensure_ascii=False)
    result={'row':row,'evidence':evidence,'issues':issues,'medicinal_materials':meds,'images':pictures,'iplant_candidate':candidate,'gbif_match':match}
    (CACHE/f'row_{number:03d}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def collect(limit=300):
    original=DATA/'tcmp-info-20250329.original.csv'
    if not original.exists(): original=DATA/'tcmp-info-20250329.csv'
    with original.open(encoding='utf-8-sig',newline='') as f:
        rows=[{k:r[k] for k in ['No','Latin Name','Family','Chinese Name']} for r in csv.DictReader(f)][:limit]
    completed=0
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks={pool.submit(collect_one,row):row for row in rows}
        for future in as_completed(tasks):
            original=tasks[future]
            try:
                result=future.result(); completed+=1
                print(json.dumps({'completed':completed,'No':original['No'],'name':original['Chinese Name'],'identity':result['row']['身份核对状态'],'evidence':len(result['evidence']),'medicinal_records':len(result['medicinal_materials'])},ensure_ascii=False),flush=True)
            except Exception as exc:
                print('ERROR '+original['No']+' '+repr(exc),flush=True)

def source_latin_names(text):
    """Recognize taxa even when botanical authors separate the binomial and rank."""
    names=[]
    for m in re.finditer(r'([A-Z][a-z]+)\s+([a-z][a-z-]+)([^\u3400-\u9fff。；、]{0,150})',text):
        name=m.group(1)+' '+m.group(2)
        infra=re.search(r'\b(var\.|subsp\.|f\.)\s+([a-z][a-z-]+)',m.group(3))
        if infra: name+=' '+infra.group(0)
        names.append(name)
    return list(dict.fromkeys(names))

def enrich_more():
    """Resolve authored infraspecific sources and reuse medicinal plant cross-links."""
    records=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(CACHE.glob('row_*.json'))]
    jobs=[]
    def additional_queries(result):
        row=result['row']
        if row['No']=='51': return []
        links=hk_search('mmid',row['Chinese Name'])
        # Follow observed pagination rather than assuming all matches fit page 1.
        index='https://sys01.lib.hkbu.edu.hk/cmed/mmid/index.php?'+urllib.parse.urlencode({'lang':'chs','qry':row['Chinese Name']})
        rec=fetch(index)
        if rec.get('body'):
            doc=LH.fromstring(rec['body'])
            pages=[]
            for a in doc.xpath('//a[@href]'):
                href=a.get('href','')
                qs=urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                if href.startswith('index.php') and qs.get('page') and qs.get('qry')==[row['Chinese Name']]:
                    n=int(qs['page'][0])
                    if n<=8 and n not in pages: pages.append(n)
            for page in sorted(pages):
                page_url=index+'&page='+str(page)
                page_rec=fetch(page_url)
                if not page_rec.get('body'): continue
                page_doc=LH.fromstring(page_rec['body'])
                for a in page_doc.xpath('//a[@href]'):
                    href=a.get('href','')
                    if 'detail.php' in href and 'pid=' in href:
                        qs=urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        url='https://sys01.lib.hkbu.edu.hk/cmed/mmid/detail.php?'+urllib.parse.urlencode({'lang':'chs','pid':qs['pid'][0]})
                        if url not in links: links.append(url)
        return links
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={pool.submit(additional_queries,result):result for result in records}
        completed_queries=0
        for future in as_completed(pending):
            result=pending[future]
            try:
                for url in future.result():
                    if url not in [m['来源链接'] for m in result['medicinal_materials']]: jobs.append((result,url))
                completed_queries+=1
                if completed_queries%30==0: print('Medicinal supplemental queries',completed_queries,flush=True)
            except Exception as exc:
                print('Additional query error',result['row']['No'],str(exc),flush=True)
    for result in records:
        row=result['row']
        if row['No']=='51': continue
        sources=[e['url'] for e in result['evidence'] if e['source_name']=='香港浸会大学药用植物图像数据库']
        if sources:
            rec=fetch(sources[0]); fields,doc=hk_fields(rec.get('body',''))
            if doc is not None:
                for a in doc.xpath('//a[@href]'):
                    href=a.get('href','')
                    if '/mmid/detail.php' in href or ('mmid' in href and 'pid=' in href):
                        qs=urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        if qs.get('pid'):
                            url='https://sys01.lib.hkbu.edu.hk/cmed/mmid/detail.php?'+urllib.parse.urlencode({'lang':'chs','pid':qs['pid'][0]})
                            if url not in [m['来源链接'] for m in result['medicinal_materials']]: jobs.append((result,url))
    # Rejected medicinal source definitions often include authors before var./subsp.
    for result in records:
        for issue in result['issues']:
            if issue.startswith('中药材候选') and 'https://' in issue:
                jobs.append((result,issue[issue.index('https://'):]))
    seen=set()
    for job_index,(result,url) in enumerate(jobs):
        if job_index%30==0: print('Checking supplemental material',job_index,'of',len(jobs),flush=True)
        key=(result['row']['No'],url)
        if key in seen: continue
        seen.add(key)
        rec=fetch(url); fields,_=hk_fields(rec.get('body',''))
        names=source_latin_names(fields.get('来源',''))
        originals=[canonical(result['row']['Latin Name']),canonical(result['row'].get('植物智学名',''))]
        supported=any(x.lower()==y.lower() for x in names for y in originals if y)
        if not supported:
            # Accept a taxonomic synonym only when both usage keys agree.
            for name in names:
                if not result['gbif_match']: break
                other,_=gbif_match(name)
                if other and gbif_key(other)==gbif_key(result['gbif_match']): supported=True; break
        if not supported: continue
        # Store fields here; the exporter performs one uniform material parser.
        result.setdefault('extra_medical_sources',[]).append({'url':url,'fields':fields})
        result['issues']=[i for i in result['issues'] if url not in i]
    for result in records:
        (CACHE/f"row_{int(result['row']['No']):03d}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Additional medicinal sources',sum(len(r.get('extra_medical_sources',[])) for r in records),flush=True)

MAIN_COLUMNS = ['No','Latin Name','Family','Chinese Name','植物ID','原始学名','原始科名','规范中文名','规范学名','植物别名','学名异名','规范科名','属名','资料科名中文','资料属名中文','分类体系','分类数据库ID','原始学名分类状态','分类接受状态','学名匹配类型','学名匹配置信度','身份核对状态','候选学名','候选植物来源','简短介绍','生长形态','株高特征','叶特征','花特征','果实特征','种子特征','茎特征','枝特征','根特征','孢子囊特征','雄球花特征','雌球花特征','识别要点','形态描述','分布地区','生境','海拔','花期','果期','物候原文','孢子期','易混淆植物','主要区别','易混淆原文','易混淆风险','易混淆审核状态','药材名称','药用部位','加工状态','药性','药味','归经','传统功效','传统应用','毒性','使用注意','药材审核状态','毒性审核状态','封面图','全株图','叶片图','花果图','封面图候选','图片候选JSON','图片审核状态','植物智学名','植物志引用','植物志原文','药用植物形态原文','生境分布原文','药用部位原文','采收加工原文','性味功能原文','药材记录JSON','资料来源名称','资料来源链接','字段来源JSON','资料版本','来源页码','检索日期','人工审核状态','待核实说明','更新日期']

def material_from_fields(fields,url,row):
    source=fields.get('来源',''); nature=fields.get('性味',''); efficacy=fields.get('功效','')
    med={'No':row['No'],'植物ID':row['植物ID'],'药材ID':urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['pid'][0],'药材名称':fields.get('名称',''),'药材来源原文':source,'药材类别':fields.get('类别',''),'性味原文':nature,'传统功效原文':efficacy,'炮制品原文':fields.get('炙品',fields.get('炮制','')),'来源链接':url,'药典核对状态':'未与2025年版药典核对','审核状态':'来源基原核对，待人工复核'}
    med['药性']='；'.join(dict.fromkeys(re.findall(r'微寒|微温|大热|大寒|寒|热|温|凉|平',nature)))
    med['药味']='；'.join(dict.fromkeys(re.findall(r'微苦|微甘|微辛|苦|甘|辛|酸|咸|涩|淡',nature)))
    toxic=re.search(r'(?:有大毒|有小毒|有毒|小毒|大毒|无毒)',nature); med['毒性记载']=toxic.group(0) if toxic else ''
    mer=re.search(r'归([^。；]+?经)',nature); med['归经']=mer.group(1) if mer else ''
    med['加工状态']='干燥药材' if '干燥' in source else ''
    parts=re.findall(r'的(?:干燥)?([^。]+)',source); med['药用部位']=parts[-1] if parts else ''
    med['使用注意原文']=' '.join(dict.fromkeys('【'+key+'】'+sent for key,value in fields.items() for sent in re.split(r'(?<=[。；])',value) if re.search(r'禁用|慎用|不宜|忌用|中毒|有毒|大毒|小毒',sent)))
    app=re.search(r'(用于[^。]+[。]?)',efficacy); med['传统应用']=app.group(1) if app else ''
    med['基原关联类型']='植物直接药材基原'
    if fields.get('名称')=='虫白蜡' and '昆虫' in source:
        med['基原关联类型']='昆虫分泌物，该植物是寄主'
        med['药用部位']='非植物部位；白蜡虫分泌蜡，来源原文见药材来源原文'
        med['加工状态']='昆虫分泌蜡，经精制'
    elif '虫瘿' in source:
        med['基原关联类型']='虫瘿，昆虫诱导的植物组织'
        med['药用部位']='虫瘿'
    return med

def processed_materials(parent):
    text=parent.get('炮制品原文','')
    labels=list(re.finditer(r'([\u3400-\u9fff]{2,12}(?:\s*[(（][^（）()]{1,20}[)）])?)\s*[:：]',text))
    results=[]
    for index,label in enumerate(labels):
        name=label.group(1).strip()
        if name=='有机人参': continue  # Certification is not a processing method.
        segment=text[label.end():labels[index+1].start() if index+1<len(labels) else len(text)].strip()
        mer=re.search(r'归([^。；]+?经)',segment)
        med={'No':parent['No'],'植物ID':parent['植物ID'],'药材ID':parent['药材ID']+'#processed-'+str(index+1),'药材名称':name,'药材来源原文':parent['药材来源原文'],'药材类别':parent['药材类别'],'性味原文':'','传统功效原文':'','炮制品原文':segment,'来源链接':parent['来源链接'],'药典核对状态':'未与2025年版药典及炮制规范核对','审核状态':'来源【炙品】明确列出的制品，待人工复核','药性':'','药味':'','毒性记载':'','归经':mer.group(1) if mer else '','加工状态':'炮制品（来源【炙品】所列）','药用部位':parent['药用部位'],'使用注意原文':'','传统应用':'','对应原药材名称':parent['药材名称'],'对应原药材ID':parent['药材ID'],'基原关联类型':'来源药材的炮制品'}
        # Product-specific properties only; never inherit raw-material toxicity.
        properties=re.search(r'(?:性味\s*)?([辛甘苦酸咸涩淡微温寒热凉平、，,\s]{2,50})[。；]?\s*归',segment)
        if properties:
            nature=properties.group(1).strip('，, ')
            med['性味原文']=nature
            med['药性']='；'.join(dict.fromkeys(re.findall(r'微寒|微温|寒|热|温|凉|平',nature)))
            med['药味']='；'.join(dict.fromkeys(re.findall(r'微苦|微甘|微辛|苦|甘|辛|酸|咸|涩|淡',nature)))
        toxicity=re.search(r'(?:有大毒|有小毒|有毒|小毒|大毒|无毒)',segment)
        if toxicity: med['毒性记载']=toxicity.group(0)
        app=re.search(r'用于[^。]+[。]?',segment)
        if app: med['传统应用']=app.group(0)
        results.append(med)
    return results

def prepare_export():
    files=sorted(CACHE.glob('row_*.json'))
    if len(files)!=300: raise ValueError(f'Expected 300 collected records, got {len(files)}')
    records=[json.loads(p.read_text(encoding='utf-8')) for p in files]
    all_evidence=[]; all_meds=[]; all_images=[]; review=[]
    for result in records:
        row=result['row']; evidence=result['evidence']; number=int(row['No'])
        def add(field,value,source,url,locator,status='来源已读取，自动提取待人工复核',version='网页，未声明版本'):
            if not value: return
            row[field]=value
            evidence.append({'No':row['No'],'field':field,'value':value,'source_name':source,'url':url,'version':version,'locator':locator,'status':status,'retrieved_date':DATE})
        plant_url=result.get('iplant_candidate',{}).get('url','')
        mpd_urls=list(dict.fromkeys(e['url'] for e in evidence if e['source_name']=='香港浸会大学药用植物图像数据库'))
        mpd={}; mpd_url=mpd_urls[0] if mpd_urls else ''
        if mpd_url: mpd,_=hk_fields(fetch(mpd_url).get('body',''))
        if number==51:
            for field in ['规范学名','规范科名','属名','分类数据库ID','分类体系','学名匹配类型','学名匹配置信度']:
                row.pop(field,None)
            evidence[:]=[e for e in evidence if e['field'] not in ['规范学名','规范科名','属名','分类数据库ID','分类体系','学名匹配类型','学名匹配置信度']]
            add('候选学名',result['iplant_candidate'].get('latin',''),'植物智',plant_url,'中文名地肤查询候选，尚未采用','原始身份冲突，待人工审核')
            row['候选植物来源']=plant_url
            row['易混淆风险']='原始中文名与学名冲突；规范植物资料暂不采用，须核查该类别图片身份'
        # The page also links alternative search hits; these are not aliases.
        if number!=51 and plant_url:
            body=fetch(plant_url).get('body','')
            doc=LH.fromstring(body) if body else None
            chinese=[]; latin=[]; alternatives=[]
            if doc is not None:
                for box in doc.xpath('//div[contains(@class,"infomore")]'):
                    label=compact(box.text_content())
                    names=[compact(a.text_content()) for a in box.xpath('.//a')]
                    if '您是否要找' in label or '同名植物' in label:
                        alternatives.extend(names); continue
                    if not ('俗名' in label or '异名' in label): continue
                    for name in names:
                        scientific=source_latin_names(name)
                        latin.extend(scientific)
                        cn=re.split(r'[A-Z][a-z]+\s+[a-z]',name)[0].strip()
                        if re.search(r'[\u3400-\u9fff]',cn): chinese.append(cn)
            row['植物别名']=''; row['学名异名']=''
            evidence[:]=[e for e in evidence if e['field'] not in ['植物别名','学名异名']]
            if chinese: add('植物别名','；'.join(dict.fromkeys(chinese)),'植物智',plant_url,'明确标为俗名或异名的中文名称，不包含其他检索候选')
            if latin: add('学名异名','；'.join(dict.fromkeys(latin)),'植物智',plant_url,'明确标为异名的科学名称；接受状态仍以分类数据库为准')
            if alternatives:
                add('易混淆风险','名称检索还列出其他植物候选，需用学名区分：'+'；'.join(dict.fromkeys(alternatives)),'植物智',plant_url,'您是否要找/同名植物检索候选；表示名称歧义，不代表形态易混淆','名称检索存在歧义，待人工核实')
        # Some source life-form slots contain a comparative diagnosis instead.
        life=row.get('生长形态','')
        if '区别' in life or len(life)>100:
            add('识别要点',life,'植物智',plant_url,'来源生活型字段中的比较描述，移至识别要点')
            row.pop('生长形态',None); evidence[:]=[e for e in evidence if e['field']!='生长形态']
        # A species page may append several subspecies. Keep only the first
        # morphology block for fallback extraction, not every appended variant.
        flora_paragraphs=[]
        if row.get('植物志原文') and result.get('iplant_candidate',{}).get('latin'):
            frps_url='https://www.iplant.cn/ashx/getfrps.ashx?'+urllib.parse.urlencode({'key':result['iplant_candidate']['latin']})
            raw_frps=json_fetch(frps_url).get('frpsdesc','')
            if raw_frps:
                flora_doc=LH.fromstring(raw_frps)
                paras=[compact(p.text_content()) for p in flora_doc.xpath('//p')]
                if not row.get('规范中文名') and paras:
                    title_name=re.match(r'\d+[a-z]?[.、]\s*([^（(\s]+)',paras[0])
                    if title_name: add('规范中文名',title_name.group(1),'中国植物志（植物智数字版）',plant_url,'条目标题中的中文名称；采用植物志版本')
                begin=next((i for i,t in enumerate(paras) if re.match(r'(?:多年生|一年生|二年生|常绿|落叶|草本|灌木|乔木|藤本|攀援|大型植物|小型植物|植株|本种与|本变种与|与[^，]{1,30}的区别)',t)),None)
                if begin is not None:
                    for t in paras[begin:]:
                        if re.match(r'\d+[a-z]?\.|(?:var\.|subsp\.)\s+[a-z]|^[A-Z][a-z]+\s+[a-z]+',t): break
                        flora_paragraphs.append(t)
        morphology=mpd.get('植物形态','') or (flora_paragraphs[0] if flora_paragraphs else row.get('植物志原文',''))
        if morphology and (mpd or flora_paragraphs):
            add('形态描述',morphology,'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'完整形态段落，未混入命名文献引用')
        if not row.get('生长形态'):
            m=re.search(r'(?:^|。)\s*((?:一年生|一年|二年生|二年|多年生|多年|常绿|落叶)?(?:草本|乔木|灌木|藤本|攀援灌木|木质藤本|草质藤本)[^。；，]{0,20})',morphology)
            if m: add('生长形态',m.group(1),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'形态原文明确的生活型句')
        sentences=[s.strip() for s in re.split(r'(?<=[。；])',morphology) if s.strip()]
        patterns={'叶特征':r'^(?:叶|叶片|小叶|羽片|基生叶|茎生叶|单叶|复叶|托叶)','花特征':r'^(?:花|雄蕊|雌蕊|雄花|雌花|萼|总状花序|聚伞花序|圆锥花序|穗状花序|肉穗花序)','果实特征':r'^(?:果实|果为|果呈|蒴果|瘦果|浆果|核果|荚果|蓇葖|颖果|翅果|坚果)','根特征':r'^(?:根|块根|主根|根茎|地下根茎|球茎|鳞茎|假鳞茎)','茎特征':r'^(?:茎|地上茎|地下茎)'}
        for field,pattern in patterns.items():
            if not row.get(field):
                selected=[s for s in sentences if re.search(pattern,s)]
                if selected: add(field,' '.join(selected),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'形态原文明确器官句；未从照片推断')
        if row.get('产地描述'):
            distribution='产地记载：'+row['产地描述']
            if row.get('分布地区'): distribution+=' 分布记载：'+row['分布地区']
            add('分布地区',distribution,'植物智',plant_url,'产地与分布合并，保留原文范围')
        if not row.get('分布地区') and mpd.get('生境分布'):
            add('分布地区',mpd['生境分布'],'香港浸会大学药用植物图像数据库',mpd_url,'【生境分布】，含植物分布与药材产区')
        if not row.get('分布地区'):
            geo=[p for p in flora_paragraphs if re.match(r'产(?:于|我国|[\u3400-\u9fff])|分布|遍布|广布|原产',p)]
            if geo: add('分布地区',' '.join(geo),'中国植物志（植物智数字版）',plant_url,'第一形态条目随后记载的分布段落，不包含后附变种')
        if not row.get('生境'):
            origin=mpd.get('生境分布','') or ' '.join(flora_paragraphs)
            selected=re.findall(r'(?:生于|生长于|生长在|常见于|生在|多生于|生海拔)[^。；]+',origin)
            if selected: add('生境','；'.join(selected),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'原文中的明确生境句')
        for field,label in [('花期','花期'),('果期','果期')]:
            if not row.get(field):
                m=re.search(label+r'([^。；，]+)',morphology)
                if m: add(field,m.group(1),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'形态原文/'+label)
            if not row.get(field):
                m=re.search(r'花果期([^。；，]+)',morphology)
                if m: add(field,m.group(1),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'原文共同记载花果期，分别记录，未拆分推断')
        spore=re.search(r'孢子期([^。；，]+)',morphology)
        if spore: add('孢子期',spore.group(1),'香港浸会大学药用植物图像数据库' if mpd else '中国植物志（植物智数字版）',mpd_url or plant_url,'原文明确孢子期，未填写为花果期')
        if mpd:
            classification=mpd.get('科属归类','')
            family=re.search(r'([\u3400-\u9fff]+科)',classification); genus=re.search(r'([\u3400-\u9fff]+属)',classification)
            if family: add('资料科名中文',family.group(1),'香港浸会大学药用植物图像数据库',mpd_url,'【科属归类】；与GBIF规范科名可能采用不同分类体系')
            if genus: add('资料属名中文',genus.group(1),'香港浸会大学药用植物图像数据库',mpd_url,'【科属归类】；未转换分类体系')
        # Preserve only explicit comparison statements, with an unresolved review state.
        comparative=[]
        for text in [row.get('识别要点',''),row.get('植物志原文','')]:
            comparative.extend(s.strip() for s in re.split(r'(?<=[。])',text) if re.search(r'本种与|本种和|本变种与|与[^。]{1,100}(?:相似|相近|区别)|区别在于|容易混淆|易混淆',s))
        if comparative:
            value=' '.join(dict.fromkeys(comparative))
            add('易混淆原文',value,'中国植物志（植物智数字版）' if row.get('植物志原文') else '植物智',plant_url,'原文比较描述，未作为正式鉴别结论','来源有比较记载，待人工核实')
            add('主要区别',value,'中国植物志（植物智数字版）',plant_url,'原文比较描述，待人工审核','来源有比较记载，待人工核实')
            names=[]
            for text in comparative:
                names.extend(re.findall(r'(?:本种与|本种和|本变种与|与)([^。；，：]{1,50}?)(?:相似|相近|的区别|不同)',text))
            if names: add('易混淆植物','；'.join(dict.fromkeys(names)),'中国植物志（植物智数字版）',plant_url,'比较句直接提及名称，未经名称消歧','待人工核实')
            row['易混淆审核状态']='植物资料有比较记载，待人工核实'
        medicines=result['medicinal_materials']
        for extra in result.get('extra_medical_sources',[]):
            if extra['url'] not in [m['来源链接'] for m in medicines]: medicines.append(material_from_fields(extra['fields'],extra['url'],row))
        # Also ensure all initial material properties use the same parser.
        medicines=[material_from_fields(hk_fields(fetch(m['来源链接']).get('body',''))[0],m['来源链接'],row) for m in medicines]
        medicines+= [processed for parent in medicines for processed in processed_materials(parent)]
        direct_medicines=[m for m in medicines if m['基原关联类型']!='昆虫分泌物，该植物是寄主']
        result['medicinal_materials']=medicines
        drug_fields={'药材名称':'药材名称','药用部位':'药用部位','加工状态':'加工状态','药性':'药性','药味':'药味','归经':'归经','传统功效':'传统功效原文','传统应用':'传统应用','毒性':'毒性记载','使用注意':'使用注意原文'}
        # Drop old aggregate provenance before rebuilding it.
        evidence[:]=[e for e in evidence if e['field'] not in drug_fields or e['source_name']!='香港浸会大学中药材图像数据库']
        for target,field in drug_fields.items():
            values=[m['药材名称']+'：'+m[field] for m in direct_medicines if m.get(field)]
            if values:
                row[target]='；'.join(m['药材名称'] for m in direct_medicines if m.get(field)) if target=='药材名称' else '；'.join(values)
                for m in direct_medicines:
                    if m.get(field): evidence.append({'No':row['No'],'field':target,'value':m['药材名称']+'：'+m[field],'source_name':'香港浸会大学中药材图像数据库','url':m['来源链接'],'version':'网页，未声明版本','locator':'药材 '+m['药材名称']+' 对应 '+field,'status':'来源基原已匹配，待2025药典与人工复核','retrieved_date':DATE})
        if medicines: row['药材审核状态']='有来源基原匹配，待药典及人工核验'
        if not row.get('药用部位') and mpd.get('药用部位'):
            add('药用部位',mpd['药用部位'],'香港浸会大学药用植物图像数据库',mpd_url,'【药用部位】；未建立正式药材标准映射','植物资料记载，待药材标准核实')
        if not row.get('加工状态') and mpd.get('采收加工'):
            add('加工状态',mpd['采收加工'],'香港浸会大学药用植物图像数据库',mpd_url,'【采收加工】原文；保留各部位差异','植物资料记载，待药材标准核实')
        if not row.get('药材名称') and mpd.get('药用部位'):
            match_name=re.search(r'中药名[:：]\s*([^。]+)',mpd['药用部位'])
            if match_name: add('药材名称',match_name.group(1),'香港浸会大学药用植物图像数据库',mpd_url,'【药用部位】中明确写出的中药名','植物资料记载，待药材标准核实')
        functional=mpd.get('性味功能','')
        if functional:
            property_text=re.split(r'。',functional)[0]
            for target,regex in [('药性',r'微寒|微温|大热|大寒|寒|热|温|凉|平'),('药味',r'微苦|微甘|微辛|苦|甘|辛|酸|咸|涩|淡')]:
                if not row.get(target):
                    prefix='性' if target=='药性' else '味'
                    tokens=re.findall(r'(?:'+prefix+r'|[,，、]|^)\s*('+regex+r')(?=$|[,，。；;、])',property_text)
                    values='；'.join(dict.fromkeys(tokens))
                    if values: add(target,'植物资料所述药用部位：'+values,'香港浸会大学药用植物图像数据库',mpd_url,'【性味功能】首句，未与药典核对','植物资料记载，待药典核实')
            mer=re.search(r'归([^。；]+?经)',functional)
            if mer and not row.get('归经'): add('归经','植物资料所述药用部位：'+mer.group(1),'香港浸会大学药用植物图像数据库',mpd_url,'【性味功能】明确归经文字','植物资料记载，待药典核实')
            if not row.get('传统功效'):
                split=functional.split('。',1)
                if len(split)>1 and split[1]: add('传统功效',split[1],'香港浸会大学药用植物图像数据库',mpd_url,'【性味功能】性味后明确记載的功能','植物资料记载，待药典核实')
        if mpd.get('主治用法') and not row.get('传统应用'):
            application=re.split(r'内服[:：]|外用[:：]|用量[:：]',mpd['主治用法'])[0].strip()
            if application: add('传统应用',application,'香港浸会大学药用植物图像数据库',mpd_url,'【主治用法】适应用途原文；不录入用量建议','植物资料记载，待药典核实')
        if row.get('毒性'): row['毒性审核状态']='来源有明确记载，待药典和人工核验'
        # Keep modern toxicology evidence separate from historical taste/nature.
        toxicity_path=CACHE/'toxicity_literature.json'
        if toxicity_path.exists():
            papers=json.loads(toxicity_path.read_text(encoding='utf-8'))
            checked={55:('41819152','文献记载含阿托品、莨菪碱及东莨菪碱等莨菪烷生物碱；误食可引起抗胆碱能中毒。'),119:('40137888','文献记载含强心苷；误食可引起严重心律失常，存在致死中毒风险。'),133:('41314269','文献综述将Gynura japonica列为已报道中药相关肝损伤的植物之一。'),145:('38663784','毒理综述记载甾体生物碱相关毒性，并报告神经毒性和胚胎毒性研究。'),163:('37116390','文献记载本植物含马兜铃酸I，并指出马兜铃酸具有肾毒性、肝毒性及致癌性。')}
            if number in checked:
                pmid,claim=checked[number]
                paper=next((p for p in papers if p['pmid']==pmid),None)
                if paper:
                    existing=row.get('毒性','')
                    add('毒性',(existing+'；' if existing else '')+'现代文献：'+claim,paper['title'],paper['url'],'PubMed PMID '+pmid+'；已核对摘要，未审阅全文','文献摘要记载，待专业复核',paper['journal']+' '+str(paper.get('year',''))+' DOI:'+paper.get('doi',''))
                    row['毒性审核状态']='已核对文献摘要，待专业复核；药典核验独立进行'
        if not row.get('毒性'):
            literal=[s.strip() for s in re.split(r'(?<=[。；])',row.get('植物志原文','')) if re.search(r'植株有毒|全株有毒|有大毒|有小毒|根[^。]{0,15}有毒|叶[^。]{0,15}有毒',s)]
            if literal:
                add('毒性',' '.join(literal),'中国植物志（植物智数字版）',plant_url,'原文明确毒性句，保留原意','植物志明确记载，待专业复核')
                row['毒性审核状态']='植物志有明确记载，待专业复核'
        if number!=51:
            snippet=''.join(row.get(k,'') for k in ['生长形态','株高特征','叶特征','花特征'])
            if not snippet and morphology: snippet=morphology[:170]
            if snippet:
                summary=row['Chinese Name']+'（'+row.get('植物智学名',canonical(row['Latin Name']))+'）。'+snippet
                if len(summary)>180: summary=summary[:179]+'…'
                # Summary is an extract, so preserve the precise contributing field sources.
                add('简短介绍',summary,'多来源形态摘录',mpd_url or plant_url,'已采集生活型/株/叶/花字段组合，参见这些字段的逐项来源','来源组合摘录，待编辑复核')
        row['药材记录JSON']=json.dumps(medicines,ensure_ascii=False) if medicines else ''
        row['检索日期']=DATE
        citation=row.get('植物志引用','')
        row['资料版本']=citation or '网页资料，来源未声明版本'
        page=re.search(r'>>(?:\s*)(\d+)页',citation); row['来源页码']=page.group(1) if page else ''
        if result.get('issues'): row['待核实说明']='；'.join(dict.fromkeys(result['issues']))
        # Preserve the exact endpoint for accepted GBIF records.
        gm=result.get('gbif_match',{})
        if gm and number!=51:
            accepted_status=gm.get('accepted_record',{}).get('taxonomicStatus',gm.get('status',''))
            match_urls=[e['url'] for e in evidence if 'GBIF' in e['source_name']]
            match_url=match_urls[0] if match_urls else 'https://api.gbif.org/v1/species/'+str(gbif_key(gm))
            add('原始学名分类状态',gm.get('status',''),'GBIF Backbone Taxonomy',match_url,'status，原始学名匹配状态')
            add('分类接受状态',accepted_status,'GBIF Backbone Taxonomy',match_url,'接受分类条目的taxonomicStatus/status')
            if accepted_status=='DOUBTFUL':
                add('候选学名',row.get('规范学名',''),'GBIF Backbone Taxonomy',match_url,'疑问名称，未采用为规范接受名','分类数据库标为DOUBTFUL，待专业核验')
                row['候选植物来源']=match_url
                row['规范学名']=''
                evidence[:]=[e for e in evidence if e['field']!='规范学名']
                row['身份核对状态']='学名匹配，分类数据库标为疑问名称，待专业核验'
                result['issues'].append('GBIF将此名称标为DOUBTFUL，暂不填入规范接受学名，须另查分类文献')
                row['待核实说明']='；'.join(dict.fromkeys(result['issues']))
        if gm.get('accepted_record'):
            for e in evidence:
                if e['source_name']=='GBIF Backbone Taxonomy' and e['field'] in ['规范学名','规范科名','属名']:
                    e['url']='https://api.gbif.org/v1/species/'+str(gbif_key(gm))
        # Stable evidence IDs allow compact field-level provenance in the plant CSV.
        seen=set(); clean=[]
        for e in evidence:
            key=(e['field'],e['value'],e['url'],e['locator'])
            if key in seen: continue
            seen.add(key)
            e['evidence_id']=f"tcmp-{number:03d}-e{len(clean)+1:03d}"
            clean.append(e)
        mapping={}
        for e in clean: mapping.setdefault(e['field'],[]).append(e['evidence_id'])
        row['字段来源JSON']=json.dumps(mapping,ensure_ascii=False,separators=(',',':'))
        row['资料来源名称']='；'.join(dict.fromkeys(e['source_name'] for e in clean))
        row['资料来源链接']='；'.join(dict.fromkeys(e['url'] for e in clean))
        for field in ['封面图','全株图','叶片图','花果图']:
            row[field]=''
        all_evidence.extend(clean); all_meds.extend(medicines); all_images.extend(result['images'])
        for issue in result.get('issues',[]): review.append({'No':row['No'],'植物ID':row['植物ID'],'中文名':row['Chinese Name'],'问题类型':'身份冲突' if number==51 else '来源匹配待核实','问题说明':issue,'处理状态':'待人工审核'})
        for field in ['规范学名','简短介绍','叶特征','花特征','果实特征','根特征','分布地区','生境','花期','果期','药材名称','药用部位','药性','药味','归经','传统功效','传统应用','毒性','使用注意']:
            if not row.get(field): review.append({'No':row['No'],'植物ID':row['植物ID'],'中文名':row['Chinese Name'],'问题类型':'字段缺失','问题说明':field+'：来源未提供、未通过核对，或器官不适用；空值不表示无毒或无药用','处理状态':'待补充或确认不适用'})
    def table(name,items,columns=None):
        columns=columns or list(dict.fromkeys(k for item in items for k in item))
        return {'filename':name,'columns':columns,'values':[[item.get(k,'') for k in columns] for item in items]}
    rows=[r['row'] for r in records]
    coverage={k:sum(bool(r.get(k)) for r in rows) for k in MAIN_COLUMNS[4:]}
    original_path=DATA/'tcmp-info-20250329.original.csv'
    if not original_path.exists(): original_path=DATA/'tcmp-info-20250329.csv'
    plan={'date':DATE,'main_original_path':str(DATA/'tcmp-info-20250329.csv'),'original_sha256':hashlib.sha256(original_path.read_bytes()).hexdigest(),'current_sha256':hashlib.sha256((DATA/'tcmp-info-20250329.csv').read_bytes()).hexdigest(),'tables':[table('tcmp-info-20250329.csv',rows,MAIN_COLUMNS),table('tcmp-medicinal-materials.csv',all_meds),table('tcmp-image-candidates.csv',all_images),table('tcmp-field-sources.csv',all_evidence),table('tcmp-review-queue.csv',review)],'coverage':coverage,'medicinal_records':len(all_meds),'evidence_records':len(all_evidence),'image_candidates':len(all_images),'review_records':len(review),'identity_states':{status:sum(r['身份核对状态']==status for r in rows) for status in set(r['身份核对状态'] for r in rows)}}
    (CACHE/'export_plan.json').write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in plan.items() if k!='tables'},ensure_ascii=False,indent=2),flush=True)

def resolve_exceptions():
    # The original label remains intact. Expand only when an actual flora entry
    # confirms both the abbreviated genus and the Chinese plant name.
    frps_url='https://www.iplant.cn/ashx/getfrps.ashx?'+urllib.parse.urlencode({'key':'Polygonum bistorta'})
    frps=json_fetch(frps_url)
    text=compact(text_of(frps.get('frpsdesc','')))
    if 'Polygonum bistorta' in text and '拳参' in text:
        rowfile=CACHE/'row_199.json'; old=json.loads(rowfile.read_text(encoding='utf-8'))
        original={k:old['row'][k] for k in ['No','Latin Name','Family','Chinese Name']}
        expanded=dict(original,**{'Latin Name':'Polygonum bistorta L.'})
        new=collect_one(expanded)
        for key,value in original.items(): new['row'][key]=value
        new['row']['原始学名']=original['Latin Name']
        new['row']['身份核对状态']='植物志核对缩写学名展开，待人工复核'
        new['row']['学名展开依据']='中国植物志拳参条目记载Polygonum bistorta L.；原始P.bistorta L.保持不变'
        new['issues'].append('原始学名为P.bistorta L.，按植物志拳参条目展开为Polygonum bistorta L.；规范分类采用GBIF接受名，待人工复核')
        new['evidence'].append({'No':'199','field':'规范学名','value':new['row'].get('规范学名',''),'source_name':'中国植物志（植物智数字版）','url':'https://www.iplant.cn/info/'+urllib.parse.quote('拳参')+'?t=z','version':compact(text_of(frps.get('frpslink',''))),'locator':'拳参条目中的Polygonum bistorta L.，用于展开原始缩写','status':'依据来源展开缩写，待人工复核','retrieved_date':DATE})
        rowfile.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
        print('199 abbreviated name expanded from retrieved flora record',flush=True)
    else: print('199 remains unresolved: flora expansion evidence absent',flush=True)
    rowfile=CACHE/'row_015.json'; result=json.loads(rowfile.read_text(encoding='utf-8'))
    # iPlant explicitly links the spelling scabiosifolia in this taxon's aliases.
    if 'Patrinia scabiosifolia' in result['row'].get('植物别名',''):
        match,url=gbif_match('Patrinia scabiosifolia')
        if match:
            accepted=match.get('accepted_record',match)
            for field,key in [('规范学名','scientificName'),('规范科名','family'),('属名','genus')]:
                result['row'][field]=accepted.get(key,'')
                result['evidence'].append({'No':'15','field':field,'value':accepted.get(key,''),'source_name':'GBIF Backbone Taxonomy + 植物智异名关联','url':url,'version':'GBIF v1，查询日期 '+DATE,'locator':'植物智原条目异名Patrinia scabiosifolia与GBIF匹配','status':'来源异名关联，待人工复核','retrieved_date':DATE})
            result['row'].update({'分类数据库ID':str(gbif_key(match)),'分类体系':'GBIF Backbone Taxonomy','学名匹配类型':match.get('matchType',''),'学名匹配置信度':str(match.get('confidence','')),'身份核对状态':'植物智异名关联与GBIF一致，待人工复核'})
            result['gbif_match']=match
            result['issues']=[i for i in result['issues'] if not i.startswith('原始学名未获得可靠')]
            result['issues'].append('原始scabiosaefolia拼写按植物智明确异名关联到GBIF scabiosifolia；保留原始学名')
            rowfile.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print('15 spelling mapped using an explicit source synonym',flush=True)

def research_toxicity():
    queries={55:'"Atropa belladonna" poisoning',119:'"Nerium oleander" poisoning review',133:'("Gynura japonica" OR "Gynura segetum") hepatotoxicity',145:'"Veratrum nigrum" toxicity',163:'"Aristolochia debilis" nephrotoxicity'}
    records=[]
    for number,query in queries.items():
        url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'+urllib.parse.urlencode({'db':'pubmed','retmode':'json','retmax':'3','term':query})
        data=json_fetch(url); ids=data.get('esearchresult',{}).get('idlist',[])
        if not ids:
            print('Toxicity query unavailable',number,flush=True); continue
        time.sleep(.4)
        xml_url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?'+urllib.parse.urlencode({'db':'pubmed','retmode':'xml','id':','.join(ids)})
        rec=fetch(xml_url)
        try: doc=ET.fromstring(rec.get('body','').encode('utf-8'))
        except Exception: continue
        for article in doc.xpath('//PubmedArticle'):
            pmid=article.findtext('.//PMID'); title=compact(''.join(article.find('.//ArticleTitle').itertext()))
            abstract=' '.join(compact(''.join(a.itertext())) for a in article.findall('.//AbstractText'))
            doi=next((a.text for a in article.findall('.//ArticleId') if a.get('IdType')=='doi'),'')
            item={'No':str(number),'query':query,'pmid':pmid,'title':title,'abstract':abstract,'doi':doi,'journal':article.findtext('.//Journal/Title'),'year':article.findtext('.//PubDate/Year'),'url':'https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/','retrieved_date':DATE}
            records.append(item)
            print(json.dumps(item,ensure_ascii=False),flush=True)
    (CACHE/'toxicity_literature.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

def probe_specimens():
    sample=json.loads((CACHE/'row_004.json').read_text(encoding='utf-8'))
    for med in sample['medicinal_materials']:
        rec=fetch(med['来源链接']); doc=LH.fromstring(rec.get('body',''))
        links=[urllib.parse.urljoin(med['来源链接'],a.get('href','')) for a in doc.xpath('//a[@href]') if '/cmsd/detail.php' in a.get('href','')]
        for url in links:
            rec=fetch(url)
            print('SPECIMEN URL',url,'STATUS',rec.get('status'),flush=True)
            print(text_of(rec.get('body',''))[:18000],flush=True)
            (CACHE/'specimen_probe.html').write_text(rec.get('body',''),encoding='utf-8')

def probe_materia():
    urls=['https://www.zysj.com.cn/zhongyaocai/index.html','https://www.zysj.com.cn/zhongyaocai/danshen/index.html']
    for url in urls:
        rec=fetch(url); body=rec.get('body','')
        print('MATERIA',url,rec.get('status'),rec.get('error',''),flush=True)
        if body:
            doc=LH.fromstring(body)
            print(text_of(body)[:14000],flush=True)
            print('DANSHEN LINKS',[(a.text_content(),a.get('href')) for a in doc.xpath('//a[@href]') if a.text_content().strip()=='丹参'],flush=True)
            (CACHE/('materia_index_probe.html' if 'danshen' not in url else 'materia_danshen_probe.html')).write_text(body,encoding='utf-8')

if __name__ == '__main__':
    if '--collect' in sys.argv:
        collect(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 300)
    elif '--enrich-more' in sys.argv: enrich_more()
    elif '--prepare-export' in sys.argv: prepare_export()
    elif '--resolve-exceptions' in sys.argv: resolve_exceptions()
    elif '--research-toxicity' in sys.argv: research_toxicity()
    elif '--probe-specimens' in sys.argv: probe_specimens()
    elif '--probe-materia' in sys.argv: probe_materia()
    elif '--probe2' in sys.argv: probe2()
    else: probe()

