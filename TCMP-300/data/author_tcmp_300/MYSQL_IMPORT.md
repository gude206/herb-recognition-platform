# TCMP-300 MySQL 数据导入

连接地址：`127.0.0.1:3306`；数据库：`tcmp_300`；字符集：`utf8mb4`。
密码不保存在导入脚本或报告中。导入状态以 `mysql_import_report.json` 为准。

| 表 | 用途 | 记录数 |
|---|---|---:|
| plants | 活体植物主表，保留 CSV 全部 103 个字段及内嵌关联资料 | 300 |
| medicinal_materials | 药材、炮制品及植物基原关联 | 219 |
| image_candidates | 尚未发布的图片候选 | 509 |
| field_sources | 字段资料来源与证据 | 12956 |
| review_queue | 待人工核实、缺失字段清单 | 1663 |

`plants.No` 是植物主键，`植物ID` 是唯一业务标识。药材、图片、待核实表通过
`(No, 植物ID)` 外键关联植物；字段来源表通过 `No` 外键关联植物，其主键是
`evidence_id`。药材表、图片表、待核实表增加自增 `id`；药材表另设
`(No, 药材ID)` 唯一约束。同一植物可以对应多个药材。

原始中文字段名保持不变，SQL 中用反引号引用。JSON 字段使用 MySQL 原生
JSON 类型；CSV 空白值写为 SQL NULL。图片候选的本地路径保留相对于
TCMP-300 项目根目录的原路径，图片文件本身未写入数据库。

导入未改变资料的审核结论：正式图片仍缺失，记录仍待人工审核。详见
`ENRICHMENT_REPORT.md`。

## 查询示例

活体识别详情可以只查 `plants`，无需关联其他表。主CSV和这张表均包含所有已有
药材明细、图片候选、字段证据和待核实事项。药材明细仍对应同一个活体植物，
不增加模型类别。`活体植物分布地区` 和 `药材产区` 分开存储。

```sql
USE tcmp_300;
SELECT `No`, `植物ID`, `Chinese Name`, `规范学名`, `规范科名`, `属名`, `简短介绍`
FROM plants ORDER BY `No`;

SELECT `No`, `活体植物名称`, `活体植物分布地区`, `分布资料状态`, `生境`,
       `活体识别特征`, `活体植物完整介绍`, `药材完整介绍`
FROM plants WHERE `No` = 4;

SELECT p.`Chinese Name`, m.`药材名称`, m.`药用部位`, m.`传统功效原文`
FROM plants p JOIN medicinal_materials m ON p.`No` = m.`No`
WHERE p.`No` = 4;

SELECT field, value, source_name, url, evidence_id
FROM field_sources WHERE `No` = 4;
```

## 再次导入

在 TCMP-300 项目目录运行：

```powershell
& '.\.venv-api\Scripts\python.exe' -m pip install -r requirements-mysql.txt
& '.\.venv-api\Scripts\python.exe' tools/import_tcmp_mysql.py
```

脚本交互式读取密码，也支持 `TCMP_MYSQL_PASSWORD` 环境变量。所有数据在
一个事务中导入，提交前及提交后逐字段核对五张表。结构创建使用 MySQL DDL，
失败时可能保留空数据库或空表；数据插入失败会回滚。已存在完全一致的数据时
仅核对，存在部分或不同数据时停止，不覆盖现有数据。

当前项目识别 API 仍使用 CSV；此次操作只完成数据库建表与导入。

2026-09-30已同步单文件活体资料整合版。同步前通过逐字段校验确认数据库与
整合前CSV一致，已保存 SQL 备份至
`before_live_plant_consolidation_20260930/tcmp_300_before_live_plant_20260930.sql.gz`。
整合后主表共103字段；提交后已逐字段核对五张表与当前CSV一致。

2026-09-30已同步来源复查补充版。主表103字段，字段来源12956条，待核实清单1663条（含已补充、不适用及仍缺少可靠资料的状态）。最终五表与当前CSV逐字段一致，详见 REVIEW_COMPLETION_REPORT.md。
