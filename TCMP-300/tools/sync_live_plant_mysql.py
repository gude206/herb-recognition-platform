"""Safely migrate the verified initial import to the single-file live plant data."""
import csv
import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymysql
from import_tcmp_mysql import DATA, FILES, column_type, load_csvs, normalized, quote, verify

BASELINE = DATA / "before_live_plant_consolidation_20260930"


def run(baseline_directory=BASELINE):
    datasets = load_csvs(check_expected_counts=False)
    baseline_directory=baseline_directory.resolve()
    baseline = load_csvs(baseline_directory, check_expected_counts=False)
    old_plants={r["No"]:r for r in baseline["plants"][1]}
    for row in datasets["plants"][1]:
        if any(row[c]!=old_plants[row["No"]][c] for c in ["No","Latin Name","Family","Chinese Name","植物ID"]):
            raise ValueError("A model class label changed")
    password = os.environ["TCMP_MYSQL_PASSWORD"]
    kwargs = dict(host="127.0.0.1", port=3306, user="root", password=password,
                  database="tcmp_300", charset="utf8mb4", autocommit=False,
                  connect_timeout=10, read_timeout=60, write_timeout=60)
    backup_path = baseline_directory / "tcmp_300_before_sync_20260930.sql.gz"
    with pymysql.connect(**kwargs) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('tcmp_300_live_plant_sync', 0)")
            if cur.fetchone()[0] != 1:
                raise RuntimeError("Another import is running")
            try:
                cur.execute("SHOW COLUMNS FROM plants")
                actual_columns = [r[0] for r in cur.fetchall()]
                old_columns = baseline["plants"][0]
                new_columns = datasets["plants"][0]
                if actual_columns == new_columns:
                    try:
                        verify(cur, datasets)
                    except ValueError:
                        pass
                    else:
                        print("Database already contains the verified live plant data")
                        return
                if actual_columns != old_columns:
                    raise ValueError("Existing schema differs from the verified baseline")
                verify(cur, baseline)
                # Check surrogate IDs using the original import order before updating reviews.
                review_columns, old_reviews = baseline["review_queue"]
                cur.execute("SELECT id, " + ", ".join(map(quote, review_columns)) +
                            " FROM review_queue ORDER BY id")
                review_records = cur.fetchall()
                if [normalized(r[1:], review_columns) for r in review_records] != [
                        normalized([r[c] for c in review_columns], review_columns) for r in old_reviews]:
                    raise ValueError("Review order no longer matches the original import")
                conn.commit()
                child_env = dict(os.environ, MYSQL_PWD=password)
                dump = subprocess.run([
                    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
                    "--no-defaults", "--host=127.0.0.1", "--port=3306", "--user=root",
                    "--single-transaction", "--set-gtid-purged=OFF", "--no-tablespaces",
                    "--default-character-set=utf8mb4", "tcmp_300"],
                    env=child_env, capture_output=True, check=True)
                if not backup_path.exists():
                    with gzip.open(backup_path, "wb") as handle:
                        handle.write(dump.stdout)
                report_file = DATA / "mysql_import_report.json"
                if report_file.exists() and not (baseline_directory / report_file.name).exists():
                    shutil.copy2(report_file, baseline_directory / report_file.name)
                for c in new_columns:
                    if c not in old_columns:
                        cur.execute(f"ALTER TABLE plants ADD COLUMN {quote(c)} {column_type(c)}")
                # Stable training-label keys must remain unchanged.
                old_plants = {r["No"]: r for r in baseline["plants"][1]}
                for row in datasets["plants"][1]:
                    if any(row[c] != old_plants[row["No"]][c]
                           for c in ["No", "Latin Name", "Family", "Chinese Name", "植物ID"]):
                        raise ValueError("A model class label changed")
                editable = [c for c in new_columns if c != "No"]
                statement = "UPDATE plants SET " + ", ".join(quote(c) + "=%s" for c in editable) + " WHERE `No`=%s"
                values = [tuple(None if not r[c] else r[c] for c in editable) + (int(r["No"]),)
                          for r in datasets["plants"][1]]
                cur.executemany(statement, values)
                source_columns, new_sources = datasets["field_sources"]
                old_sources = {r["evidence_id"]: r for r in baseline["field_sources"][1]}
                changed_sources = [r for r in new_sources if r != old_sources.get(r["evidence_id"])]
                for row in changed_sources:
                    if row["evidence_id"] in old_sources:
                        editable = [c for c in source_columns if c != "evidence_id"]
                        cur.execute("UPDATE field_sources SET " + ", ".join(quote(c) + "=%s" for c in editable) +
                                    " WHERE evidence_id=%s",
                                    tuple(None if not row[c] else row[c] for c in editable) + (row["evidence_id"],))
                    else:
                        cur.execute("INSERT INTO field_sources (" + ", ".join(map(quote, source_columns)) +
                                    ") VALUES (" + ", ".join(["%s"] * len(source_columns)) + ")",
                                    tuple(None if not row[c] else row[c] for c in source_columns))
                new_reviews = datasets["review_queue"][1]
                for record, old, new in zip(review_records, old_reviews, new_reviews):
                    if old != new:
                        cur.execute("UPDATE review_queue SET " + ", ".join(quote(c) + "=%s" for c in review_columns) +
                                    " WHERE id=%s", tuple(new[c] or None for c in review_columns) + (record[0],))
                for row in new_reviews[len(old_reviews):]:
                    cur.execute("INSERT INTO review_queue (" + ", ".join(map(quote, review_columns)) +
                                ") VALUES (" + ", ".join(["%s"] * len(review_columns)) + ")",
                                tuple(row[c] or None for c in review_columns))
                counts = verify(cur, datasets)
                conn.commit()
                cur.execute("SELECT VERSION()")
                version = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.execute("SELECT RELEASE_LOCK('tcmp_300_live_plant_sync')")
    with pymysql.connect(**kwargs) as conn:
        with conn.cursor() as cur:
            if verify(cur, datasets) != counts:
                raise ValueError("Committed data differs")
    report = {
        "status": "PASS", "action": "source_review_completion_synced",
        "verified_at": datetime.now(timezone.utc).isoformat(), "host": "127.0.0.1", "port": 3306,
        "database": "tcmp_300", "mysql_version": version, "charset": "utf8mb4",
        "row_counts": counts, "plants_source_columns": len(new_columns),
        "verification": "All five tables match CSV values after commit; main table embeds all associated introductions and evidence.",
        "database_backup": str(backup_path),
        "files": {table: {"filename": name,
                            "sha256": hashlib.sha256((DATA / name).read_bytes()).hexdigest()}
                  for table, name in FILES.items()},
    }
    (DATA / "mysql_import_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",type=Path,default=BASELINE)
    run(parser.parse_args().baseline)
