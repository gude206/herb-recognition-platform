"""Validate preserved class mappings and source links; write a delivery report."""
from pathlib import Path
import csv, hashlib, json, re, sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'author_tcmp_300'
sys.stdout.reconfigure(encoding='utf-8',errors='replace')

def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); columns=reader.fieldnames; rows=list(reader)
    assert len(columns)==len(set(columns)), name+' duplicate headers'
    assert all(None not in row for row in rows), name+' malformed row'
    return columns,rows

def run():
    columns,plants=read('tcmp-info-20250329.csv')
    old_columns,original=read('tcmp-info-20250329.original.csv')
    assert old_columns==['No','Latin Name','Family','Chinese Name']
    assert len(plants)==len(original)==300
    assert [{k:r[k] for k in old_columns} for r in plants]==original
    assert {int(r['No']) for r in plants}==set(range(1,301))
    assert len({r['植物ID'] for r in plants})==300
    by_number={r['No']:r for r in plants}
    _,meds=read('tcmp-medicinal-materials.csv')
    _,images=read('tcmp-image-candidates.csv')
    _,sources=read('tcmp-field-sources.csv')
    _,review=read('tcmp-review-queue.csv')
    assert len({e['evidence_id'] for e in sources})==len(sources)
    source_ids={e['evidence_id']:e for e in sources}
    source_fields=['规范中文名','规范学名','植物别名','学名异名','规范科名','属名','简短介绍','生长形态','叶特征','花特征','果实特征','茎特征','根特征','形态描述','分布地区','生境','花期','果期','主要区别','易混淆原文','药用部位','药性','药味','归经','传统功效','传统应用','毒性','使用注意']
    for row in plants:
        mapping=json.loads(row['字段来源JSON'])
        for field,ids in mapping.items():
            assert all(i in source_ids and source_ids[i]['No']==row['No'] and source_ids[i]['field']==field for i in ids)
        for field in source_fields:
            if row[field]: assert mapping.get(field), (row['No'],field,'missing field citation')
        if row['药材记录JSON']: json.loads(row['药材记录JSON'])
        json.loads(row['图片候选JSON'])
        assert len(row['简短介绍'])<=180
        assert row['人工审核状态']=='未人工审核'
        if row['分类接受状态']=='DOUBTFUL': assert not row['规范学名'] and row['候选学名']
        assert all(row[f]=='' for f in ['封面图','全株图','叶片图','花果图'])
        assert (ROOT/row['封面图候选']).is_file()
    assert not by_number['51']['规范学名'] and not by_number['51']['药用部位']
    for number,name in [('143','Viola japonica'),('185','Viola diffusa')]:
        assert by_number[number]['规范学名'].startswith(name)
        assert 'GBIF原匹配仍为DOUBTFUL' in by_number[number]['分类接受状态']
        assert 'Flora of China' in by_number[number]['分类体系']
        assert 'getfoc.ashx' in by_number[number]['资料来源链接']
    assert 'Polygonum' in by_number['199']['植物智学名'] and by_number['199']['Latin Name']=='P.bistorta L.'
    # Match against every training class using the same normalization as the API.
    norm=lambda s: re.sub(r'[^a-z0-9]','',s.lower())
    folders=[p for p in (DATA/'images'/'tcmp-300'/'train').iterdir() if p.is_dir()]
    assert len(folders)==300
    for folder in folders:
        n,_,latin=folder.name.partition('.')
        assert norm(latin)==norm(by_number[str(int(n))]['Latin Name'])
    for med in meds:
        assert med['No'] in by_number and med['植物ID']==by_number[med['No']]['植物ID']
        assert med['来源链接'].startswith('https://sys01.lib.hkbu.edu.hk/cmed/mmid/detail.php?')
        assert '未与2025' in med['药典核对状态']
        if med['基原关联类型']=='昆虫分泌物，该植物是寄主':
            assert med['药材名称']=='虫白蜡' and '非植物部位' in med['药用部位']
            assert '虫白蜡' not in by_number[med['No']]['药材名称']
    for image in images:
        assert image['No'] in by_number and image['审核状态']=='待人工审核，未发布'
        if not image['图片URL或路径'].startswith('https://'): assert (ROOT/image['图片URL或路径']).is_file()
    for evidence in sources:
        assert evidence['url'].startswith('https://') and evidence['value'] and evidence['locator']
    if '活体植物完整介绍' in columns:
        for row in plants:
            number=row['No']
            assert row['识别对象']=='活体植物' and row['活体植物完整介绍']
            assert json.loads(row['药材记录JSON'])==[m for m in meds if m['No']==number]
            assert json.loads(row['图片候选JSON'])==[i for i in images if i['No']==number]
            assert json.loads(row['字段证据JSON'])==[s for s in sources if s['No']==number]
            assert json.loads(row['待核实事项JSON'])==[r for r in review if r['No']==number]
            assert '药材主产' not in row['活体植物分布地区']
            assert all(part not in row['生境'] for part in ['花序的下部','叶腋内','侧枝顶端','茎、枝顶端'])
        assert sum(bool(r['活体植物分布地区']) for r in plants)==299
        assert not by_number['51']['活体植物分布地区']
        assert by_number['143']['活体植物分布地区']
        for row in plants:
            if row['药材完整介绍']:
                assert row['药材完整介绍'] in row['活体植物完整介绍']
            assert row['资料来源链接'] in row['活体植物完整介绍']
            json.loads(row['字段核对状态JSON'])
            json.loads(row['候选植物资料JSON'])
        assert not by_number['188']['毒性']
        assert not by_number['204']['归经']
        assert '及10月' in by_number['143']['花期']
        for number in ['68','83','87','99','134','175','220','244','246','272','297']:
            assert all(by_number[number][field].startswith('不适用：') for field in ['花特征','果实特征','花期','果期'])
    coverage={k:sum(bool(r[k]) and not r[k].startswith('不适用：') for r in plants) for k in columns[4:]}
    result={'status':'PASS','date':'2026-09-30','plants':300,'columns':len(columns),'original_fields_preserved':True,'training_folder_mappings_checked':300,'field_provenance_checked':True,'medicinal_records':len(meds),'image_candidates':len(images),'evidence_records':len(sources),'review_records':len(review),'original_sha256':hashlib.sha256((DATA/'tcmp-info-20250329.original.csv').read_bytes()).hexdigest(),'coverage':coverage,'identity_states':dict(Counter(r['身份核对状态'] for r in plants))}
    (DATA/'enrichment_sources_20260930'/'validation_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# TCMP-300 植物资料补充说明','', f'更新日期：2026-09-30。原 CSV 已扩展为 300 行、{len(columns)} 列；原有编号、学名、科名、中文名逐项保持一致。','',
      '本次交付是有来源、可追溯的资料补充版。自动提取和文献摘要核对不等于植物专家或药学人员审核。所有记录的人工审核状态均为“未人工审核”。','',
      '## 文件','',
      '- [植物主表](tcmp-info-20250329.csv)：活体植物的完整介绍、分布、生境、形态及本草知识；药材明细、图片候选、字段证据和待核实事项已全部内嵌，读取一个CSV即可取得所有现有资料。',
      '- [原始文件备份](tcmp-info-20250329.original.csv)：原文件字节备份。',
      '- [药材关联表](tcmp-medicinal-materials.csv)：219 条关联记录，区分植物直接基原、昆虫寄主、虫瘿和炮制品。',
      '- [图片候选表](tcmp-image-candidates.csv)：509 条候选，尚未确认器官和转载授权。',
      f'- [字段来源表](tcmp-field-sources.csv)：{len(sources)} 条证据记录，主表已完整内嵌，独立表用于维护与审核。',
      f'- [待核实清单](tcmp-review-queue.csv)：{len(review)} 条问题或缺失字段记录，主表已完整内嵌；缺失可能是来源未提供或器官不适用。','',
      '## 资料覆盖','', '| 字段 | 已填植物数 / 300 |','|---|---:|']
    for field in ['规范中文名','规范学名','植物别名','简短介绍','生长形态','形态描述','叶特征','花特征','果实特征','茎特征','根特征','分布地区','生境','花期','果期','主要区别','药材名称','药用部位','药性','药味','归经','传统功效','传统应用','毒性','使用注意']:
        lines.append(f'| {field} | {coverage[field]} |')
    lines+=['', '## 来源与解释','',
      '1. 植物智及其《中国植物志》数字版提供中文名、别名、器官特征、分布、生境、物候和明确的比较描述。保存了植物志原文、版本及页码。',
      '2. GBIF Backbone Taxonomy 提供学名匹配和接受分类。科属变更保存在新字段；原科名不改。GBIF疑问状态与植物志采用名分别标明，不把植物志收录解读成GBIF现行接受名已确认。',
      '3. 香港浸会大学药用植物及中药材图像数据库提供药用部位、采收加工、性味功能、传统应用及药材基原。仅当具体药材的来源定义或分类异名关联与植物一致时才建立药材关联。',
      '4. PubMed 已读取颠茄、夹竹桃、菊三七、藜芦、马兜铃相关文献摘要，补充现代毒性信息；来源表记录文献题名、PMID、DOI和年份。未把动物/毒理研究写成人体剂量结论。',
      '5. 数据库网页未声明的版本记录为未声明；药材内容未与2025年版《中国药典》逐条核验。不能把“有来源”解读成“药典已确认”。','',
      '## 需要重点核实','',
      '- 第51类“地肤”：原始学名为 Geranium wilfordii，与中文名和科名冲突。保留原始训练标签，候选学名为 Bassia scoparia；规范植物和药材信息暂不采用。',
      '- 第143类“犁头草”、第185类“七星莲”：已依据Flora of China (2007)补充所采用体系的学名，保留GBIF原匹配DOUBTFUL状态及数据库差异说明；不代表完成现行分类专家审定。',
      '- 第199类“拳参”：根据植物志明确记载，将缩写 P.bistorta L. 关联到 Polygonum bistorta L.，再取得接受分类；原始缩写保留。',
      '- 第15类“黄花败酱”：按植物智明确异名关系将 scabiosaefolia 关联到 GBIF scabiosifolia；原拼写保留。',
      '- 多个中文名检索返回其他植物候选，已将这些提示记为名称歧义，未当作别名或形态易混淆结论。',
      '- 当前归经覆盖3类植物：白英有明确植物数据库记载；半夏和何首乌为来源明确炮制品的记载。没有明确归经来源的条目留空；不由疾病所在经络反推。',
      '- 正式封面、全株、叶片、花果图片字段仍为空。保留300张本地类别封面候选及大学资料图片链接，均待器官审核与授权确认；不把图像分类标签当器官标签。',
      '- 毒性空值表示尚未取得可采用的证据，不能解读为无毒。传统功效和应用是来源记载，不代表现代临床疗效已证实。','',
      '## 字段使用','',
      '- `No` 与 `植物ID` 是稳定关联键。不要按中文名或学名直接合并类别，也不要用规范学名改训练目录。',
      '- `字段来源JSON` 是“字段名 → evidence_id列表”的映射；用 evidence_id 查字段来源表。它不存整段引用，便于查证。',
      '- `药材记录JSON` 保留一株植物对应多个药材和炮制品的完整关联。主表性味等字段使用“药材名称：内容”保留适用对象；筛选最好读取药材关联表的独立属性列。',
      '- `资料科名中文` 和 `资料属名中文` 来自大学资料原分类，不应与GBIF规范分类混为同一体系。',
      '- `物候原文`、`花期`、`果期`、`孢子期` 保留原资料范围。源文共同写“花果期”的条目不人为拆成不同月份；蕨类孢子期不写成花期。',
      '- `主要区别` 为来源直接比较摘录，仍需人工核实对象和适用范围。个别植物志页包含附属亚种/变种，完整原文用于复查；主表不是正式鉴定检索表。',
      '- `封面图候选` 为相对项目根目录的本地路径；图片候选表同时保存外部页面和授权状态。','',
      '## 活体识别与单文件使用','',
      '- 每行对应一个活体植物类别，300行保持训练类别匹配；药材、植物器官及炮制品不作为额外活体类别。',
      '- `活体植物完整介绍` 为可直接展示的植物详情；`药材完整介绍` 保留植物资料及对应药材的所有已有记载。',
      '- `活体植物分布地区` 是植物来源记载的分布范围；`药材产区` 单列药材生产区域；地理信息不用于排除图像预测类别。',
      '- 当前299条植物有分布资料；第51类地肤仍存在训练标签身份冲突，候选地肤植物志资料保存在候选植物资料JSON，未当作训练类确认身份。',
      '- 已从保存的植物志原文补充临时救、透茎冷水花的分布；修正5条生境误提取，其中慈姑缺少可靠生境资料而留空。',
      '- `药材记录JSON`、`图片候选JSON`、`字段证据JSON`、`待核实事项JSON` 内嵌对应独立表的完整记录；不依赖其他CSV即可查证。',
      '- 同步后的MySQL `plants` 表拥有主CSV全部103个字段，详情可以只查这一张表；辅助表继续保留用于维护。',
      '- 整合前的五个CSV及数据库SQL备份保存在 `before_live_plant_consolidation_20260930/`。','',
      '## 验证结果','',
      '已重新读取所有CSV，检查300个唯一类别、原四列逐项一致、300个训练目录名称匹配、JSON可解析、逐字段证据ID有效、药材关联、来源链接、本地图片路径、未审核状态、身份冲突和疑问学名处理。','',
      '验证通过表示文件结构和上述一致性检查通过；不表示全部植物学和药学事实已通过专家审核。','',
      '原始文件 SHA-256：`'+result['original_sha256']+'`。','',
      '本次采集的公开资料快照保存在 `enrichment_sources_20260930/`；采集逻辑在项目 `tools/enrich_tcmp_metadata.py`，验证逻辑在 `tools/validate_tcmp_enrichment.py`。不需要安装依赖才能使用CSV。','']
    (DATA/'ENRICHMENT_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['coverage','identity_states']},ensure_ascii=False,indent=2))

if __name__=='__main__': run()
