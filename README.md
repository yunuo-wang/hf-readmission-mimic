# Predicting 30-Day Readmission After Heart Failure Hospitalization
### Integrating MIMIC-IV, ICD-9/ICD-10, LOINC and RxNorm/ATC with SQL and Python

BIS 638 — Clinical Database and Ontology · Final Project

---

## 1. Motivation

Heart failure (HF) is the most common cause of hospitalization in adults over 65.
About 1 in 5 HF patients is readmitted within 30 days, and the CMS Hospital
Readmissions Reduction Program financially penalizes hospitals with high HF
readmission rates. To study readmission, we have to **integrate** data that sits
in several tables and uses several coding systems:

| Information | Source in MIMIC-IV | Standard / ontology used |
|---|---|---|
| Diagnoses (HF and comorbidities) | `hosp.diagnoses_icd` | ICD-9-CM **and** ICD-10-CM (both appear in MIMIC-IV) |
| Laboratory results | `hosp.labevents` (local `itemid`) | LOINC |
| Medications | `hosp.prescriptions` (free-text drug names) | RxNorm → WHO ATC classes (NLM RxNav / RxClass API) |
| Admissions / readmissions | `hosp.admissions`, `icu.icustays` | — |

## 2. Research questions

1. **Descriptive:** What is the 30-day all-cause readmission rate after an HF
   hospitalization in MIMIC-IV, and how is it distributed over the 30 days after discharge?
2. **Analytic:** Which patient factors (demographics, prior use of care,
   comorbidities, discharge labs, discharge medications) are independently associated
   with 30-day readmission?
3. **Predictive:** How well does a simple, interpretable model built from the integrated data
   discriminate readmitted from non-readmitted patients (cross-validated AUC)?
4. **Temporal:** How have readmission rates and guideline-directed medical therapy
   (GDMT) use changed from 2008 to 2022?

## 3. How the project maps to the course topics

| Lecture topic | Where it is used in the project |
|---|---|
| SQL & relational databases (9/3, 9/10) | Entire pipeline is SQL (DuckDB): joins, CTEs, `PIVOT`, `QUALIFY` |
| Windows, partitions, pivot tables (9/10) | `LEAD()` for the next admission; `RANGE` window for prior-year admissions; `ROW_NUMBER()` for first/last labs; running `SUM() OVER` for the cumulative curve; `PIVOT` for comorbidity and medication flags |
| MIMIC repository + Python (9/17) | MIMIC-IV v3.1 `hosp` and `icu` modules; Python orchestration and statistics |
| Relational database design (9/24) | Layered design: staging → vocabulary → cohort → star-schema data mart |
| SQL analytics with time series (10/1) | Cumulative readmission by day; creatinine trajectory by hospital day; trends across 2008–2022 |
| EHR & clinical data warehousing (10/8) | Star schema with `fact_index_admission`, `fact_diagnosis`, `fact_lab`, `fact_medication` plus dimensions |
| Clinical data standards (10/15) | ICD-9-CM ↔ ICD-10-CM value sets; LOINC-coded labs; RxNorm drug identifiers |
| Ontologies & biomedical ontologies (11/5, 11/12) | ICD hierarchy (prefix → descendant codes); RxNorm ingredient relations; ATC class hierarchy |
| Ontology applications (11/19) | Ontology-driven drug classification of thousands of free-text drug strings via the RxNav API |

## 4. Study design

* **Data:** MIMIC-IV v3.1 (Beth Israel Deaconess Medical Center, 2008–2022).
* **Cohort:**
  * Hospital admissions whose **principal diagnosis** (`seq_num = 1`) is HF:
    ICD-9 `428.x`, `402.x1`, `404.x1/x3`; ICD-10 `I50.x`, `I11.0`, `I13.0`, `I13.2`.
  * Excluded: in-hospital death, discharge to hospice, discharge against medical advice, age < 18.
  * Kept: the **first** eligible HF admission per patient (index admission), so each patient appears once.
* **Primary outcome:** any hospital admission within 30 days of index discharge (`LEAD(admittime)`).
* **Secondary outcome:** death within 30 days (`patients.dod`).
* **Predictors**
  * Demographics: age, sex, insurance.
  * Utilization: admissions in the prior 365 days, length of stay > 7 days, ICU stay, discharge to SNF/rehab.
  * Comorbidities (ICD-9/10 value sets): diabetes, CKD, chronic pulmonary disease, AF, ischemic heart disease, anemia.
  * Last labs before discharge (LOINC): creatinine > 1.5, sodium < 135, BUN > 30, hemoglobin < 10.
  * Discharge medications (ATC via RxNorm), defined as orders active in the final 24 h:
    loop diuretic (C03C), beta-blocker (C07), ACEi/ARB/ARNI (C09), MRA (C03DA), SGLT2i (A10BK).
* **Statistics:** Table 1 (Mann-Whitney U / χ²), multivariable logistic regression
  (adjusted ORs), 5-fold cross-validated AUC with bootstrap 95% CI.

## 5. Architecture

```
 MIMIC-IV CSV.gz files                       External knowledge
 (hosp, icu)                                 NLM RxNav (RxNorm + RxClass/ATC)
       │                                              │
       ▼                                              ▼
┌──────────────┐   ┌───────────────────┐   ┌────────────────────────┐
│ stg.*        │──▶│ vocab.*           │◀──│ seeds/*.csv            │
│ staging      │   │ concept_map (ICD) │   │ ICD value sets, LOINC, │
│ (01_staging) │   │ concept_code      │   │ ATC targets, RxNav     │
└──────┬───────┘   │ lab_concepts      │   │ cache                  │
       │           └─────────┬─────────┘   └────────────────────────┘
       ▼                     ▼
┌─────────────────────────────────────┐
│ cohort.* (02_cohort)                │  LEAD(), RANGE window, QUALIFY
│ adm_sequence → hf_admissions →      │
│ index_adm  (+ readmit_30d)          │
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│ dw.* star schema (03/04)            │
│ dim_patient  dim_concept  dim_lab   │
│ dim_drug_class   map_drug_class     │
│ fact_diagnosis  fact_lab            │
│ fact_medication fact_index_admission│
└──────────────┬──────────────────────┘
               ▼
   05_queries.sql (SQL analytics)  ──▶  outputs/tables/*.csv
   src/analysis.py (Python stats)  ──▶  outputs/figures/*.png
```

## 6. Repository layout

```
run_all.py                 one command runs everything
requirements.txt
sql/
  01_staging.sql           source tables + vocabulary (ICD, LOINC, ATC)
  02_cohort.sql            HF cohort, readmission outcome (window functions)
  03_warehouse.sql         star-schema facts/dimensions
  04_analytic.sql          medication fact + one-row-per-patient analytic table (PIVOT)
  05_queries.sql           12 named analytic queries -> CSV
src/
  config.py                paths (override with MIMIC_DIR / HF_DB_PATH env vars)
  pipeline.py              executes the SQL layers in order
  ontology_rxnav.py        RxNorm/ATC mapping through NLM RxNav (+ cache + offline fallback)
  analysis.py              Table 1, logistic regression, AUC, figures
seeds/
  concept_map.csv          ICD-9/ICD-10 value sets for each clinical concept
  lab_concepts.csv         MIMIC itemid -> LOINC
  drug_class_targets.csv   target drug classes as ATC prefixes
  drug_class_fallback.csv  offline keyword fallback
  rxnav_atc_cache.csv      cached RxNav responses (created on first run)
outputs/tables, outputs/figures
report/final_report.md     write-up with results
```

## 7. How to run

```bash
pip install -r requirements.txt
# MIMIC-IV v3.1 CSVs expected at ~/data/mimic/physionet.org/files/mimiciv/3.1
# (or: export MIMIC_DIR=/path/to/mimiciv/3.1)
python run_all.py
```

Runtime is about 5–10 minutes on a laptop, mostly the single filtered scan of `labevents.csv.gz`.
The DuckDB database is written to `~/data/mimic/hf_readmission.duckdb`, outside the
shared folder, because it contains MIMIC data and must not be redistributed under the PhysioNet DUA.
Open the database in any DuckDB client to explore the `stg`, `vocab`, `cohort` and `dw` schemas.

> **Data use:** only aggregate results are written to `outputs/`. The patient-level analytic
> table (`hf_analytic_dataset.csv`) is written next to the DuckDB file and must not be shared
> outside credentialed PhysioNet users.
