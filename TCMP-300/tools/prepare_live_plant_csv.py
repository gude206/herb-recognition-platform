"""Prepare source-backed, self-contained live plant records for CSV authoring."""
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "author_tcmp_300"
BACKUP = DATA / "before_live_plant_consolidation_20260930"
ADDED = ["识别对象", "活体植物名称", "活体植物分布地区", "分布资料状态", "药材产区",
         "活体识别特征", "活体植物完整介绍", "药材完整介绍", "药材与植物关系说明",
         "字段证据JSON", "待核实事项JSON"]


def read(filename, directory=DATA):
    with (directory / filename).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def group(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["No"]].append(row)
    return groups


def clean_plant_distribution(text):
    # Strip explicitly labelled medicinal production areas and habitat sentences.
    sentences = re.split(r"(?<=[。；;])", text)
    return "".join(s for s in sentences if not re.search(
        r"药材(?:主产|产于|产地)|^\s*(?:生于|生长于|生长在|生海拔|模式标本)", s)).strip()


def render_fields(row, fields):
    return "\n".join(f"{field}：{row[field]}" for field in fields if row.get(field))


def prepare(output):
    filenames = ["tcmp-info-20250329.csv", "tcmp-medicinal-materials.csv",
                 "tcmp-image-candidates.csv", "tcmp-field-sources.csv", "tcmp-review-queue.csv"]
    BACKUP.mkdir(exist_ok=True)
    for name in filenames:
        if not (BACKUP / name).exists():
            shutil.copy2(DATA / name, BACKUP / name)
    # Always use the immutable baseline so reruns do not duplicate additions.
    columns, plants = read(filenames[0], BACKUP)
    _, medicines = read(filenames[1], BACKUP)
    _, images = read(filenames[2], BACKUP)
    source_columns, sources = read(filenames[3], BACKUP)
    review_columns, reviews = read(filenames[4], BACKUP)
    by_no = {r["No"]: r for r in plants}

    corrections = {
        ("150", "分布地区"): "产于我国长江以南各省区以及陕西、甘肃南部和台湾省。分布于锡金、不丹、缅甸、越南。",
        ("239", "分布地区"): "除新疆、青海、台湾和海南外，分布几遍及全国。俄罗斯西伯利亚、蒙古、朝鲜、日本和北美温带地区广泛分布。",
        ("39", "生境"): "",
        ("71", "生境"): "生山地杂木林边、灌丛或荒野，海拔500-2000米。",
        ("237", "生境"): "生海拔2500米以下的湿润的草坡、沟边、路旁及林缘。",
        ("239", "生境"): "生于海拔400-2 200米山坡林下或岩石缝的阴湿处。",
        ("260", "生境"): "生长于向阳山坡及草丛中。",
    }
    for (number, field), value in corrections.items():
        row = by_no[number]
        if value:
            # Validate every edited sentence against the already retained source text.
            origin = row["植物志原文"] + row["分布地区"]
            for sentence in value.split("。"):
                if sentence and sentence not in origin:
                    raise ValueError(f"Correction is absent from source: {number}/{field}")
        mapping = json.loads(row["字段来源JSON"])
        for evidence in sources:
            if evidence["No"] == number and evidence["field"] == field:
                evidence["status"] = "旧版提取；当前值已更正，以活体整合版字段及新证据为准"
        mapping.pop(field, None)
        row[field] = value
        if value:
            url = next(u for u in row["资料来源链接"].split("；") if "iplant.cn/info/" in u)
            evidence_id = "live-" + hashlib.sha256((number + field + value).encode()).hexdigest()[:24]
            evidence = dict(No=number, field=field, value=value,
                            source_name="中国植物志（植物智数字版）", url=url,
                            version=row["植物志引用"] or "网页，未声明版本",
                            locator="当前类群原文的明确分布/生境句；未采用后附变种及花序着生位置",
                            status="已与保存原文逐句核对，待人工审核", retrieved_date="2026-09-30",
                            evidence_id=evidence_id)
            sources.append(evidence)
            mapping[field] = [evidence_id]
        row["字段来源JSON"] = pack(mapping)

    for review in reviews:
        if review["No"] in {"150", "239"} and review["问题说明"].startswith("分布地区："):
            review["处理状态"] = "已补充植物志原文记载，待人工复核"
    # The removed entry described flower position, not ecological habitat.
    reviews.append({"No": "39", "植物ID": by_no["39"]["植物ID"], "中文名": by_no["39"]["Chinese Name"],
                    "问题类型": "生境缺失", "问题说明": "生境：原提取内容为花序着生位置，已清空；待查可靠生境资料",
                    "处理状态": "待人工核实"})

    med_groups, image_groups = group(medicines), group(images)
    source_groups, review_groups = group(sources), group(reviews)
    for row in plants:
        number = row["No"]
        meds = med_groups[number]
        row["药材记录JSON"] = pack(meds)
        row["图片候选JSON"] = pack(image_groups[number])
        row["识别对象"] = "活体植物"
        row["活体植物名称"] = row["规范中文名"] or row["Chinese Name"]
        row["活体植物分布地区"] = clean_plant_distribution(row["分布地区"])
        row["分布资料状态"] = ("身份冲突，暂不采用分布信息" if number == "51" else
                                "有来源记载，待人工核实" if row["活体植物分布地区"] else
                                "未取得可靠分布资料，待补充")
        row["药材产区"] = "。".join(dict.fromkeys(re.findall(
            r"药材(?:主产(?:于)?|产于|产地)[^。；;]+", row["生境分布原文"] + "。" + row["分布地区"])))
        row["活体识别特征"] = render_fields(row, [
            "生长形态", "株高特征", "叶特征", "花特征", "果实特征", "种子特征",
            "茎特征", "枝特征", "根特征", "孢子囊特征", "雄球花特征", "雌球花特征", "识别要点"])
        relation_lines = []
        med_lines = []
        for med in meds:
            relation_lines.append("：".join(filter(None, [med["药材名称"], med.get("基原关联类型"),
                                                        med.get("药用部位"), med.get("加工状态")])))
            med_lines.append(render_fields(med, list(med)))
        row["药材与植物关系说明"] = "\n".join(relation_lines) or row["药用部位原文"]
        # Retain both plant-database knowledge and material-specific source descriptions.
        sections = []
        plant_drug_info = render_fields(row, ["药材名称", "药用部位", "加工状态", "药性", "药味", "归经",
                                             "传统功效", "传统应用", "毒性", "使用注意", "药用部位原文",
                                             "采收加工原文", "性味功能原文", "药材审核状态"])
        if plant_drug_info:
            sections.append("植物资料中记载的药材知识\n" + plant_drug_info)
        if med_lines:
            sections.append("对应药材及炮制品的详细记录\n\n" + "\n\n".join(med_lines))
        row["药材完整介绍"] = "\n\n".join(sections)
        row["字段证据JSON"] = pack(source_groups[number])
        row["待核实事项JSON"] = pack(review_groups[number])
        introduction = ["植物名称：" + row["活体植物名称"], "识别对象：活体植物"]
        identity = render_fields(row, ["原始学名", "规范学名", "植物别名", "学名异名", "规范科名", "属名",
                                      "资料科名中文", "资料属名中文", "身份核对状态"])
        if identity:
            introduction.append(identity)
        if row["简短介绍"]:
            introduction.append("简介：" + row["简短介绍"])
        introduction.append("植物分布地区：" + (row["活体植物分布地区"] or row["分布资料状态"]))
        introduction.append(render_fields(row, ["生境", "海拔", "花期", "果期", "孢子期"]))
        if row["活体识别特征"]:
            introduction.append("活体形态特征\n" + row["活体识别特征"])
        if row["形态描述"]:
            introduction.append("完整形态描述：" + row["形态描述"])
        confusion = render_fields(row, ["易混淆植物", "主要区别", "易混淆风险", "易混淆审核状态"])
        if confusion:
            introduction.append(confusion)
        if row["药材完整介绍"]:
            introduction.append(row["药材完整介绍"])
        if row["药材产区"]:
            introduction.append("药材产区：" + row["药材产区"])
        introduction.append(render_fields(row, ["资料来源名称", "资料来源链接", "人工审核状态", "待核实说明"]))
        row["活体植物完整介绍"] = "\n\n".join(s for s in introduction if s)
    all_columns = columns + [c for c in ADDED if c not in columns]
    datasets = {
        filenames[0]: {"columns": all_columns, "rows": [[r[c] for c in all_columns] for r in plants]},
        filenames[3]: {"columns": source_columns, "rows": [[r[c] for c in source_columns] for r in sources]},
        filenames[4]: {"columns": review_columns, "rows": [[r[c] for c in review_columns] for r in reviews]},
    }
    Path(output).write_text(pack(datasets), encoding="utf-8")
    print(pack({"rows": len(plants), "columns": len(all_columns),
                "distribution_coverage": sum(bool(r["活体植物分布地区"]) for r in plants),
                "evidence_rows": len(sources), "review_rows": len(reviews),
                "longest_cell": max(len(v) for r in plants for v in r.values()),
                "missing_distribution": [r["No"] for r in plants if not r["活体植物分布地区"]]}))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    prepare(sys.argv[1])
