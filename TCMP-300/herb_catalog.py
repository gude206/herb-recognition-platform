"""Read-only atlas built from the source-backed, single-file plant catalogue."""
import csv
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CSV_PATH=ROOT/"data/author_tcmp_300/tcmp-info-20250329.csv"
TRAIN_IMAGES=ROOT/"data/author_tcmp_300/images/tcmp-300/train"
REGIONS=["北京","天津","河北","山西","内蒙古","辽宁","吉林","黑龙江","上海","江苏","浙江","安徽",
         "福建","江西","山东","河南","湖北","湖南","广东","广西","海南","重庆","四川","贵州","云南",
         "西藏","陕西","甘肃","青海","宁夏","新疆","台湾","香港","澳门","华东","华中","华北","华南","东北","西北","西南"]
EFFECTS=["清热解毒","清热","解毒","活血","止血","止痛","祛风","利湿","消肿","化痰","止咳","平喘","补气","补血","安神","利水"]
PARTS=["根茎","块茎","块根","鳞茎","根皮","茎皮","树皮","枝皮","干皮","花蕾","花序","果皮","果实","种子",
       "地上部分","全草","全株","藤茎","木材","虫瘿","孢子","根","茎","叶","花","枝"]


def split_values(text):
    return list(dict.fromkeys(v.strip() for v in re.split(r"[；;、，,\s]+",text) if v.strip()))


def attributes(row, materials, field):
    values=[]
    for material in materials:
        if material.get("基原关联类型") not in {"昆虫分泌物，该植物是寄主","虫瘿，非植物直接药材基原"}:
            values+=split_values(material.get(field,""))
    for segment in row.get(field,"").split("；"):
        values+=split_values(segment.rsplit("：",1)[-1])
    return list(dict.fromkeys(values))


def medicinal_parts(row,materials):
    """Extract organ labels, excluding medicine names/aliases from source prose."""
    texts=[m.get("药用部位","") for m in materials if m.get("基原关联类型") not in
           {"昆虫分泌物，该植物是寄主","虫瘿，非植物直接药材基原"}]
    for segment in row.get("药用部位","").split("；"):
        # Botanical prose continues with medicine names after '入药', not organ data.
        if "入药" in segment:segment=segment.split("入药",1)[0]
        elif "：" in segment:segment=segment.rsplit("：",1)[-1]
        else:segment=segment.split("中药名",1)[0]
        texts.append(segment)
    found=set()
    for source in texts:
        for part in PARTS:
            if part in source:
                found.add(part)
                source=source.replace(part," ")
    return [part for part in PARTS if part in found]


def region_matches(text,region):
    # Ignore explicit exclusions ('除…外', '(…除外)') when matching source prose.
    positive=re.sub(r"[（(][^（）()]*除外[^（）()]*[）)]","",text)
    positive=re.sub(r"除[^；。]*?外","",positive)
    return region in positive


@lru_cache(maxsize=1)
def _load(signature):
    with CSV_PATH.open(encoding="utf-8-sig",newline="") as handle:
        rows=list(csv.DictReader(handle))
    if len(rows)!=300 or len({row["植物ID"] for row in rows})!=300:
        raise ValueError("Atlas must contain 300 unique model classes")
    return {row["植物ID"]:row for row in rows}


def rows():
    stat=CSV_PATH.stat()
    return _load((stat.st_mtime_ns,stat.st_size))


def reference_image(herb_id):
    row=rows().get(herb_id)
    if not row or not row.get("封面图候选"):return None
    path=(ROOT/row["封面图候选"]).resolve()
    if not path.is_relative_to(TRAIN_IMAGES.resolve()) or path.suffix.lower() not in {".jpg",".jpeg",".png",".webp"}:
        return None
    return path if path.is_file() else None


def identity_metadata(row):
    """Share identity warnings with model outputs without confirming candidates."""
    conflict="冲突" in row["身份核对状态"]
    return dict(identity_conflict=conflict,identity_status=row["身份核对状态"],
        review_status=row["人工审核状态"],original_latin_name=row["Latin Name"].strip(),
        accepted_latin_name="" if conflict else row["规范学名"].strip())


def serialize(row,detail=False):
    materials=json.loads(row["药材记录JSON"] or "[]")
    nature=attributes(row,materials,"药性")
    herb_id=row["植物ID"]
    distribution=row["活体植物分布地区"]
    effects=[effect for effect in EFFECTS if effect in row["传统功效"]]
    identity=identity_metadata(row)
    image=reference_image(herb_id)
    result=dict(id=herb_id,classId=int(row["No"]),name=row["活体植物名称"] or row["Chinese Name"],
        latinName=identity["accepted_latin_name"] or row["Latin Name"],originalLatinName=row["Latin Name"],
        acceptedLatinName=identity["accepted_latin_name"],
        aliases=split_values(row["植物别名"]),family=row["规范科名"] or row["Family"],genus=row["属名"],
        familyChinese=row["资料科名中文"],genusChinese=row["资料属名中文"],
        medicinalPart=medicinal_parts(row,materials),property="、".join(nature),
        properties=nature,flavor=attributes(row,materials,"药味"),meridians=attributes(row,materials,"归经"),
        effects=effects,description=row["简短介绍"] or "植物身份资料尚待核实。",
        image=f"/api/v1/herbs/{herb_id}/reference-image" if image else "",
        imageStatus="dataset_reference" if image else "missing",
        morphology="",traditionalUses=[],precautions=[],background="",
        distribution=distribution,distributionStatus=row["分布资料状态"],habitat=row["生境"],
        growthForm=row["生长形态"],identityStatus=identity["identity_status"],
        identityConflict=identity["identity_conflict"],toxicity=row["毒性"],reviewStatus=identity["review_status"])
    if detail:
        result.update(morphology=row["活体识别特征"],traditionalUses=[row["传统应用"]] if row["传统应用"] else [],
            precautions=[row["使用注意"]] if row["使用注意"] else [],background=row["药材与植物关系说明"],
            elevation=row["海拔"],flowering=row["花期"],fruiting=row["果期"],sporeSeason=row["孢子期"],
            features=[dict(label=field.replace("特征",""),value=row[field]) for field in
                ["生长形态","株高特征","叶特征","花特征","果实特征","种子特征","茎特征","枝特征","根特征",
                 "孢子囊特征","雄球花特征","雌球花特征"] if row[field]],
            completeIntroduction=row["活体植物完整介绍"],medicinalIntroduction=row["药材完整介绍"],
            medicinalRegions=row["药材产区"],materials=materials,
            traditionalEffects=row["传统功效"],natureText=row["药性"],flavorText=row["药味"],
            meridianText=row["归经"],confusion=row["易混淆植物"],differences=row["主要区别"],
            confusionRisk=row["易混淆风险"],confusionStatus=row["易混淆审核状态"],
            taxonomySystem=row["分类体系"],taxonomyStatus=row["分类接受状态"],notes=row["待核实说明"],
            fieldReview=json.loads(row.get("字段核对状态JSON") or "{}"),
            sources=list({e["url"]:dict(name=e["source_name"],url=e["url"],version=e["version"],
                locator=e["locator"]) for e in json.loads(row["字段证据JSON"] or "[]")}.values()),
            updatedAt=row["更新日期"])
    return result


def list_herbs(q="",family="",genus="",region="",effect="",property="",part="",sort="class",
               page=1,page_size=24,recent_ids=""):
    result=[]
    for row in rows().values():
        herb=serialize(row)
        searchable=" ".join(row.get(k,"") for k in ["Chinese Name","Latin Name","规范中文名","规范学名",
            "植物别名","药材名称","规范科名","属名","资料科名中文","资料属名中文","活体植物分布地区","传统功效"])
        if q.strip() and q.strip().casefold() not in searchable.casefold():continue
        if family and herb["family"]!=family:continue
        if genus and herb["genus"]!=genus:continue
        if region and not region_matches(herb["distribution"],region):continue
        if effect and effect not in row["传统功效"]:continue
        if property and property not in herb["properties"]:continue
        if part and part not in herb["medicinalPart"]:continue
        result.append(herb)
    if sort=="name":result.sort(key=lambda h:h["name"])
    elif sort=="recent":
        recent=list(dict.fromkeys(recent_ids.split(",")))
        order={herb_id:index for index,herb_id in enumerate(recent)}
        result.sort(key=lambda h:(order.get(h["id"],len(order)),h["classId"]))
    else:result.sort(key=lambda h:h["classId"])
    total=len(result)
    page=min(page,max(1,(total+page_size-1)//page_size))
    return dict(total=total,collectionTotal=len(rows()),page=page,pageSize=page_size,
                items=result[(page-1)*page_size:page*page_size])


def filters():
    herbs=[serialize(row) for row in rows().values()]
    return dict(total=len(herbs),distributionCount=sum(bool(h["distribution"]) for h in herbs),
        families=sorted({h["family"] for h in herbs if h["family"]}),
        genera=sorted({h["genus"] for h in herbs if h["genus"]}),
        regions=[r for r in REGIONS if any(region_matches(h["distribution"],r) for h in herbs)],
        properties=sorted({p for h in herbs for p in h["properties"]}),
        parts=sorted({p for h in herbs for p in h["medicinalPart"]}),
        effects=[e for e in EFFECTS if any(e in h["effects"] for h in herbs)])
