"""
End-to-end pipeline:
  MIMIC-IV CSVs -> DuckDB (SQL staging, vocabulary, cohort, star schema)
  -> RxNorm/ATC ontology mapping -> SQL analytics -> Python statistics & figures

Usage:  python run_all.py
"""
import time

from src import analysis, pipeline


def main():
    t0 = time.time()
    con, q = pipeline.build()
    print("[7] Statistics + figures")
    r = analysis.run(con, q)
    o = q["q2_overall_outcomes"].iloc[0]
    print("\n================ KEY RESULTS ================")
    print(q["q1_cohort_flow"].to_string(index=False))
    print(f"\nIndex HF patients: {int(o.n_patients):,}")
    print(f"30-day readmission: {o.pct_readmit_30d}%  | 30-day death: {o.pct_death_30d}%")
    print(f"CV AUC full model: {r['auc']['auc_full']:.3f} "
          f"(95% CI {r['auc']['auc_full_ci'][0]:.3f}-{r['auc']['auc_full_ci'][1]:.3f}); "
          f"age+sex only: {r['auc']['auc_base']:.3f}")
    print("\nAdjusted odds ratios:")
    print(r["or_table"][["label", "odds_ratio", "ci_low", "ci_high", "p_value"]]
          .round(3).to_string(index=False))
    print(f"\nTotal runtime: {(time.time() - t0) / 60:.1f} min")
    con.close()


if __name__ == "__main__":
    main()
