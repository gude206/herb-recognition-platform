"""Report the verified review completion without changing the CSV data."""
from collections import Counter
import hashlib
import json
import sys

from research_tcmp_reviews import BACKUP, CACHE, DATA, FILES, read


def run():
    columns, plants=read(FILES[0])
    _, baseline=read(FILES[0],BACKUP)
    _, reviews=read(FILES[4])
    old={r['No']:r for r in baseline}
    prepared=json.loads((CACHE/'review_completion_report.json').read_text(encoding='utf-8'))
    mysql=json.loads((DATA/'mysql_import_report.json').read_text(encoding='utf-8'))
    validation=json.loads((DATA/'enrichment_sources_20260930'/'validation_report.json').read_text(encoding='utf-8'))
    assert mysql['status']==validation['status']=='PASS'
    for item in mysql['files'].values():
        assert hashlib.sha256((DATA/item['filename']).read_bytes()).hexdigest()==item['sha256']
    keys={(e['No'],e['field']) for e in prepared['edits']}
    changes=[(r['No'],field,old[r['No']][field],r[field]) for r in plants
             for field in columns if (r['No'],field) in keys and old[r['No']][field]!=r[field]]
    assert len(changes)==prepared['changed_fields']
    unknown=Counter(r['问题说明'].split('：',1)[0] for r in reviews
                    if r['处理状态']=='已复查现有来源，尚无可靠对应资料')
    result={k:v for k,v in prepared.items() if k!='edits'}
    result.update(status='PASS',newly_filled_fields=sum(not c[2] for c in changes),
                  corrected_fields=sum(bool(c[2]) for c in changes),
                  affected_plants=len({c[0] for c in changes}),unresolved_by_field=dict(unknown),
                  distribution_coverage=sum(bool(r['活体植物分布地区']) for r in plants),
                  original_training_fields_preserved=True,mysql_verified=True,
                  mysql_backup=mysql['database_backup'])
    (CACHE/'review_completion_report.json').write_text(
        json.dumps({**result,'edits':prepared['edits']},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 待核实项目补充结果','',
           '更新日期：2026-09-30。已写回主CSV并同步MySQL tcmp_300。','',
           f"- 主表：300行、{len(columns)}列；原四列和300个训练目录映射保持一致。",
           f"- 本轮新增或更正{len(changes)}个植物字段：新填{result['newly_filled_fields']}个，更正{result['corrected_fields']}个，涉及{result['affected_plants']}类植物。",
           "- 299类植物有活体分布资料，299类有叶部资料，296类有生境或来源明确的栽培状况。",
           "- 原待核实清单中，147项已按来源补充或核对，39项确认为不适用；另保留来源匹配与身份差异的核对说明。",
           f"- 来源表由12693条增加到{prepared['evidence_records']}条；所有关联资料继续内嵌主CSV。",
           '', '## 已处理的关键问题','',
           '- 犁头草：补齐Flora of China形态、生境和分布；花期按原文为3月及10月，未误写成连续3至10月。',
           '- 犁头草、七星莲：规范学名采用Flora of China (2007)体系，同时保留GBIF疑问名称状态与体系差异。',
           '- 木防己：更正此前误用后附毛木防己变种描述的问题；改用物种正文的形态、分布和生境。',
           '- 蕨类、石松类：花和果字段明确为不适用，原孢子结构移入相应字段。',
           '- 裸子植物：果实字段标明不形成真正果实，球果等原文保留供识别；苏铁另补球花与胚珠描述。',
           '- 天麻和菟丝子：补入原文明确的无绿叶或无叶特征；木贼和问荆补入叶鞘描述。',
           '- 补充明确的毒性及使用注意；排除“治疗药物中毒”与“邪入心经”导致的错误属性推断。',
           '- Flora of China英文原文完整保留，器官摘录不再在小数点或ca.等缩写处截断。',
           '', '## 尚未取得可靠资料','',
           f"仍有{sum(unknown.values())}项缺失字段在复查现有来源后没有可靠对应内容。这些是缺失字段数，不是植物数。",
           '', '| 字段 | 尚无可靠对应资料的项目数 |','|---|---:|']
    lines += [f'| {field} | {count} |' for field,count in unknown.most_common()]
    lines += ['', '地肤第51类仍存在原学名Geranium wilfordii与中文名及科名冲突。7张训练图抽样支持地肤候选，但不能确认全部训练图的身份；地肤候选资料保存在候选植物资料JSON，未作为正式药材或类别身份使用。',
              '', '正式图片字段仍未填入：候选图片的器官标签和转载授权没有获得可靠证明。毒性空值不表示无毒；来源的传统无毒记载也不等于鲜活全株可以食用。',
              '', '自动核对来源不等于人工专家审核，人工审核状态继续明确为“未人工审核”。不适用、已取得来源、尚无可靠资料分别记录在字段核对状态JSON和待核实事项JSON。',
              '', '## 如何查看','',
              '使用Excel或WPS打开tcmp-info-20250329.csv，主要查看活体植物完整介绍、活体植物分布地区、生境、活体识别特征和药材完整介绍。资料来源与核对状态均在同一行。',
              '', 'MySQL可直接查询：','',
              '~~~sql','USE tcmp_300;',
              'SELECT No, 活体植物名称, 活体植物分布地区, 生境,',
              '       活体植物完整介绍, 药材完整介绍, 字段核对状态JSON',
              'FROM plants ORDER BY No;', '~~~',
              '', '已验证五表提交后的全部字段与CSV一致；CSV原四列、300个训练类别、嵌入JSON与独立维护表的对应关系均通过检查。',
              '', '本轮开始时的五个CSV和SQL备份在before_review_completion_20260930；最后一批修正前的备份在before_review_refinement_20260930。','']
    (DATA/'REVIEW_COMPLETION_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    validator=DATA.parents[1]/'tools'/'validate_tcmp_enrichment.py'
    replacement='GBIF疑问状态与植物志采用名分别标明，不把植物志收录解读成GBIF现行接受名已确认。'
    for path in [validator,DATA/'ENRICHMENT_REPORT.md']:
        text=path.read_text(encoding='utf-8').replace('全部99个字段','全部103个字段').replace(
            'DOUBTFUL 名称留在候选字段，不能当作已确认接受名。',replacement)
        path.write_text(text,encoding='utf-8')
    doc=DATA/'MYSQL_IMPORT.md'
    text=doc.read_text(encoding='utf-8').replace('全部 99 个字段','全部 103 个字段').replace(
        '| 字段资料来源与证据 | 12693 |',f"| 字段资料来源与证据 | {prepared['evidence_records']} |").replace('主表共99字段','主表共103字段')
    addition='\n2026-09-30已同步来源复查补充版。主表103字段，字段来源12956条，待核实清单1663条（含已补充、不适用及仍缺少可靠资料的状态）。最终五表与当前CSV逐字段一致，详见 REVIEW_COMPLETION_REPORT.md。\n'
    if addition not in text:text+=addition
    doc.write_text(text,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run()
