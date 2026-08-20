#!/usr/bin/env python3
"""Arm 1 -- criterion test of the core score against reported breaches (CSBS 2023-2025).

Reads the three recent Cyber Security Breaches Survey waves through csbs_common.py, builds the
core (security hygiene + incident readiness) score, and fits the pre-registered specification.

Primary: weighted GLM (Binomial, freq_weights = normalised survey weights) of breach
(Cybercrime_all, among those asked) on core-score z + size + sector. Robustness: the same
specification unweighted. Reported per wave: n business, n asked, n complete-case, outcome rate,
power (Hsieh et al. 1998), odds ratio per SD with 95% CI, rank-based AUC, and missingness counts.

Size and sector controls (sizeb_comb2, sector_comb2 as factors) are in the primary model because
the pre-registered specification requires them, not because they improved it.

The headline result is negative, and is reported as such: a higher posture score is associated
with MORE reported breaches, which the paper reads as a detection-and-reporting artefact rather
than as evidence that security controls cause incidents. Arm 2 is the test that can separate the
two; this one cannot.

Output: analysis/results/arm1_cross_sectional.json
"""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("p0", HERE / "csbs_common.py")
p0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p0)

OUT = HERE / "results"


def run_spec(d, weighted, label):
    """GLM Binomial: y ~ score_z + C(size) + C(sector), optional freq_weights."""
    X = pd.DataFrame({"score_z": (d["score"] - d["score"].mean()) / d["score"].std()})
    X["const"] = 1.0
    X = X.join(pd.get_dummies(d["size"], prefix="sz", drop_first=True, dtype=float))
    X = X.join(pd.get_dummies(d["sector"], prefix="se", drop_first=True, dtype=float))
    w = None
    if weighted:
        n = len(d)
        w = d["weight"] / d["weight"].sum() * n
    try:
        m = sm.GLM(d["y"], X, family=sm.families.Binomial(), freq_weights=w).fit()
        coef = float(m.params["score_z"])
        se = float(m.bse["score_z"])
        lo, hi = coef - 1.96 * se, coef + 1.96 * se
        return {"label": label, "n": int(len(d)), "or_per_sd": float(np.exp(coef)),
                "ci95": [float(np.exp(lo)), float(np.exp(hi))], "p": float(m.pvalues["score_z"]),
                "auc": p0.auc(d["y"], d["score"])}
    except Exception as e:
        return {"label": label, "n": int(len(d)), "error": str(e)}


def main():
    results = {"preregistered_run": True, "extends": "csbs_common.py", "waves": {}}
    for label in ["2025", "2024", "2023"]:
        full, biz = p0.load_wave(label)
        items, score = p0.build_core_score(biz)
        out = biz["Cybercrime_all"].astype(str)
        asked = ~out.isin({"Not asked", "nan"})
        y = (out == "Yes").astype(float)
        y[~asked] = np.nan
        size_col = "sizeb_comb2" if "sizeb_comb2" in biz.columns else "sizeb"
        d = pd.DataFrame({
            "score": score, "y": y, "weight": biz["weight"].astype(float),
            "size": biz[size_col].astype(str),
            "sector": (biz["sector_comb2"].astype(str) if "sector_comb2" in biz.columns
                       else pd.Series("NA", index=biz.index)),
        })
        # Detection-paradox diagnostic (the manuscript headline "37.5% vs 18.3%").
        # Same definition as csbs_common.py: unweighted breach
        # rate by policy_comb, on this wave's complete-case frame. Descriptive only —
        # not a specification change; waves without a policy variable report nothing.
        if "policy_comb" in biz.columns:
            d["has_policy"] = biz["policy_comb"].astype(str).eq("Yes")
        n_biz = int(len(d))
        n_asked = int(asked.sum())
        n_complete = int(len(d.dropna(subset=["score", "y", "weight", "size", "sector"])))
        d = d.dropna(subset=["score", "y", "weight", "size", "sector"])
        d["sector"] = d["sector"].replace({"NA": "Other"})
        p_out = float(d["y"].mean()) if len(d) else np.nan
        n_req_13, or_detect = p0.hsieh_power_n(len(d), p_out, 1.3) if len(d) and 0 < p_out < 1 else (np.nan, np.nan)
        results["waves"][label] = {
            "n_business": n_biz, "n_asked": n_asked, "n_complete_case": n_complete,
            "outcome_rate": p_out,
            "missingness": {"size_sector_dropped": n_asked - n_complete,
                            "not_asked": int((~asked).sum())},
            "power_detectable_or_per_sd_80pct": or_detect, "n_required_for_or13": n_req_13,
            "weighted_full_controls": run_spec(d, weighted=True, label=f"weighted+controls {label}"),
            "unweighted_full_controls": run_spec(d, weighted=False, label=f"unweighted+controls {label}"),
        }
        if "has_policy" in d.columns:
            rates = d.groupby("has_policy")["y"].mean().to_dict()
            results["waves"][label]["detection_diagnostic"] = {
                "breach_rate_with_policy": {str(k).lower(): float(v) for k, v in rates.items()},
                "n_by_policy": {str(k).lower(): int(v)
                                for k, v in d.groupby("has_policy")["y"].size().to_dict().items()},
                "note": "unweighted, complete-case; policy_comb == 'Yes' vs otherwise",
            }
            print("   policy gap: with={with_p:.4f} without={no_p:.4f}".format(
                with_p=rates.get(True, float("nan")), no_p=rates.get(False, float("nan"))))
        w = results["waves"][label]["weighted_full_controls"]
        u = results["waves"][label]["unweighted_full_controls"]
        print(f"=== {label}: n_biz={n_biz} asked={n_asked} complete={n_complete} rate={p_out:.3f} "
              f"detectable={or_detect:.3f} n_req={n_req_13:.0f}")
        for r in (w, u):
            if "error" in r:
                print(f"   {r['label']}: {r['error']} (n={r['n']})")
            else:
                print(f"   {r['label']}: n={r['n']} OR/SD={r['or_per_sd']:.3f} "
                      f"CI[{r['ci95'][0]:.3f},{r['ci95'][1]:.3f}] p={r['p']:.3f} AUC={r['auc']:.3f}")
    (OUT / "arm1_cross_sectional.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved: {OUT / 'arm1_cross_sectional.json'}")


if __name__ == "__main__":
    main()