-- =====================================================================
-- 05_queries.sql : Descriptive / time-series SQL analytics
-- Each statement is preceded by "-- name: <output file>" and saved as CSV.
-- =====================================================================

-- name: q1_cohort_flow
SELECT * FROM cohort.flow ORDER BY step;

-- name: q2_overall_outcomes
SELECT COUNT(*)                                   AS n_patients,
       SUM(readmit_30d)                           AS n_readmit_30d,
       ROUND(100.0*AVG(readmit_30d),1)            AS pct_readmit_30d,
       ROUND(100.0*AVG(death_30d),1)              AS pct_death_30d,
       ROUND(100.0*AVG(GREATEST(readmit_30d,death_30d)),1) AS pct_readmit_or_death_30d,
       ROUND(MEDIAN(los_days),1)                  AS median_los_days,
       ROUND(AVG(age),1)                          AS mean_age
FROM dw.fact_index_admission;

-- name: q3_cumulative_readmission_by_day
-- Time series: cumulative % readmitted by day after discharge (running SUM window)
WITH days AS (SELECT range AS day FROM range(0, 31)),
     ev   AS (SELECT CAST(CEIL(days_to_readmit) AS INTEGER) AS day, COUNT(*) AS n
              FROM dw.fact_index_admission
              WHERE readmit_30d = 1 GROUP BY 1),
     tot  AS (SELECT COUNT(*) AS n FROM dw.fact_index_admission)
SELECT d.day, COALESCE(ev.n,0) AS new_readmissions,
       ROUND(100.0 * SUM(COALESCE(ev.n,0)) OVER (ORDER BY d.day) / tot.n, 2) AS cumulative_pct
FROM days d LEFT JOIN ev USING (day) CROSS JOIN tot ORDER BY d.day;

-- name: q4_readmission_trend_by_period
-- Time series across (approximate, de-shifted) calendar periods
SELECT CASE WHEN approx_real_year < 2011 THEN '2008-2010'
            WHEN approx_real_year < 2014 THEN '2011-2013'
            WHEN approx_real_year < 2017 THEN '2014-2016'
            WHEN approx_real_year < 2020 THEN '2017-2019'
            ELSE '2020-2022' END                  AS period,
       COUNT(*)                                   AS n,
       ROUND(100.0*AVG(readmit_30d),1)            AS pct_readmit_30d,
       ROUND(100.0*AVG(rx_beta_blocker::INT),1)   AS pct_beta_blocker,
       ROUND(100.0*AVG(rx_raas_inhibitor::INT),1) AS pct_raas_inhibitor,
       ROUND(100.0*AVG(rx_mra::INT),1)            AS pct_mra,
       ROUND(100.0*AVG(rx_sglt2i::INT),1)         AS pct_sglt2i
FROM dw.fact_index_admission GROUP BY 1 ORDER BY 1;

-- name: q5_icd_version_mix
SELECT icd_version, COUNT(*) AS n, ROUND(100.0*AVG(readmit_30d),1) AS pct_readmit_30d
FROM dw.fact_index_admission GROUP BY 1 ORDER BY 1;

-- name: q6_top_hf_codes
SELECT dx.icd_version, dx.icd_code, d.long_title, COUNT(*) AS n
FROM dw.fact_diagnosis dx
JOIN stg.d_icd_diagnoses d USING (icd_version, icd_code)
WHERE dx.seq_num = 1
GROUP BY ALL ORDER BY n DESC LIMIT 15;

-- name: q7_readmission_by_prior_admissions
SELECT CASE WHEN prior_adm_365d = 0 THEN '0'
            WHEN prior_adm_365d = 1 THEN '1'
            WHEN prior_adm_365d = 2 THEN '2'
            ELSE '3+' END AS prior_admissions_365d,
       COUNT(*) AS n, ROUND(100.0*AVG(readmit_30d),1) AS pct_readmit_30d
FROM dw.fact_index_admission GROUP BY 1 ORDER BY 1;

-- name: q8_readmission_by_comorbidity_count
SELECT (dm::INT + ckd::INT + copd::INT + af::INT + ihd::INT + anemia::INT + obesity::INT) AS n_comorbidities,
       COUNT(*) AS n, ROUND(100.0*AVG(readmit_30d),1) AS pct_readmit_30d
FROM dw.fact_index_admission GROUP BY 1 ORDER BY 1;

-- name: q9_creatinine_trajectory
-- Lab time series: mean creatinine by hospital day, readmitted vs not
WITH daily AS (
    SELECT f.hadm_id, f.hosp_day, AVG(f.valuenum) AS creat
    FROM dw.fact_lab f WHERE f.lab_name = 'creatinine' AND f.hosp_day BETWEEN 0 AND 7
    GROUP BY 1,2)
SELECT d.hosp_day, a.readmit_30d, COUNT(*) AS n_patients,
       ROUND(AVG(d.creat),3) AS mean_creatinine,
       ROUND(STDDEV(d.creat)/SQRT(COUNT(*)),3) AS se
FROM daily d JOIN dw.fact_index_admission a USING (hadm_id)
GROUP BY 1,2 ORDER BY 1,2;

-- name: q10_readmission_by_discharge_location
SELECT discharge_location, COUNT(*) AS n, ROUND(100.0*AVG(readmit_30d),1) AS pct_readmit_30d
FROM dw.fact_index_admission GROUP BY 1 HAVING COUNT(*) >= 50 ORDER BY n DESC;

-- name: q11_drug_class_mapping_summary
SELECT m.drug_class, m.source, COUNT(DISTINCT m.drug_norm) AS n_drug_strings,
       STRING_AGG(DISTINCT m.drug_norm, '; ' ORDER BY m.drug_norm) AS examples
FROM dw.map_drug_class m GROUP BY 1,2 ORDER BY 1,2;

-- name: q12_lab_loinc_coverage
SELECT l.lab_name, l.loinc_code, COUNT(DISTINCT f.hadm_id) AS n_admissions_with_value,
       ROUND(100.0*COUNT(DISTINCT f.hadm_id)/(SELECT COUNT(*) FROM dw.fact_index_admission),1) AS pct_coverage
FROM dw.dim_lab l LEFT JOIN dw.fact_lab f USING (lab_name)
GROUP BY 1,2 ORDER BY 1;
