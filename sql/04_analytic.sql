-- =====================================================================
-- 04_analytic.sql : medication fact + one-row-per-patient analytic table
-- (run after dw.map_drug_class has been loaded by the ontology step)
-- =====================================================================
CREATE OR REPLACE TABLE dw.fact_medication AS
SELECT DISTINCT r.hadm_id, r.subject_id, m.drug_class
FROM dw.stg_discharge_rx r
JOIN dw.map_drug_class m ON m.drug_norm = r.drug_norm
-- keep systemic routes only (e.g. timolol eye drops share ATC ingredient C07)
WHERE COALESCE(UPPER(r.route),'PO') NOT IN ('OU','OS','OD','BOTH EYES','LEFT EYE','RIGHT EYE',
                                            'OPHTH','TP','TOPICAL','INHALATION','NU','ED');

CREATE OR REPLACE TABLE dw.fact_index_admission AS
WITH comorb AS (
    PIVOT (SELECT DISTINCT hadm_id, concept_id FROM dw.fact_diagnosis
           WHERE concept_id IS NOT NULL AND concept_id <> 'HF')
    ON concept_id IN ('DM','CKD','COPD','AF','IHD','ANEMIA','OBESITY')
    USING COUNT(*) GROUP BY hadm_id
),
last_lab AS (  -- last value before discharge (window function)
    SELECT hadm_id, lab_name, valuenum FROM dw.fact_lab
    QUALIFY ROW_NUMBER() OVER (PARTITION BY hadm_id, lab_name ORDER BY charttime DESC) = 1
),
first_lab AS ( -- first value after admission
    SELECT hadm_id, lab_name, valuenum FROM dw.fact_lab
    QUALIFY ROW_NUMBER() OVER (PARTITION BY hadm_id, lab_name ORDER BY charttime) = 1
),
labs AS (
    SELECT hadm_id,
        MAX(CASE WHEN lab_name='creatinine' THEN valuenum END) AS creat_last,
        MAX(CASE WHEN lab_name='sodium'     THEN valuenum END) AS sodium_last,
        MAX(CASE WHEN lab_name='bun'        THEN valuenum END) AS bun_last,
        MAX(CASE WHEN lab_name='hemoglobin' THEN valuenum END) AS hgb_last,
        MAX(CASE WHEN lab_name='potassium'  THEN valuenum END) AS k_last
    FROM last_lab GROUP BY hadm_id
),
bnp AS (SELECT hadm_id, valuenum AS ntprobnp_first FROM first_lab WHERE lab_name='ntprobnp'),
meds AS (
    PIVOT (SELECT hadm_id, drug_class FROM dw.fact_medication)
    ON drug_class IN ('loop_diuretic','beta_blocker','raas_inhibitor','mra','sglt2i')
    USING COUNT(*) GROUP BY hadm_id
),
icu AS (SELECT DISTINCT hadm_id, 1 AS icu_stay FROM stg.icustays)
SELECT i.subject_id, i.hadm_id, i.gender, i.age, i.anchor_year_group, i.approx_real_year,
       i.icd_version, i.admission_type, i.insurance, i.race, i.discharge_location,
       i.los_days, i.prior_adm_365d, COALESCE(icu.icu_stay,0) AS icu_stay,
       COALESCE(c.DM,0)>0 AS dm, COALESCE(c.CKD,0)>0 AS ckd, COALESCE(c.COPD,0)>0 AS copd,
       COALESCE(c.AF,0)>0 AS af, COALESCE(c.IHD,0)>0 AS ihd, COALESCE(c.ANEMIA,0)>0 AS anemia,
       COALESCE(c.OBESITY,0)>0 AS obesity,
       l.creat_last, l.sodium_last, l.bun_last, l.hgb_last, l.k_last, b.ntprobnp_first,
       COALESCE(m.loop_diuretic,0)>0 AS rx_loop_diuretic,
       COALESCE(m.beta_blocker,0)>0  AS rx_beta_blocker,
       COALESCE(m.raas_inhibitor,0)>0 AS rx_raas_inhibitor,
       COALESCE(m.mra,0)>0           AS rx_mra,
       COALESCE(m.sglt2i,0)>0        AS rx_sglt2i,
       i.days_to_readmit, i.next_admission_type, i.readmit_30d, i.death_30d
FROM cohort.index_adm i
LEFT JOIN comorb c USING (hadm_id)
LEFT JOIN labs   l USING (hadm_id)
LEFT JOIN bnp    b USING (hadm_id)
LEFT JOIN meds   m USING (hadm_id)
LEFT JOIN icu      USING (hadm_id);
