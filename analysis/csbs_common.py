#!/usr/bin/env python3
"""Shared CSBS data layer and statistics helpers for the criterion-validity test.

arm1_cross_sectional.py imports this module for wave loading, item risk-coding, the core score,
AUC, KR-20 reliability and the power calculation; running it directly executes the earlier
bivariate specification, retained because arm1 extends rather than replaces it.

Implements the pre-committed analysis:
  (i)   primary: weighted logistic of breach (Cybercrime_all, among asked) on the
        core-dimension score (security hygiene + incident readiness), size/sector controls
  (ii)  power analysis at 80% (Hsieh et al., 1998, logistic with continuous predictor):
        detectable OR per SD for each wave's business subsample
  (iii) minimum-effect gate: OR per SD >= max(1.3, detectable at 80% power), 95% CI excl 1
  (iv)  effect report: AUC (rank-based) + calibration slope
  (v)   robustness: unweighted model; per-wave fits (2023/2024/2025)
  (vi)  missingness: complete-case among asked; counts reported
  reliability: KR-20 / standardized alpha + item-total correlations on the mapped core items

NOTE: the item -> variable mapping below is the provisional one. The mapping the paper reports
is the one produced by the full coverage audit in instrument_validation.py; the numbers the paper
reports come from arm1_cross_sectional.py, not from this module's __main__.

Output (direct execution only): analysis/results/csbs_common.json
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WAVES = {
    "2025": "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta",
    "2024": "UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta",
    "2023": "UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta",
}


def load_wave(label):
    df = pd.read_stata(DATA / WAVES[label], convert_categoricals=True)
    # business subsample: size variable label not in not-asked set
    size_col = "sizeb_comb2" if "sizeb_comb2" in df.columns else "sizeb"
    na_labels = {"Not asked", "Not applicable", "Don't know", "Refused", "n/a"}
    biz = df[~df[size_col].astype(str).isin(na_labels)].copy()
    biz["size_business"] = df.loc[biz.index, size_col].astype(str)
    return df, biz


def risk_item(df, col, risk_vals=None, invert=False):
    """1 = risk present, NaN = not asked/missing. risk_vals: labels counted as risk."""
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    s = df[col].astype(str)
    if risk_vals is None:
        risk_vals = {"No", "Don't have", "Not insured", "No - none"}
    out = pd.Series(np.nan, index=df.index)
    out[s.isin(risk_vals)] = 1
    out[~s.isin(risk_vals) & ~s.isin({"Not asked", "Not applicable", "nan", "Don't know"})] = 0
    return out


def build_core_score(df):
    """Provisional item -> variable mapping; the audited mapping is in instrument_validation.py."""
    items = {}
    # security hygiene
    pol = "policy_comb" if "policy_comb" in df.columns else ("policy1" if "policy1" in df.columns else None)
    items["no_formal_policy"] = risk_item(df, pol, {"No"}) if pol else pd.Series(np.nan, index=df.index)
    items["no_staff_training"] = risk_item(df, "trained", {"No"})
    ins = risk_item(df, "insurex", {"We are not insured against cyber security breaches or attacks",
                                    "No", "Not insured", "We do not have any cyber security insurance"})
    items["no_cyber_insurance"] = ins
    # backups (if present)
    backup_col = next((c for c in df.columns if "backup" in c.lower()), None)
    items["no_backups"] = risk_item(df, backup_col, {"No", "Don't have"}) if backup_col else pd.Series(np.nan, index=df.index)
    # incident readiness (first matching column, if any)
    read_col = next((c for c in df.columns if any(k in c.lower() for k in
                     ("incident_response", "incident plan", "response_plan", "detect"))), None)
    items["no_incident_readiness"] = risk_item(df, read_col, {"No", "Don't have"}) if read_col else pd.Series(np.nan, index=df.index)
    score = pd.concat(items.values(), axis=1).sum(axis=1, min_count=1)
    return items, score


def auc(y, x):
    """Rank-based AUC."""
    pos = x[y == 1]
    neg = x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    n1, n2 = len(pos), len(neg)
    r = stats.rankdata(np.concatenate([pos, neg]))
    return (r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n2)


def reliability(items, score):
    """KR-20 (binary alpha) + item-total correlations on complete cases."""
    mat = pd.DataFrame(items)
    mat = mat.loc[:, mat.notna().any()].dropna()  # drop all-NaN columns first
    if len(mat) < 5 or mat.shape[1] < 2:
        return {}
    k = mat.shape[1]
    p = mat.mean()
    var_total = mat.sum(axis=1).var(ddof=1)
    kr20 = (k / (k - 1)) * (1 - (p * (1 - p)).sum() / var_total)
    itc = {c: float(np.corrcoef(mat[c], mat.sum(axis=1) - mat[c])[0, 1]) for c in mat.columns}
    return {"n_items": k, "n_cases": len(mat), "kr20": float(kr20), "item_total": itc}


def hsieh_power_n(n, p_outcome, or_per_sd, alpha=0.05, power=0.80):
    """Hsieh et al. 1998: n = (z1-a/2 + z1-b)^2 / [p(1-p) b^2], b = log(OR) per SD.
    Returns required n for given OR, and detectable OR for given n."""
    za = stats.norm.ppf(1 - alpha / 2)
    zb = stats.norm.ppf(power)
    b = np.log(or_per_sd)
    n_req = (za + zb) ** 2 / (p_outcome * (1 - p_outcome) * b ** 2)
    b_detect = (za + zb) / np.sqrt(n * p_outcome * (1 - p_outcome))
    return n_req, float(np.exp(b_detect))


def main():
    results = {"waves": {}, "provisional_mapping": True,
               "mapping_note": "provisional map; the audited map is in instrument_validation.py"}
    for label in ["2025", "2024", "2023"]:
        full, biz = load_wave(label)
        items, score = build_core_score(biz)
        out = biz["Cybercrime_all"].astype(str)
        asked = ~out.isin({"Not asked", "nan"})
        y = (out == "Yes").astype(float)
        y[~asked] = np.nan
        d = pd.DataFrame({"score": score, "y": y, "weight": biz["weight"].astype(float),
                          "sector": biz["sector_comb2"].astype(str) if "sector_comb2" in biz.columns else "NA"})
        d = d.dropna(subset=["score", "y", "weight"])
        n = len(d)
        p_out = d["y"].mean()
        n_req_13, or_detect = hsieh_power_n(n, p_out, 1.3)
        # primary: weighted logistic
        X = pd.DataFrame({"score_z": (d["score"] - d["score"].mean()) / d["score"].std()})
        X["const"] = 1.0
        w = d["weight"] / d["weight"].sum() * n
        # detection-paradox diagnostic: breach rate by posture (policy yes/no)
        pol = biz["policy_comb"].astype(str) if "policy_comb" in biz.columns else None
        diag = {}
        if pol is not None:
            has_pol = pol.eq("Yes")
            diag["breach_rate_with_policy"] = d.loc[d["score"].notna(), :].assign(
                has_pol=has_pol.reindex(d.index)).groupby("has_pol")["y"].mean().to_dict()
        # alternative outcomes (less detection-biased candidates)
        alt = {}
        for oc in ["Cybercrime_rans", "Cybercrime_hack"]:
            if oc not in biz.columns:
                continue
            o = biz[oc].astype(str)
            a_ok = ~o.isin({"Not asked", "nan"})
            yy = (o == "Yes").astype(float)
            dd = pd.DataFrame({"score": score, "y": yy})[a_ok].dropna()
            if len(dd) and dd["y"].sum() > 0:
                alt[oc] = {"n": int(len(dd)), "events": int(dd["y"].sum()),
                           "rpb": float(stats.pointbiserialr(dd["score"], dd["y"]).correlation),
                           "rate_score_ge1": float(dd.loc[dd["score"] >= 1, "y"].mean()),
                           "rate_score_0": float(dd.loc[dd["score"] == 0, "y"].mean())}
        # weighted logistic via GLM (freq_weights supported)
        try:
            m = sm.GLM(d["y"], X, family=sm.families.Binomial(), freq_weights=w).fit()
            or_ = float(np.exp(m.params["score_z"]))
            lo, hi = m.conf_int().loc["score_z"]
            or_lo, or_hi = float(np.exp(lo)), float(np.exp(hi))
            gate = max(1.3, or_detect)
            passed_gate = (or_ >= gate) and (or_lo > 1)
            cal_slope = float(m.params["score_z"])
        except Exception as e:
            or_, or_lo, or_hi, gate, passed_gate, cal_slope = np.nan, np.nan, np.nan, np.nan, False, np.nan
        a = auc(d["y"], d["score"])
        rel = reliability(items, score)
        results["waves"][label] = {
            "n_business": int(len(biz)), "n_asked_complete": int(n), "outcome_rate": float(p_out),
            "n_not_asked": int((~asked).sum()),
            "power_detectable_or_per_sd_80pct": or_detect, "n_required_for_or13": n_req_13,
            "gate_or_per_sd": gate,
            "weighted_logit": {"or_per_sd": or_, "ci95": [or_lo, or_hi], "gate_passed": passed_gate,
                               "calibration_slope": cal_slope},
            "auc": a, "reliability": rel, "detection_diagnostic": diag, "alternative_outcomes": alt,
            "items_used": [k for k, v in items.items() if v.notna().any()],
            "paradox_note": "inverse association expected if detection/reporting or reverse causality dominates",
        }
        print(f"=== {label}: n_business={len(biz)} asked_complete={n} outcome_rate={p_out:.3f}")
        print(f"    detectable OR/SD @80% = {or_detect:.3f} | n_req(OR1.3) = {n_req_13:.0f} | gate = {gate:.3f}")
        print(f"    weighted OR/SD = {or_:.3f} (95% CI {or_lo:.3f}-{or_hi:.3f}) gate_passed={passed_gate} | AUC={a:.3f}")
        print(f"    reliability: kr20={rel.get('kr20')} items={rel.get('n_items')}")
        print(f"    diagnostic: {diag}")
        for oc, v in alt.items():
            print(f"    alt {oc}: rpb={v['rpb']:.3f} (events={v['events']})")
    (OUT / "csbs_common.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved: {OUT / 'csbs_common.json'}")


if __name__ == "__main__":
    main()