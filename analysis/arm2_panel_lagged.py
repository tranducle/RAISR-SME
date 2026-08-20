#!/usr/bin/env python3
"""Arm 2 -- does security posture at t-1 predict a breach at t? (CSLS panel, UKDS SN 9356).

Arm 1 measures an association at one point in time and cannot separate "policies cause reports"
from "reporting causes policies". This script runs the timing test that can: posture measured in
one wave, outcome measured in the next, on the same organisations.

Two specification decisions are pre-committed rather than chosen after seeing the estimates:

  1. Organisation frame. The primary frame is business organisations (qtypdum == "Business");
     the high-income charity sub-sample is estimated separately as a robustness frame rather
     than pooled into the headline.
  2. Sample harmonisation. The lagged logit and the firm fixed-effects specification run on ONE
     harmonised sample (rows with non-missing posture_{t-1}, size band, wave, LongId, outcome),
     so the two estimates differ by specification and not by who is in them. The maximal-sample
     FE is kept as a robustness row.

Posture score = 6 items: bgoverna, bgovernb, incidman, rulesa, gova, insurex.
Outcome: brk_outcome. Logits clustered by LongId with size (medium/large) + wave fixed effects;
FE = within-firm linear probability model with wave fixed effects. The 5-item robustness row is
the same specification without cyber insurance.

Scope limit, and it is not a technicality: CSLS covers medium (50-249) and large (250+)
organisations. Nothing estimated here is an SME point estimate.

Output: analysis/results/arm2_panel_lagged.json
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
CSLS = DATA / "UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta"

POSTURE_ITEMS = {
    "board_responsibility": "bgoverna",
    "designated_staff": "bgovernb",
    "incident_processes": "incidman",
    "rules_controls": "rulesa",
    "governance_docs": "gova",
}


def _binary_yes(col):
    s = col.astype(str)
    out = pd.Series(np.nan, index=col.index)
    out[s == "Yes"] = 1
    out[s == "No"] = 0
    return out


def load_csls():
    df = pd.read_stata(CSLS, convert_categoricals=True).copy()
    df["breach"] = df["brk_outcome"].astype(str).map({"Yes": 1, "No": 0})
    df.loc[~df["brk_outcome"].astype(str).isin({"Yes", "No"}), "breach"] = np.nan
    items = {k: _binary_yes(df[v]) for k, v in POSTURE_ITEMS.items()}
    posture = pd.DataFrame(items)
    ins = df["insurex"].astype(str)
    insurex_bin = pd.Series(np.nan, index=df.index)
    insurex_bin[ins.str.contains("specific cyber security insurance", case=False)] = 1
    insurex_bin[ins.str.contains("broader insurance policy", case=False)] = 1
    insurex_bin[ins.str.contains("not insured", case=False)] = 0
    posture["cyber_insurance"] = insurex_bin
    df["posture"] = posture.sum(axis=1, min_count=1)                     # 6-item score
    df["posture5"] = posture[list(POSTURE_ITEMS)].sum(axis=1, min_count=1)  # 5-item robustness
    df["size_band"] = df["qsize"].astype(str)
    df["wave_c"] = df["wave"].astype(str).str.replace(r"\.0$", "", regex=True)
    large = {"250 to 499": 1, "500 to 999": 1, "1,000 or more": 1, "50 to 249": 0}
    df["large"] = df["qsize"].astype(str).map(large)
    df["org_type"] = df["qtypdum"].astype(str)                           # "Business" / "Charity"
    return df


def z(x):
    x = pd.to_numeric(x, errors="coerce")
    return (x - x.mean()) / x.std()


def hsieh_detectable(n, p_outcome, alpha=0.05, power=0.80):
    from scipy import stats as _st
    za = _st.norm.ppf(1 - alpha / 2)
    zb = _st.norm.ppf(power)
    b_detect = (za + zb) / np.sqrt(n * p_outcome * (1 - p_outcome))
    n_req_13 = (za + zb) ** 2 / (p_outcome * (1 - p_outcome) * np.log(1.3) ** 2)
    return float(np.exp(b_detect)), float(n_req_13)


def run_logit(df, xcol, label):
    d = df.dropna(subset=["breach", xcol, "large", "wave_c", "LongId"]).copy()
    d = d[d["large"].notna()]
    if len(d) < 50:
        return {"label": label, "n": int(len(d)), "error": "n<50 after complete cases"}
    d[f"{xcol}_z"] = z(d[xcol])
    try:
        m = smf.logit(f"breach ~ {xcol}_z + large + C(wave_c)", data=d).fit(
            cov_type="cluster", cov_kwds={"groups": d["LongId"]}, disp=0, maxiter=200)
        coef = float(m.params[f"{xcol}_z"])
        ci = m.conf_int().loc[f"{xcol}_z"]
        return {"label": label, "n": int(len(d)), "n_clusters": int(d["LongId"].nunique()),
                "coef": coef, "or_per_sd": float(np.exp(coef)),
                "ci95_or": [float(np.exp(ci[0])), float(np.exp(ci[1]))],
                "p": float(m.pvalues[f"{xcol}_z"]),
                "direction": "protective" if np.exp(coef) < 1 else ("paradox" if np.exp(coef) > 1 else "null")}
    except Exception as e:
        return {"label": label, "n": int(len(d)), "error": str(e)}


def run_within_fe(df, label):
    """Within-firm LPM on an explicit sample: breach ~ posture_lag (demeaned) + wave FE."""
    d = df.dropna(subset=["breach", "posture_lag", "wave_c", "LongId"]).copy()
    gid = d["LongId"]
    def demean(s):
        return s - s.groupby(gid).transform("mean")
    d["y_w"] = demean(d["breach"])
    d["p_w"] = demean(d["posture_lag"])
    wave_dummies = pd.get_dummies(d["wave_c"], prefix="w", drop_first=True)
    for c in wave_dummies.columns:
        d[f"{c}_w"] = demean(wave_dummies[c])
    Xcols = ["p_w"] + [f"{c}_w" for c in wave_dummies.columns]
    X = sm.add_constant(d[Xcols])
    try:
        m = sm.OLS(d["y_w"], X).fit(cov_type="cluster", cov_kwds={"groups": gid})
        coef = float(m.params["p_w"])
        ci = m.conf_int().loc["p_w"]
        return {"label": label, "n": int(len(d)), "n_clusters": int(d["LongId"].nunique()),
                "coef_pp": coef, "ci95_pp": [float(ci[0]), float(ci[1])],
                "p": float(m.pvalues["p_w"]),
                "direction": "protective" if coef < 0 else ("paradox" if coef > 0 else "null")}
    except Exception as e:
        return {"label": label, "n": int(len(d)), "error": str(e)}


def frame_block(df, frame):
    """All Arm-2 specs for one organisation frame."""
    d = df.sort_values(["LongId", "wave"]).copy()
    d["posture_lag"] = d.groupby("LongId")["posture"].shift(1)
    d["posture5_lag"] = d.groupby("LongId")["posture5"].shift(1)

    # harmonized sample: lagged-eligible + size band + wave + outcome (one sample, both specs)
    harm = d.dropna(subset=["breach", "posture_lag", "large", "wave_c", "LongId"])
    harm = harm[harm["large"].notna()]

    lagged_ids = set(d.loc[d["posture_lag"].notna(), "LongId"].unique())
    lag_sample = d[d["LongId"].isin(lagged_ids)]

    models = [
        run_logit(d, "posture", "contemporaneous (full panel)"),
        run_logit(lag_sample, "posture", "contemporaneous (lagged-sample)"),
        run_logit(harm, "posture_lag", "lagged, harmonized sample"),
        run_within_fe(harm, "firm-FE, harmonized sample"),
        run_within_fe(d, "firm-FE, maximal sample (robustness)"),
        run_logit(d, "posture5", "contemporaneous, 5-item (robustness)"),
        run_logit(harm, "posture5_lag", "lagged, 5-item (robustness)"),
    ]

    lb = None
    lag = harm.dropna(subset=["posture_lag"])
    if len(lag) >= 10:
        med = lag["posture_lag"].median()
        hi = lag[lag["posture_lag"] >= med]["breach"]
        lo = lag[lag["posture_lag"] < med]["breach"]
        lb = {"n": int(len(lag)), "hi_rate": float(hi.mean()), "lo_rate": float(lo.mean())}

    power = None
    if len(harm) and 0 < harm["breach"].mean() < 1:
        or_det, n_req = hsieh_detectable(len(harm), float(harm["breach"].mean()))
        power = {"harmonized_n": int(len(harm)), "outcome_rate": float(harm["breach"].mean()),
                 "detectable_or_per_sd_80pct": or_det, "n_required_for_or13": n_req}

    return {
        "frame": frame,
        "frame_rows": int(len(d)),
        "unique_orgs": int(d["LongId"].nunique()),
        "orgs_ge2_waves": int((d.groupby("LongId")["wave"].nunique() >= 2).sum()),
        "breach_yes": int(d["breach"].eq(1).sum()),
        "breach_no": int(d["breach"].eq(0).sum()),
        "harmonized_n": int(len(harm)),
        "models": models,
        "lagged_bivariate": lb,
        "power": power,
    }


def main():
    df = load_csls()
    results = {
        "preregistered_run": True,
        "extends": "earlier CSLS panel specification, superseded by this script",
        "posture": "6 items (bgoverna, bgovernb, incidman, rulesa, gova, insurex)",
        "frames": {},
    }
    for frame in ["business", "charity", "pooled"]:
        sub = df if frame == "pooled" else df[df["org_type"] == "Business" if frame == "business" else df["org_type"] == "Charity"]
        results["frames"][frame] = frame_block(sub, frame)

    (OUT / "arm2_panel_lagged.json").write_text(json.dumps(results, indent=2, default=str))

    for frame, blk in results["frames"].items():
        print(f"\n=== FRAME {frame.upper()} ===  rows={blk['frame_rows']} orgs={blk['unique_orgs']} "
              f"(>=2 waves: {blk['orgs_ge2_waves']})  breach {blk['breach_yes']}/{blk['breach_yes']+blk['breach_no']} "
              f"harmonized n={blk['harmonized_n']}")
        for m in blk["models"]:
            if "error" in m:
                print(f"   {m['label']}: {m['error']} (n={m['n']})")
            elif "or_per_sd" in m:
                print(f"   {m['label']}: n={m['n']} OR/SD={m['or_per_sd']:.3f} "
                      f"CI[{m['ci95_or'][0]:.3f},{m['ci95_or'][1]:.3f}] p={m['p']:.3f} -> {m['direction']}")
            else:
                print(f"   {m['label']}: n={m['n']} coef={m['coef_pp']:+.4f} "
                      f"CI[{m['ci95_pp'][0]:+.4f},{m['ci95_pp'][1]:+.4f}] p={m['p']:.3f} -> {m['direction']}")
        if blk["lagged_bivariate"]:
            lb = blk["lagged_bivariate"]
            print(f"   lagged bivariate (median split): hi={lb['hi_rate']:.3f} lo={lb['lo_rate']:.3f} (n={lb['n']})")
        if blk["power"]:
            p = blk["power"]
            print(f"   power (harmonized): n={p['harmonized_n']} rate={p['outcome_rate']:.3f} "
                  f"detectable OR/SD@80%={p['detectable_or_per_sd_80pct']:.3f} n_req(OR1.3)={p['n_required_for_or13']:.0f}")
    print(f"\nSaved: {OUT / 'arm2_panel_lagged.json'}")


if __name__ == "__main__":
    main()