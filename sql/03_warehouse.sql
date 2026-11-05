-- =====================================================================
-- 03_warehouse.sql : Star-schema clinical data mart for the HF cohort
--   dim_patient, dim_concept, dim_lab, dim_drug_class
--   fact_index_admission (grain: 1 row per index admission)
--   fact_diagnosis, fact_lab, fact_medication
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS dw;

CREATE OR REPLACE TABLE dw.dim_patient AS
SELECT DISTINCT p.subject_id, p.gender, p.anchor_age, p.anchor_year_group, p.dod
FROM stg.patients p JOIN cohort.index_adm i USING (subject_id);

CREATE OR REPLACE TABLE dw.dim_concept AS
SELECT DISTINCT concept_id, concept_name FROM vocab.concept_map;

CREATE OR REPLACE TABLE dw.dim_lab AS SELECT * FROM vocab.lab_concepts;

CREATE OR REPLACE TABLE dw.dim_drug_class AS SELECT * FROM vocab.drug_class_targets;

-- Fact: all diagnoses on index admission, standardised to concepts
CREATE OR REPLACE TABLE dw.fact_diagnosis AS
SELECT i.hadm_id, i.subject_id, dx.seq_num, dx.icd_version, dx.icd_code, cc.concept_id
FROM cohort.index_adm i
JOIN stg.diagnoses_icd dx USING (hadm_id)
LEFT JOIN vocab.concept_code cc
       ON cc.icd_code = dx.icd_code AND cc.icd_version = dx.icd_version;

-- Fact: labs during index admission (filtered scan of the 2.6 GB labevents file)
CREATE OR REPLACE TABLE dw.fact_lab AS
SELECT i.hadm_id, i.subject_id, l.lab_name, l.loinc_code, le.charttime, le.valuenum,
       CAST(FLOOR(DATE_DIFF('hour', i.admittime, le.charttime) / 24.0) AS INTEGER) AS hosp_day  -- day 0 = first 24 h
FROM stg.labevents le
JOIN vocab.lab_concepts l ON l.itemid = le.itemid
JOIN cohort.index_adm i
  ON i.subject_id = le.subject_id
 AND le.charttime BETWEEN i.admittime AND i.dischtime
WHERE le.valuenum IS NOT NULL;

-- Raw prescriptions active in the final 24 h before discharge
-- (proxy for discharge medications). Drug classes are attached in Python
-- (RxNorm/RxClass ontology lookup) -> dw.map_drug_class, then joined.
CREATE OR REPLACE TABLE dw.stg_discharge_rx AS
SELECT i.hadm_id, i.subject_id, rx.drug, LOWER(TRIM(rx.drug)) AS drug_norm, rx.route,
       rx.starttime, rx.stoptime
FROM cohort.index_adm i
JOIN stg.prescriptions rx USING (hadm_id)
WHERE rx.starttime <= i.dischtime
  AND COALESCE(rx.stoptime, i.dischtime) >= i.dischtime - INTERVAL 24 HOUR;
