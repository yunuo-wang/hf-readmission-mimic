"""Project paths. Override with environment variables if your setup differs."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIMIC_DIR = Path(os.environ.get(
    "MIMIC_DIR", Path.home() / "data/mimic/physionet.org/files/mimiciv/3.1"))
# The DuckDB file is kept outside iCloud (binary, rebuilt on every run)
DB_PATH = Path(os.environ.get("HF_DB_PATH", Path.home() / "data/mimic/hf_readmission.duckdb"))

SQL_DIR = ROOT / "sql"
SEEDS_DIR = ROOT / "seeds"
OUT_TABLES = ROOT / "outputs" / "tables"
OUT_FIGS = ROOT / "outputs" / "figures"
for d in (OUT_TABLES, OUT_FIGS):
    d.mkdir(parents=True, exist_ok=True)
