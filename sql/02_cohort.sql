-- =====================================================================
-- 02_cohort.sql : Heart-failure index admissions + 30-day readmission
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS cohort;

-- Step 1. Every hospital admission with its "next admission" (window LEAD)
--         and the number of admissions in the previous 365 days.
CREATE OR REPLACE TABLE cohort.adm_sequence AS
SELECT a.subject_id, a.hadm_id, a.admittime, a.dischtime, a.deathtime,
       a.admission_type, a.admission_location, a.discharge_location,
       a.insurance, a.race, a.hospital_expire_flag,
       LEAD(a.hadm_id)        OVER w AS next_hadm_id,
       LEAD(a.admittime)      OVER w AS next_admittime,
       LEAD(a.admission_type) OVER w AS next_admission_type,
       ROW_NUMBER()           OVER w AS adm_seq,
       COUNT(*) OVER (PARTITION BY a.subject_id ORDER BY a.admittime
                      RANGE BETWEEN INTERVAL 365 DAY PRECEDING AND INTERVAL 1 SECOND PRECEDING)
                                         AS prior_adm_365d
FROM stg.admissions a
WINDOW w AS (PARTITION BY a.subject_id ORDER BY a.admittime);

-- Step 2. Admissions whose PRINCIPAL diagnosis (seq_num = 1) is heart failure
CREATE OR REPLACE TABLE cohort.hf_admissions AS
SELECT dx.hadm_id, MAX(dx.icd_version) AS icd_version
FROM stg.diagnoses_icd dx
JOIN vocab.concept_code cc
  ON cc.icd_code = dx.icd_code AND cc.icd_version = dx.icd_version
WHERE cc.concept_id = 'HF' AND dx.seq_num = 1
GROUP BY dx.hadm_id;

-- Step 3. Apply inclusion / exclusion criteria and keep the FIRST eligible
--         HF admission per patient (index admission).
CREATE OR REPLACE TABLE cohort.index_adm AS
WITH candidates AS (
    SELECT s.*, p.gender, p.anchor_age, p.anchor_year, p.anchor_year_group, p.dod,
           p.anchor_age + (YEAR(s.admittime) - p.anchor_year)               AS age,
           -- approximate real-world calendar year (dates are shifted in MIMIC)
           CAST(LEFT(p.anchor_year_group, 4) AS INTEGER)
               + (YEAR(s.admittime) - p.anchor_year)                        AS approx_real_year,
           h.icd_version
    FROM cohort.adm_sequence s
    JOIN cohort.hf_admissions h USING (hadm_id)
    JOIN stg.patients p        USING (subject_id)
    WHERE s.hospital_expire_flag = 0                                   -- alive at discharge
      AND COALESCE(s.discharge_location,'') NOT IN ('HOSPICE','AGAINST ADVICE','DIED')
      AND p.anchor_age + (YEAR(s.admittime) - p.anchor_year) >= 18
)
SELECT *,
       DATE_DIFF('hour', admittime, dischtime) / 24.0                         AS los_days,
       DATE_DIFF('hour', dischtime, next_admittime) / 24.0                    AS days_to_readmit,
       CASE WHEN next_admittime IS NOT NULL
             AND next_admittime <= dischtime + INTERVAL 30 DAY THEN 1 ELSE 0 END AS readmit_30d,
       CASE WHEN dod IS NOT NULL
             AND dod <= CAST(dischtime AS DATE) + INTERVAL 30 DAY THEN 1 ELSE 0 END AS death_30d
FROM candidates
QUALIFY ROW_NUMBER() OVER (PARTITION BY subject_id ORDER BY admittime) = 1;

-- Cohort flow (for the CONSORT-style diagram in the report)
CREATE OR REPLACE TABLE cohort.flow AS
SELECT 1 AS step, 'All MIMIC-IV hospital admissions' AS description,
       (SELECT COUNT(*) FROM stg.admissions) AS n
UNION ALL SELECT 2, 'Admissions with principal diagnosis of heart failure',
       (SELECT COUNT(*) FROM cohort.hf_admissions)
UNION ALL SELECT 3, 'Patients with >=1 HF admission',
       (SELECT COUNT(DISTINCT a.subject_id) FROM cohort.hf_admissions h JOIN stg.admissions a USING(hadm_id))
UNION ALL SELECT 4, 'Index admissions after exclusions (alive, not hospice/AMA, adult; first per patient)',
       (SELECT COUNT(*) FROM cohort.index_adm);
