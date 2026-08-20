#!/usr/bin/env python3
"""Supporting analyses: (1) governance matched-pair diagnostic on CSBS 9404;
(2) CSBS posture trend series 2016-2025 (8971 + 9101/9285/9404) for Fig. 1(a).
Outputs: analysis/results/auxiliary_analyses.json
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent / "results"

WAVES = {
    2025: DATA / "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta",
    2024: DATA / "UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta",
    2023: DATA / "UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta",
}
COMB = DATA / "UKDA-8971-stata/stata/stata13/dcms_csbs_combined_2016-2022_banded_cost_data_only_v3_public.dta"


def biz_mask(df, size_col):
    na = {"Not asked", "Not applicable", "Don't know", "Refused", "n/a", "nan"}
    return ~df[size_col].astype(str).isin(na)


def bin_yes(s):
    s = s.astype(str)
    out = pd.Series(np.nan, index=s.index)
    out[s.eq("Yes")] = 1
    out[s.eq("No")] = 0
    return out


def matched_pair():
    """Governance index (policy+training+insurance) vs breach, matched on size+sector (9404)."""
    df = pd.read_stata(WAVES[2025], convert_categoricals=True)
    biz = biz_mask(df, "sizeb_comb2")
    d = df[biz].copy()
    d["gov"] = 0.0
    d["gov"] += bin_yes(d["policy_comb"]).fillna(0) if "policy_comb" in d else 0
    d["gov"] += (1 - d["trained"].astype(str).isin({"No"}).astype(float)) if "trained" in d else 0
    ins = d["insurex"].astype(str)
    d["gov"] += ins.str.contains("specific|broader", case=False, na=False).astype(float)
    d["breach"] = d["Cybercrime_all"].astype(str).map({"Yes": 1, "No": 0})
    d = d.dropna(subset=["breach", "gov"])
    strata = d.groupby(["sizeb_comb2", "sector_comb2"]).apply(
        lambda g: pd.Series({
            "gov_hi_rate": g.loc[g["gov"] >= 2, "breach"].mean(),
            "gov_lo_rate": g.loc[g["gov"] < 2, "breach"].mean(),
            "n_hi": int((g["gov"] >= 2).sum()), "n_lo": int((g["gov"] < 2).sum()),
        }), include_groups=False)
    strata = strata.dropna(subset=["gov_hi_rate", "gov_lo_rate"])
    return {
        "n_strata": int(len(strata)),
        "strata_gov_hi_mean": float(strata["gov_hi_rate"].mean()) if len(strata) else None,
        "strata_gov_lo_mean": float(strata["gov_lo_rate"].mean()) if len(strata) else None,
        "note": "Suggestive only (secondary, proxy governance index; unadjusted within size x sector strata).",
    }


def trend_series():
    """Business-organisation prevalence of policy/training/insurance by year, 2016-2025."""
    rows = []
    # 8971 (2016-2022): non-unique value labels force manual mapping via StataReader
    from pandas.io.stata import StataReader
    with StataReader(COMB) as sr:
        vlabels = sr.value_labels()
    df = pd.read_stata(COMB, convert_categoricals=False)
    def as_text(col):
        return df[col].map(vlabels.get(col, {})).astype(str)
    year_col = next((c for c in df.columns if c.lower() in {"year", "yr", "surveyyear", "catiyear"}), None)
    if year_col is None:
        cands = [c for c in df.columns if "year" in c.lower()]
        year_col = cands[0] if cands else None
    size_col = "sizea" if "sizea" in df.columns else ("sizeb" if "sizeb" in df.columns else None)
    pol = "policy_comb" if "policy_comb" in df.columns else ("policy1" if "policy1" in df.columns else None)
    tr = "trained" if "trained" in df.columns else None
    ins = "insurex" if "insurex" in df.columns else None
    if year_col and size_col:
        s_size = as_text(size_col)
        b = df[~s_size.isin({"Not asked", "Not applicable", "Don't know", "Refused", "n/a", "nan"})]
        yrs = pd.to_numeric(b[year_col], errors="coerce")
        for y, idx in b.groupby(yrs).groups.items():
            if pd.isna(y):
                continue
            g = b.loc[idx]
            row = {"source": "8971", "year": int(y)}
            if pol:
                p = as_text(pol).loc[g.index]
                p2 = p.map({"Yes": 1.0, "No": 0.0})
                row["policy"] = float(p2.mean()) if p2.notna().any() else None
            if tr:
                t = as_text(tr).loc[g.index]
                t2 = t.map({"Yes": 1.0, "No": 0.0})
                row["training"] = float(t2.mean()) if t2.notna().any() else None
            if ins:
                i = as_text(ins).loc[g.index]
                row["insurance"] = float(i.str.contains("specific|broader", case=False, na=False).mean())
            rows.append(row)
    # recent waves
    for y, p in WAVES.items():
        d = pd.read_stata(p, convert_categoricals=True)
        size_col = "sizeb_comb2" if "sizeb_comb2" in d.columns else "sizeb"
        b = d[biz_mask(d, size_col)]
        row = {"source": str(y), "year": y}
        if "policy_comb" in d:
            row["policy"] = float(bin_yes(b["policy_comb"]).mean())
        if "trained" in d:
            row["training"] = float(bin_yes(b["trained"]).mean())
        if "insurex" in d:
            i = b["insurex"].astype(str)
            row["insurance"] = float(i.str.contains("specific|broader", case=False, na=False).mean())
        rows.append(row)
    out = sorted(rows, key=lambda r: r["year"])
    return out


def main():
    res = {"matched_pair": matched_pair(), "trend": trend_series()}
    (OUT / "auxiliary_analyses.json").write_text(json.dumps(res, indent=2, default=str))
    print("matched_pair:", res["matched_pair"])
    print("\ntrend (year: policy/training/insurance prevalence among businesses):")
    for r in res["trend"]:
        def f(k): return f"{r[k]*100:.1f}%" if k in r else "  n/a "
        print(f"  {r['year']} [{r['source']}]: policy {f('policy')}  training {f('training')}  insurance {f('insurance')}")
    print(f"Saved: {OUT / 'auxiliary_analyses.json'}")


if __name__ == "__main__":
    main()