-- =====================================================================
-- 01_staging.sql  : Staging layer (raw MIMIC-IV source tables)
-- {MIMIC} and {SEEDS} are replaced by run_pipeline.py at run time.
-- Small tables are loaded; the two very large files (labevents, prescriptions)
-- stay as views that read the compressed CSVs directly (no duplication).
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS stg;

CREATE OR REPLACE TABLE stg.patients        AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/patients.csv.gz');
CREATE OR REPLACE TABLE stg.admissions      AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/admissions.csv.gz');
CREATE OR REPLACE TABLE stg.diagnoses_icd   AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/diagnoses_icd.csv.gz', types={'icd_code':'VARCHAR'});
CREATE OR REPLACE TABLE stg.d_icd_diagnoses AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/d_icd_diagnoses.csv.gz', types={'icd_code':'VARCHAR'});
CREATE OR REPLACE TABLE stg.d_labitems      AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/d_labitems.csv.gz');
CREATE OR REPLACE VIEW stg.labevents       AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/labevents.csv.gz', types={'value':'VARCHAR','comments':'VARCHAR'});
CREATE OR REPLACE VIEW stg.prescriptions   AS SELECT * FROM read_csv_auto('{MIMIC}/hosp/prescriptions.csv.gz', types={'ndc':'VARCHAR','gsn':'VARCHAR'});
CREATE OR REPLACE TABLE stg.icustays        AS SELECT * FROM read_csv_auto('{MIMIC}/icu/icustays.csv.gz');

-- ---------------------------------------------------------------------
-- Vocabulary / knowledge layer (data standards + ontology mappings)
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS vocab;

-- ICD-9-CM / ICD-10-CM value sets for each clinical concept
CREATE OR REPLACE TABLE vocab.concept_map AS
SELECT concept_id, concept_name, CAST(icd_version AS INTEGER) AS icd_version,
       CAST(code_prefix AS VARCHAR) AS code_prefix, note
FROM read_csv_auto('{SEEDS}/concept_map.csv', types={'code_prefix':'VARCHAR'});

-- Lab items mapped to LOINC (MIMIC itemid -> standard LOINC code)
CREATE OR REPLACE TABLE vocab.lab_concepts AS
SELECT * FROM read_csv_auto('{SEEDS}/lab_concepts.csv', types={'loinc_code':'VARCHAR'});

-- Target drug classes defined by ATC (WHO Anatomical Therapeutic Chemical) prefixes
CREATE OR REPLACE TABLE vocab.drug_class_targets AS
SELECT * FROM read_csv_auto('{SEEDS}/drug_class_targets.csv');

-- Expand value sets into the actual codes present in the ICD dictionary.
-- This is the "ontology/hierarchy" step: a prefix such as I50 selects every
-- descendant code (I501, I5021, I5023, ...) in the ICD-10-CM hierarchy.
CREATE OR REPLACE TABLE vocab.concept_code AS
SELECT DISTINCT m.concept_id, m.concept_name, d.icd_version, d.icd_code, d.long_title
FROM vocab.concept_map m
JOIN stg.d_icd_diagnoses d
  ON d.icd_version = m.icd_version
 AND d.icd_code LIKE m.code_prefix || '%';
