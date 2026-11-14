"""Plant atlas backed by MySQL when enabled, with explicit CSV mode otherwise."""
import csv
import json
import re
from functools import lru_cache
from pathlib import Path
import content_store
import history_store
import publication_policy as publication
import curated_content

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
    if history_store.enabled():
        return content_store.plant_rows()
    stat=CSV_PATH.stat()
    return _load((stat.st_mtime_ns,stat.st_size))


def reference_image(herb_id, row=None, *, evidence=None, publications=None):
    row=rows().get(herb_id) if row is None else row
    if not publication.plant_is_public(row,evidence):return None
    approved=curated_content.image_path(herb_id,records=publications)
    if approved is not None:return approved
    if not publication.plant_image_is_public(row,evidence):return None
    path=(ROOT/row["封面图"]).resolve()
    if not path.is_relative_to(TRAIN_IMAGES.resolve()) or path.suffix.lower() not in {".jpg",".jpeg",".png",".webp"}:
        return None
    return path if path.is_file() else None


def identity_metadata(row):
    """Model provenance remains separate from publicly released plant knowledge."""
    conflict="冲突" in row["身份核对状态"]
    return dict(identity_conflict=conflict,
        identity_status="名称冲突，该类别不提供植物资料" if conflict else "模型类别记录",
        review_status="", original_latin_name="" if conflict else row["Latin Name"].strip(),
        accepted_latin_name="" if conflict else row["规范学名"].strip())


def serialize(row,detail=False,*,publications=None):
    evidence=publication.botanical_evidence(row)
    if not publication.plant_is_public(row,evidence):return None
    value=lambda field:publication.botanical_value(evidence,field)
    herb_id=row["植物ID"]
    if publications is None:publications=curated_content.publications()[0]
    latin=value("规范学名") or value("植物智学名")
    image=reference_image(herb_id,row=row,evidence=evidence,publications=publications)
    feature_fields=["生长形态","株高特征","叶特征","花特征","果实特征","种子特征",
                    "茎特征","枝特征","根特征","孢子囊特征","雄球花特征","雌球花特征"]
    features=[dict(label=field.replace("特征",""),value=value(field)) for field in feature_fields if value(field)]
    description=value("生长形态") or value("叶特征")
    result=dict(id=herb_id,classId=int(row["No"]),name=value("规范中文名"),latinName=latin,
        originalLatinName=value("植物智学名") or latin,acceptedLatinName=latin,
        aliases=split_values(value("植物别名")),family=value("规范科名"),genus=value("属名"),
        familyChinese=value("资料科名中文"),genusChinese=value("资料属名中文"),
        medicinalPart=[],property="",properties=[],flavor=[],meridians=[],effects=[],description=description,
        image=f"/api/v1/herbs/{herb_id}/reference-image" if image else "",
        imageStatus="published" if image else "missing",morphology="",traditionalUses=[],precautions=[],background="",
        distribution=value("分布地区"),distributionStatus="",habitat=value("生境"),
        growthForm=value("生长形态"),identityStatus="",identityConflict=False,toxicity="",reviewStatus="")
    if detail:
        used_fields=set(feature_fields+["规范学名","规范中文名","植物智学名","植物别名","规范科名","属名",
            "资料科名中文","资料属名中文","分布地区","生境","海拔","花期","果期","孢子期","分类体系","分类接受状态"])
        sources={item["url"]:dict(name=item["source_name"],url=item["url"],version=item.get("version",""),
                    locator=item.get("locator","")) for field,items in evidence.items() if field in used_fields for item in items}
        result.update(morphology="；".join(item["value"] for item in features),
            elevation=value("海拔"),flowering=value("花期"),fruiting=value("果期"),sporeSeason=value("孢子期"),features=features,
            completeIntroduction="\n\n".join(item["label"]+"："+item["value"] for item in features),
            medicinalIntroduction="",medicinalRegions="",materials=[],traditionalEffects="",natureText="",flavorText="",
            meridianText="",confusion="",differences="",confusionRisk="",confusionStatus="",
            taxonomySystem=value("分类体系"),taxonomyStatus=value("分类接受状态"),notes="",fieldReview={},
            sources=list(sources.values()),updatedAt=row["更新日期"])
    editorial=curated_content.plant(herb_id,records=publications)
    result['curated']=bool(editorial)
    if editorial:
        result.update(description=editorial['description'],distribution=editorial['distribution'],habitat=editorial['habitat'],
            imageCredit=curated_content.public_credit(editorial['imageCredit']),editorialOrder=editorial['displayOrder'])
        result.update({field:editorial[field] for field in ('family','familyChinese','genus','genusChinese','growthForm') if field in editorial})
        if image:result['image']+= '?v='+editorial['imageCredit']['sha256'][:12]
        if detail:
            result.update(completeIntroduction=editorial['completeIntroduction'],observation=editorial['observation'],
                features=editorial['features'],sources=editorial['sources'],updatedAt=editorial['updatedAt'],
                morphology='；'.join(item['value'] for item in editorial['features']),flowering='',fruiting='',
                elevation='',sporeSeason='')
    return result


def list_herbs(q="",family="",genus="",region="",effect="",property="",part="",sort="class",
               page=1,page_size=24,recent_ids=""):
    result=[]
    # Share one publication snapshot across all 300 records. Reading it inside
    # serialize/image lookup repeatedly reparses .env and repeats database checks.
    source_rows=rows()
    publications=curated_content.publications()[0]
    collection_total=0
    query=q.strip().casefold()
    for row in source_rows.values():
        herb=serialize(row,publications=publications)
        if herb is None:continue
        collection_total+=1
        searchable=" ".join([herb["name"],herb["latinName"],*herb["aliases"],herb["family"],herb["genus"],herb["distribution"]])
        if query and query not in searchable.casefold():continue
        if family and herb["family"]!=family:continue
        if genus and herb["genus"]!=genus:continue
        if region and not region_matches(herb["distribution"],region):continue
        if effect and effect not in herb["effects"]:continue
        if property and property not in herb["properties"]:continue
        if part and part not in herb["medicinalPart"]:continue
        result.append(herb)
    if sort=="name":result.sort(key=lambda h:h["name"])
    elif sort=="featured":result.sort(key=lambda h:(not h['curated'],h.get('editorialOrder',h['classId'])))
    elif sort=="recent":
        recent=list(dict.fromkeys(recent_ids.split(",")))
        order={herb_id:index for index,herb_id in enumerate(recent)}
        result.sort(key=lambda h:(order.get(h["id"],len(order)),h["classId"]))
    else:result.sort(key=lambda h:h["classId"])
    total=len(result)
    page=min(page,max(1,(total+page_size-1)//page_size))
    return dict(total=total,collectionTotal=collection_total,page=page,pageSize=page_size,
                items=result[(page-1)*page_size:page*page_size])


def filters():
    source_rows=rows()
    publications=curated_content.publications()[0]
    herbs=[herb for row in source_rows.values() if (herb:=serialize(row,publications=publications)) is not None]
    return dict(total=len(herbs),curatedCount=sum(h['curated'] for h in herbs),distributionCount=sum(bool(h["distribution"]) for h in herbs),
        families=sorted({h["family"] for h in herbs if h["family"]}),
        genera=sorted({h["genus"] for h in herbs if h["genus"]}),
        regions=[r for r in REGIONS if any(region_matches(h["distribution"],r) for h in herbs)],
        properties=sorted({p for h in herbs for p in h["properties"]}),
        parts=sorted({p for h in herbs for p in h["medicinalPart"]}),
        effects=[e for e in EFFECTS if any(e in h["effects"] for h in herbs)])
