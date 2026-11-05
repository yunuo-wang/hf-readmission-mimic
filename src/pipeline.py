"""Build the DuckDB clinical data mart from MIMIC-IV and run the SQL analytics."""
import re
import time

import duckdb

from .config import DB_PATH, MIMIC_DIR, OUT_TABLES, SEEDS_DIR, SQL_DIR
from .ontology_rxnav import build_drug_class_map


def run_sql_file(con, name):
    sql = (SQL_DIR / name).read_text()
    sql = sql.replace("{MIMIC}", str(MIMIC_DIR)).replace("{SEEDS}", str(SEEDS_DIR))
    t = time.time()
    con.execute(sql)
    print(f"  {name:<20} {time.time() - t:6.1f}s")


def run_named_queries(con, name="05_queries.sql"):
    """Execute each '-- name: xxx' block and save its result to outputs/tables/xxx.csv."""
    text = (SQL_DIR / name).read_text()
    blocks = re.split(r"^-- name:\s*", text, flags=re.M)[1:]
    results = {}
    for b in blocks:
        qname, body = b.split("\n", 1)
        qname = qname.strip()
        df = con.sql(body.strip().rstrip(";")).df()
        df.to_csv(OUT_TABLES / f"{qname}.csv", index=False)
        results[qname] = df
    print(f"  saved {len(results)} query results to {OUT_TABLES}")
    return results


def build(con=None):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = con or duckdb.connect(str(DB_PATH))
    con.execute("SET preserve_insertion_order = false; SET threads TO 8;")
    print("[1] Staging + vocabulary layer");  run_sql_file(con, "01_staging.sql")
    print("[2] Cohort + readmission outcome"); run_sql_file(con, "02_cohort.sql")
    print("[3] Star-schema data mart (scans labevents/prescriptions; a few minutes)")
    run_sql_file(con, "03_warehouse.sql")
    print("[4] Drug ontology mapping (RxNorm -> ATC via RxNav)")
    build_drug_class_map(con)
    print("[5] Analytic table");                run_sql_file(con, "04_analytic.sql")
    print("[6] SQL analytics");                 res = run_named_queries(con)
    return con, res
