"""Import the five enriched CSVs into MySQL without replacing existing data."""
import argparse
import csv
import getpass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "author_tcmp_300"
FILES = {
    "plants": "tcmp-info-20250329.csv",
    "medicinal_materials": "tcmp-medicinal-materials.csv",
    "image_candidates": "tcmp-image-candidates.csv",
    "field_sources": "tcmp-field-sources.csv",
    "review_queue": "tcmp-review-queue.csv",
}
EXPECTED_COUNTS = {"plants":300,"medicinal_materials":219,"image_candidates":509,"review_queue":1663}
SURROGATE_TABLES = {"medicinal_materials", "image_candidates", "review_queue"}


def quote(identifier):
    return "`" + identifier.replace("`", "``") + "`"


def load_csvs(directory=DATA, check_expected_counts=True):
    datasets = {}
    for table, filename in FILES.items():
        with (directory / filename).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        if not columns or len(columns) != len(set(columns)):
            raise ValueError(f"Invalid headers: {filename}")
        if check_expected_counts and table in EXPECTED_COUNTS and len(rows) != EXPECTED_COUNTS[table]:
            raise ValueError(f"Unexpected number of rows: {filename}")
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ValueError(f"Malformed CSV: {filename}")
        for row in rows:
            int(row["No"])
            for name in columns:
                if name.endswith("JSON") and row[name]:
                    json.loads(row[name])
        datasets[table] = (columns, rows)
    plants = {r["No"]: r["植物ID"] for r in datasets["plants"][1]}
    if len(plants) != 300 or len(set(plants.values())) != 300:
        raise ValueError("Duplicate plant keys")
    evidence = datasets["field_sources"][1]
    ids = {r["evidence_id"] for r in evidence}
    if len(ids) != len(evidence):
        raise ValueError("Duplicate evidence keys")
    for table, (_, rows) in datasets.items():
        for row in rows:
            if row["No"] not in plants:
                raise ValueError(f"Unknown plant in {table}")
            if "植物ID" in row and row["植物ID"] != plants[row["No"]]:
                raise ValueError(f"Mismatched plant key in {table}")
    for row in datasets["plants"][1]:
        for cited_ids in json.loads(row["字段来源JSON"]).values():
            if not set(cited_ids).issubset(ids):
                raise ValueError("Unknown evidence reference")
    return datasets


def column_type(name):
    if name == "No":
        return "SMALLINT UNSIGNED NOT NULL"
    if name in {"植物ID", "药材ID", "evidence_id"}:
        return "VARCHAR(64) COLLATE utf8mb4_0900_bin NOT NULL"
    if name in {"Chinese Name", "规范中文名", "规范科名", "属名", "药材名称", "field"}:
        return "VARCHAR(255) NULL"
    if name.endswith("JSON"):
        return "JSON NULL"
    return "LONGTEXT NULL"


def create_table_sql(table, columns):
    definitions = []
    if table in SURROGATE_TABLES:
        definitions.append("`id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY")
    definitions.extend(f"{quote(c)} {column_type(c)}" for c in columns)
    if table == "plants":
        definitions.extend([
            "PRIMARY KEY (`No`)",
            "UNIQUE KEY `uq_plant_id` (`植物ID`)",
            "UNIQUE KEY `uq_plant_pair` (`No`, `植物ID`)",
            "KEY `idx_chinese_name` (`Chinese Name`)",
            "KEY `idx_standard_name` (`规范中文名`)",
            "KEY `idx_family` (`规范科名`)",
            "KEY `idx_genus` (`属名`)",
        ])
    elif table == "field_sources":
        definitions.extend([
            "PRIMARY KEY (`evidence_id`)",
            "KEY `idx_plant_field` (`No`, `field`)",
            "CONSTRAINT `fk_sources_plant` FOREIGN KEY (`No`) REFERENCES `plants` (`No`)",
        ])
    else:
        definitions.append(
            f"CONSTRAINT {quote('fk_' + table + '_plant')} "
            "FOREIGN KEY (`No`, `植物ID`) REFERENCES `plants` (`No`, `植物ID`)"
        )
        if table == "medicinal_materials":
            definitions.extend([
                "UNIQUE KEY `uq_plant_material` (`No`, `药材ID`)",
                "KEY `idx_material_name` (`药材名称`)",
            ])
    return (
        f"CREATE TABLE IF NOT EXISTS {quote(table)} (\n  "
        + ",\n  ".join(definitions)
        + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
    )


def normalized(values, columns):
    result = []
    for name, value in zip(columns, values):
        if value is None or value == "":
            result.append(None)
        elif name == "No":
            result.append(int(value))
        elif name.endswith("JSON"):
            result.append(json.dumps(json.loads(value), ensure_ascii=False, sort_keys=True))
        else:
            result.append(value)
    return tuple(result)


def verify(cursor, datasets):
    counts = {}
    for table, (columns, rows) in datasets.items():
        cursor.execute(f"SELECT {', '.join(map(quote, columns))} FROM {quote(table)}")
        actual = cursor.fetchall()
        expected_rows = [normalized([r[c] for c in columns], columns) for r in rows]
        actual_rows = [normalized(r, columns) for r in actual]
        # JSON string sorting preserves duplicate rows and avoids comparing None to str.
        key = lambda r: json.dumps(r, ensure_ascii=False)
        if sorted(expected_rows, key=key) != sorted(actual_rows, key=key):
            raise ValueError(f"Database values differ from CSV: {table}")
        counts[table] = len(actual)
    return counts


def run(args):
    datasets = load_csvs()
    password = os.environ.get("TCMP_MYSQL_PASSWORD") or getpass.getpass("MySQL password: ")
    connection_args = dict(
        host=args.host, port=args.port, user=args.user, password=password,
        charset="utf8mb4", connect_timeout=10, read_timeout=60, write_timeout=60,
        autocommit=False,
    )
    conn = pymysql.connect(**connection_args)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {quote(args.database)} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            conn.select_db(args.database)
            for table, (columns, _) in datasets.items():
                cur.execute(create_table_sql(table, columns))
                cur.execute(f"SHOW COLUMNS FROM {quote(table)}")
                actual_columns = [r[0] for r in cur.fetchall()]
                expected_columns = (["id"] if table in SURROGATE_TABLES else []) + columns
                if actual_columns != expected_columns:
                    raise ValueError(f"Existing table has incompatible columns: {table}")
            existing_counts = {}
            for table in FILES:
                cur.execute(f"SELECT COUNT(*) FROM {quote(table)}")
                existing_counts[table] = cur.fetchone()[0]
            if any(existing_counts.values()):
                # An identical completed import is a no-op; partial/different data is refused.
                counts = verify(cur, datasets)
                action = "already_present"
            else:
                for table, (columns, rows) in datasets.items():
                    statement = (
                        f"INSERT INTO {quote(table)} ({', '.join(map(quote, columns))}) "
                        f"VALUES ({', '.join(['%s'] * len(columns))})"
                    )
                    values = [tuple(None if r[c] == "" else int(r[c]) if c == "No" else r[c]
                                    for c in columns) for r in rows]
                    for start in range(0, len(values), 100):
                        cur.executemany(statement, values[start:start + 100])
                    print(f"Imported {table}: {len(rows)} rows", flush=True)
                counts = verify(cur, datasets)
                action = "imported"
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    # Validate committed data using a fresh connection, including every source field.
    with pymysql.connect(database=args.database, **connection_args) as committed:
        with committed.cursor() as cur:
            committed_counts = verify(cur, datasets)
    if committed_counts != counts:
        raise ValueError("Post-commit record counts differ")
    report = {
        "status": "PASS", "action": action,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host, "port": args.port, "database": args.database,
        "mysql_version": version, "charset": "utf8mb4", "row_counts": counts,
        "plants_source_columns": len(datasets["plants"][0]),
        "verification": "Every CSV value matches committed data; JSON compared semantically; foreign keys enforced.",
        "files": {table: {"filename": name,
                            "sha256": hashlib.sha256((DATA / name).read_bytes()).hexdigest()}
                  for table, name in FILES.items()},
    }
    report_path = DATA / "mysql_import_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--database", default="tcmp_300")
    args = parser.parse_args()
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    run(args)
