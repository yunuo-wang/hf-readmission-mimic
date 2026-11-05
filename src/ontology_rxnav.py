"""
Drug ontology integration: map free-text MIMIC drug names to WHO-ATC classes
through the NLM RxNorm / RxClass web services (RxNav).

  MIMIC drug string --approximateTerm--> RxCUI --related(tty=IN)--> ingredient
  ingredient RxCUI --rxclass byRxcui (relaSource=ATC)--> ATC class (e.g. C07AB)

Results are cached in seeds/rxnav_atc_cache.csv so the project is reproducible
offline. If RxNav cannot be reached, a curated keyword list
(seeds/drug_class_fallback.csv) is used instead.
"""
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .config import SEEDS_DIR

BASE = "https://rxnav.nlm.nih.gov/REST"
CACHE = SEEDS_DIR / "rxnav_atc_cache.csv"


def _get(url, retries=3):
    for k in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(1 + k)
    return None


def map_one(drug_name):
    """Return list of dicts (drug_norm, rxcui, ingredient, atc_code, atc_name)."""
    q = urllib.parse.quote(drug_name)
    d = _get(f"{BASE}/approximateTerm.json?term={q}&maxEntries=1&option=1")
    cands = (d or {}).get("approximateGroup", {}).get("candidate", [])
    if not cands:
        return [dict(drug_norm=drug_name, rxcui=None, ingredient=None, atc_code=None, atc_name=None)]
    rxcui = cands[0]["rxcui"]
    rel = _get(f"{BASE}/rxcui/{rxcui}/related.json?tty=IN") or {}
    ings = [(p["rxcui"], p["name"])
            for g in rel.get("relatedGroup", {}).get("conceptGroup", []) or []
            for p in g.get("conceptProperties", []) or []]
    rows = []
    for ing_cui, ing_name in ings:
        cl = _get(f"{BASE}/rxclass/class/byRxcui.json?rxcui={ing_cui}&relaSource=ATC") or {}
        for it in cl.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
            if it["minConcept"]["rxcui"] != ing_cui:      # skip combination products
                continue
            c = it["rxclassMinConceptItem"]
            rows.append(dict(drug_norm=drug_name, rxcui=rxcui, ingredient=ing_name,
                             atc_code=c["classId"], atc_name=c["className"]))
    if not rows:
        rows.append(dict(drug_norm=drug_name, rxcui=rxcui,
                         ingredient=";".join(n for _, n in ings) or None, atc_code=None, atc_name=None))
    return rows


def build_drug_class_map(con, min_count=5):
    """Create dw.map_drug_class(drug_norm, drug_class, atc_code, source)."""
    names = con.sql(f"""
        SELECT drug_norm, COUNT(*) n FROM dw.stg_discharge_rx
        GROUP BY 1 HAVING COUNT(*) >= {min_count} ORDER BY n DESC""").df()
    cache = pd.read_csv(CACHE, dtype=str) if CACHE.exists() else pd.DataFrame(
        columns=["drug_norm", "rxcui", "ingredient", "atc_code", "atc_name"])
    todo = sorted(set(names.drug_norm) - set(cache.drug_norm))
    print(f"  RxNav: {len(names)} distinct drug strings (>= {min_count} orders); "
          f"{len(todo)} not yet cached")

    source = "RxNav ATC"
    if todo:
        if _get(f"{BASE}/version.json") is None:
            print("  RxNav unreachable -> using curated keyword fallback")
            source = None
        else:
            with ThreadPoolExecutor(max_workers=8) as ex:   # RxNav allows 20 req/s
                results = list(ex.map(map_one, todo))
            new = pd.DataFrame([r for rs in results for r in rs])
            cache = pd.concat([cache, new], ignore_index=True)
            cache.to_csv(CACHE, index=False)

    targets = pd.read_csv(SEEDS_DIR / "drug_class_targets.csv")
    rows = []
    if source:
        c = cache[cache.drug_norm.isin(names.drug_norm) & cache.atc_code.notna()]
        for _, r in c.iterrows():
            for _, t in targets.iterrows():
                if str(r.atc_code).startswith(t.atc_prefix):
                    rows.append((r.drug_norm, t.drug_class, r.atc_code, "RxNav ATC"))
    else:
        fb = pd.read_csv(SEEDS_DIR / "drug_class_fallback.csv")
        for d in names.drug_norm:
            for _, t in fb.iterrows():
                if t.name_keyword in d:
                    rows.append((d, t.drug_class, None, "keyword fallback"))
    m = pd.DataFrame(rows, columns=["drug_norm", "drug_class", "atc_code", "source"]).drop_duplicates()
    # Exclude non-systemic forms that share an ingredient (e.g. timolol eye drops = C07 ... S01ED)
    m = m[~m.drug_norm.str.contains("ophth|eye|drop|cream|gel|patch", regex=True)]
    con.register("m_df", m)
    con.sql("CREATE OR REPLACE TABLE dw.map_drug_class AS SELECT * FROM m_df")
    con.unregister("m_df")
    print(f"  mapped {m.drug_norm.nunique()} drug strings to "
          f"{m.drug_class.nunique()} target classes ({source or 'keyword fallback'})")
    return m
