"""Statistical analysis + figures (Python layer)."""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import statsmodels.api as sm
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import DB_PATH, OUT_FIGS, OUT_TABLES

# Reference palette (validated categorical slots 1-3) + text/grid tokens
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 200, "font.size": 10,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False,
})

LABELS = {
    "age_per10": "Age (per 10 years)", "female": "Female sex",
    "prior_adm_1": "1 prior admission (past year)", "prior_adm_2plus": "2+ prior admissions (past year)",
    "los_gt7": "Length of stay > 7 days", "icu_stay": "ICU stay during admission",
    "dm": "Diabetes", "ckd": "Chronic kidney disease", "copd": "Chronic pulmonary disease",
    "af": "Atrial fibrillation/flutter", "ihd": "Ischemic heart disease", "anemia": "Anemia (diagnosis)",
    "creat_high": "Creatinine > 1.5 mg/dL", "sodium_low": "Sodium < 135 mEq/L",
    "bun_high": "BUN > 30 mg/dL", "hgb_low": "Hemoglobin < 10 g/dL",
    "rx_beta_blocker": "Beta-blocker at discharge", "rx_raas_inhibitor": "ACEi/ARB/ARNI at discharge",
    "rx_mra": "MRA at discharge", "rx_sglt2i": "SGLT2 inhibitor at discharge",
    "rx_loop_diuretic": "Loop diuretic at discharge",
    "dc_snf": "Discharged to SNF / rehab", "medicaid": "Medicaid insurance",
}


def prepare(df):
    d = pd.DataFrame(index=df.index)
    d["age_per10"] = df.age / 10
    d["female"] = (df.gender == "F").astype(int)
    d["prior_adm_1"] = (df.prior_adm_365d == 1).astype(int)
    d["prior_adm_2plus"] = (df.prior_adm_365d >= 2).astype(int)
    d["los_gt7"] = (df.los_days > 7).astype(int)
    d["icu_stay"] = df.icu_stay.astype(int)
    for c in ["dm", "ckd", "copd", "af", "ihd", "anemia"]:
        d[c] = df[c].astype(int)
    # abnormal-lab flags (missing = not abnormal)
    d["creat_high"] = (df.creat_last > 1.5).astype(int)
    d["sodium_low"] = (df.sodium_last < 135).astype(int)
    d["bun_high"] = (df.bun_last > 30).astype(int)
    d["hgb_low"] = (df.hgb_last < 10).astype(int)
    for c in ["rx_loop_diuretic", "rx_beta_blocker", "rx_raas_inhibitor", "rx_mra", "rx_sglt2i"]:
        d[c] = df[c].astype(int)
    d["dc_snf"] = df.discharge_location.isin(["SKILLED NURSING FACILITY", "REHAB", "CHRONIC/LONG TERM ACUTE CARE"]).astype(int)
    d["medicaid"] = (df.insurance == "Medicaid").astype(int)
    return d


def table1(df, X):
    rows = []
    y = df.readmit_30d
    def cont(name, s):
        a, b = s[y == 0].dropna(), s[y == 1].dropna()
        p = stats.mannwhitneyu(a, b).pvalue
        rows.append((name, f"{s.median():.1f} [{s.quantile(.25):.1f}-{s.quantile(.75):.1f}]",
                     f"{a.median():.1f} [{a.quantile(.25):.1f}-{a.quantile(.75):.1f}]",
                     f"{b.median():.1f} [{b.quantile(.25):.1f}-{b.quantile(.75):.1f}]", p))
    def binary(name, s):
        p = stats.chi2_contingency(pd.crosstab(s, y))[1] if s.nunique() > 1 else np.nan
        f = lambda v: f"{int(v.sum())} ({100 * v.mean():.1f}%)"
        rows.append((name, f(s), f(s[y == 0]), f(s[y == 1]), p))
    rows.append(("N", str(len(df)), str((y == 0).sum()), str((y == 1).sum()), np.nan))
    cont("Age, years, median [IQR]", df.age)
    cont("Length of stay, days", df.los_days)
    cont("Last creatinine, mg/dL", df.creat_last)
    cont("Last sodium, mEq/L", df.sodium_last)
    cont("Last hemoglobin, g/dL", df.hgb_last)
    cont("First NT-proBNP, pg/mL", df.ntprobnp_first)
    for c in X.columns:
        if c != "age_per10":
            binary(LABELS.get(c, c), X[c])
    t = pd.DataFrame(rows, columns=["Variable", "Overall", "Not readmitted", "Readmitted <=30d", "p_value"])
    t["p_value"] = t.p_value.map(lambda p: "" if pd.isna(p) else ("<0.001" if p < 0.001 else f"{p:.3f}"))
    t.to_csv(OUT_TABLES / "table1_characteristics.csv", index=False)
    return t


def logistic(X, y):
    m = sm.Logit(y, sm.add_constant(X.astype(float))).fit(disp=False)
    ci = m.conf_int()
    res = pd.DataFrame({"variable": X.columns, "label": [LABELS[c] for c in X.columns],
                        "odds_ratio": np.exp(m.params[X.columns]),
                        "ci_low": np.exp(ci.loc[X.columns, 0]), "ci_high": np.exp(ci.loc[X.columns, 1]),
                        "p_value": m.pvalues[X.columns]}).reset_index(drop=True)
    res.round(4).to_csv(OUT_TABLES / "logistic_regression_or.csv", index=False)
    return m, res


def cv_auc(X, y):
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    skf = StratifiedKFold(5, shuffle=True, random_state=638)
    p_full = cross_val_predict(pipe, X, y, cv=skf, method="predict_proba")[:, 1]
    base = ["age_per10", "female"]
    p_base = cross_val_predict(pipe, X[base], y, cv=skf, method="predict_proba")[:, 1]
    # bootstrap CI for the full-model AUC
    rng = np.random.default_rng(638); boots = []
    yv = y.values
    for _ in range(500):
        i = rng.integers(0, len(yv), len(yv))
        if yv[i].min() != yv[i].max():
            boots.append(roc_auc_score(yv[i], p_full[i]))
    out = dict(auc_full=roc_auc_score(y, p_full), auc_full_ci=np.percentile(boots, [2.5, 97.5]),
               auc_base=roc_auc_score(y, p_base), p_full=p_full, p_base=p_base)
    pd.DataFrame([{"model": "Age + sex only", "cv_auc": round(out["auc_base"], 3)},
                  {"model": "Full model (demographics + utilisation + comorbidities + labs + meds)",
                   "cv_auc": round(out["auc_full"], 3),
                   "ci95": f"{out['auc_full_ci'][0]:.3f}-{out['auc_full_ci'][1]:.3f}"}]
                 ).to_csv(OUT_TABLES / "model_auc.csv", index=False)
    return out


# ------------------------------------------------------------------ figures
def _save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT_FIGS / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_cumulative(q):
    d = q["q3_cumulative_readmission_by_day"]
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.plot(d.day, d.cumulative_pct, color=BLUE, lw=2)
    ax.fill_between(d.day, d.cumulative_pct, color=BLUE, alpha=.08, lw=0)
    for day in (7, 14, 30):
        v = d.loc[d.day == day, "cumulative_pct"].iloc[0]
        ax.plot(day, v, "o", ms=6, color=BLUE, mec="white", mew=2)
        ax.annotate(f"Day {day}: {v:.1f}%", (day, v), xytext=(-8, 8), textcoords="offset points",
                    ha="right", color=INK, fontsize=9)
    ax.set_xlim(0, 30.5); ax.set_ylim(0, d.cumulative_pct.max() * 1.2)
    ax.set_xlabel("Days after discharge"); ax.set_ylabel("Cumulative % readmitted")
    ax.set_title("Cumulative 30-day all-cause readmission after HF discharge")
    _save(fig, "fig1_cumulative_readmission.png")


def fig_prior(q):
    d = q["q7_readmission_by_prior_admissions"]
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    ax.bar(d.prior_admissions_365d, d.pct_readmit_30d, color=BLUE, width=.6)
    for x, v, n in zip(d.prior_admissions_365d, d.pct_readmit_30d, d.n):
        ax.text(x, v + .5, f"{v:.1f}%\n(n={n:,})", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_ylim(0, d.pct_readmit_30d.max() * 1.25)
    ax.set_xlabel("Hospital admissions in the prior 365 days"); ax.set_ylabel("30-day readmission (%)")
    ax.set_title("Readmission risk rises with prior utilisation")
    ax.grid(axis="x", visible=False)
    _save(fig, "fig2_readmission_by_prior_admissions.png")


def fig_forest(res):
    r = res.sort_values("odds_ratio").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    sig = r.p_value < 0.05
    y = np.arange(len(r))
    ax.hlines(y, r.ci_low, r.ci_high, color=np.where(sig, BLUE, "#9a9893"), lw=2)
    ax.plot(r.odds_ratio[sig], y[sig], "o", color=BLUE, ms=7, mec="white", mew=1.5, label="p < 0.05")
    ax.plot(r.odds_ratio[~sig], y[~sig], "o", color="#9a9893", ms=7, mec="white", mew=1.5, label="p ≥ 0.05")
    ax.axvline(1, color=INK2, lw=1, ls="--")
    ax.set_yticks(y); ax.set_yticklabels(r.label)
    ax.set_xscale("log"); ax.set_xlim(0.3, 3)
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xticks([0.33, 0.5, 0.75, 1, 1.5, 2, 3]); ax.set_xticklabels(["0.33", "0.5", "0.75", "1", "1.5", "2", "3"])
    ax.set_xlabel("Adjusted odds ratio (95% CI), log scale")
    ax.set_title("Predictors of 30-day readmission (multivariable logistic regression)")
    ax.legend(loc="lower right"); ax.grid(axis="y", visible=False)
    _save(fig, "fig3_forest_plot.png")


def fig_roc(y, out):
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    for p, col, lab in [(out["p_full"], BLUE, f"Full model  AUC {out['auc_full']:.3f}"),
                        (out["p_base"], ORANGE, f"Age + sex   AUC {out['auc_base']:.3f}")]:
        fpr, tpr, _ = roc_curve(y, p)
        ax.plot(fpr, tpr, color=col, lw=2, label=lab)
    ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--")
    ax.set_xlabel("1 - Specificity"); ax.set_ylabel("Sensitivity")
    ax.set_title("5-fold cross-validated ROC"); ax.legend(loc="lower right")
    ax.set_aspect("equal")
    _save(fig, "fig4_roc.png")


def fig_creatinine(q):
    d = q["q9_creatinine_trajectory"]
    fig, ax = plt.subplots(figsize=(6, 3.8))
    last = d[d.hosp_day == d.hosp_day.max()].set_index("readmit_30d").mean_creatinine
    for flag, col, lab in [(0, BLUE, "Not readmitted"), (1, ORANGE, "Readmitted ≤30 d")]:
        s = d[d.readmit_30d == flag]
        dy = 8 if last.get(flag, 0) >= last.max() else -8
        ax.plot(s.hosp_day, s.mean_creatinine, color=col, lw=2, marker="o", ms=5, mec="white", mew=1.5, label=lab)
        ax.fill_between(s.hosp_day, s.mean_creatinine - 1.96 * s.se, s.mean_creatinine + 1.96 * s.se,
                        color=col, alpha=.12, lw=0)
        ax.annotate(lab, (s.hosp_day.iloc[-1], s.mean_creatinine.iloc[-1]), xytext=(6, dy),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_xlim(-0.2, 9.5); ax.set_xticks(range(8))
    ax.set_xlabel("Hospital day (0 = first 24 h)"); ax.set_ylabel("Mean serum creatinine (mg/dL)")
    ax.set_title("Creatinine trajectory during the index admission")
    ax.legend(loc="upper left")
    _save(fig, "fig5_creatinine_trajectory.png")


def fig_gdmt_trend(q):
    d = q["q4_readmission_trend_by_period"]
    series = [("pct_beta_blocker", BLUE, "Beta-blocker"), ("pct_raas_inhibitor", ORANGE, "ACEi/ARB/ARNI"),
              ("pct_mra", AQUA, "MRA"), ("pct_sglt2i", "#eda100", "SGLT2i")]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), gridspec_kw={"width_ratios": [1.4, 1]})
    ax = axes[0]
    for c, col, lab in series:
        ax.plot(d.period, d[c], color=col, lw=2, marker="o", ms=5, mec="white", mew=1.5, label=lab)
        ax.annotate(lab, (len(d) - 1, d[c].iloc[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK)
    ax.set_ylabel("% of patients at discharge"); ax.set_ylim(0, 100)
    ax.set_title("HF guideline-directed medication use by period")
    ax.legend(loc="upper left", ncol=2, fontsize=8.5)
    ax.set_xlim(-0.3, len(d) - 0.2 + 0.9)
    ax = axes[1]
    ax.bar(d.period, d.pct_readmit_30d, color=BLUE, width=.6)
    for x, v, n in zip(d.period, d.pct_readmit_30d, d.n):
        ax.text(x, v + .4, f"{v:.1f}%\nn={n:,}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_ylim(0, d.pct_readmit_30d.max() * 1.3)
    ax.set_ylabel("30-day readmission (%)"); ax.set_title("Readmission rate by period")
    ax.grid(axis="x", visible=False)
    for a in axes:
        a.tick_params(axis="x", labelsize=8.5)
    _save(fig, "fig6_trends_by_period.png")


def run(con, q):
    df = con.sql("SELECT * FROM dw.fact_index_admission ORDER BY hadm_id").df()
    # patient-level rows stay next to the DB (outside the shared/iCloud project folder)
    df.to_csv(DB_PATH.parent / "hf_analytic_dataset.csv", index=False)
    X = prepare(df); y = df.readmit_30d.astype(int)
    t1 = table1(df, X)
    model, res = logistic(X, y)
    out = cv_auc(X, y)
    fig_cumulative(q); fig_prior(q); fig_forest(res); fig_roc(y, out)
    fig_creatinine(q); fig_gdmt_trend(q)
    with open(OUT_TABLES / "logistic_model_summary.txt", "w") as f:
        f.write(model.summary2().as_text())
    return dict(df=df, table1=t1, or_table=res, auc=out)
