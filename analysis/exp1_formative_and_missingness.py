#!/usr/bin/env python3
"""Experiment 1 (Claim K2): Variable-by-variable skip-routing attrition waterfall explaining
the legacy n=24 (2025) and n=25 (2024) complete-case collapse, complete-case selection-bias
tests, and full-sample formative Variance Inflation Factor (VIF) / tetrachoric diagnostics
across UK CSBS 2023 to 2025 and UK CSLS Waves 1 to 4.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import optimize, stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BANK_PATH = REPO / "instrument" / "bank_v1.json"
OUT_DIR = HERE / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_DIR = Path(os.environ.get("RAISR_SUMMARY_DIR", str(OUT_DIR / "summaries")))
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)


def resolve_data_dir() -> Path:
    env_dir = os.environ.get("RAISR_DATA_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    for cand in [REPO / "data", REPO.parent / "data"]:
        if (cand / "UKDA-9404-stata").exists():
            return cand
    raise FileNotFoundError("Could not locate UKDA data directory under data/ or RAISR_DATA_DIR")


LEGACY_KEYWORDS = {
    "H1": ["policy"],
    "H2": ["train"],
    "H3": ["insur"],
    "H4": ["backup"],
    "H5": ["admin", "privileg", "access control"],
    "H6": ["monitor", "antivirus", "anti-virus", "security software"],
    "I1": ["incident", "response", "plan"],
    "I2": ["contact"],
    "I3": ["exercise", "test"],
    "I4": [],
}


def variable_labels(path: Path) -> Dict[str, str]:
    itr = pd.read_stata(path, iterator=True)
    return itr.variable_labels()


def legacy_risk_item(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    s = df[col].astype(str)
    out = pd.Series(np.nan, index=df.index)
    out[s.eq("Yes")] = 0.0
    out[s.eq("No")] = 1.0
    return out


def tetrachoric_r(x: np.ndarray, y: np.ndarray) -> float:
    """Maximum-likelihood / Edwards cosine-checked bivariate normal tetrachoric correlation."""
    n11 = float(np.sum((x == 1) & (y == 1))) + 0.5
    n10 = float(np.sum((x == 1) & (y == 0))) + 0.5
    n01 = float(np.sum((x == 0) & (y == 1))) + 0.5
    n00 = float(np.sum((x == 0) & (y == 0))) + 0.5
    n = n11 + n10 + n01 + n00
    p1 = (n11 + n10) / n
    p2 = (n11 + n01) / n
    t1 = stats.norm.ppf(1.0 - p1)
    t2 = stats.norm.ppf(1.0 - p2)
    target = n11 / n

    def diff_fn(r: float) -> float:
        cov = np.array([[1.0, r], [r, 1.0]])
        # P(Z1 > t1, Z2 > t2) = P(-Z1 < -t1, -Z2 < -t2) with same correlation r
        prob = stats.multivariate_normal.cdf([-t1, -t2], mean=[0.0, 0.0], cov=cov)
        return float(prob - target)

    try:
        sol = optimize.brentq(diff_fn, -0.995, 0.995, xtol=1e-5)
        return float(sol)
    except ValueError:
        ratio = (n00 * n11) / (n01 * n10)
        return float(np.cos(np.pi / (1.0 + np.sqrt(ratio))))


def compute_formative_diagnostics(mat: pd.DataFrame) -> Dict:
    """Compute VIFs, singular-value condition number, KR-20, Pearson phi, and tetrachoric r."""
    clean = mat.dropna().astype(float)
    n_cases, k = clean.shape
    X = clean.to_numpy()
    corr_pearson = np.corrcoef(X, rowvar=False)

    vifs = {}
    cols = list(clean.columns)
    for j, cname in enumerate(cols):
        y_j = X[:, j]
        others = np.delete(X, j, axis=1)
        design = np.column_stack([np.ones(len(y_j)), others])
        beta, _, _, _ = np.linalg.lstsq(design, y_j, rcond=None)
        y_hat = design @ beta
        ss_res = float(np.sum((y_j - y_hat) ** 2))
        ss_tot = float(np.sum((y_j - np.mean(y_j)) ** 2))
        r2 = max(0.0, min(0.9999, 1.0 - ss_res / ss_tot)) if ss_tot > 0 else 0.0
        vifs[cname] = round(1.0 / (1.0 - r2), 4)

    # Standardized condition number
    X_std = (X - X.mean(axis=0)) / np.where(X.std(axis=0, ddof=1) > 0, X.std(axis=0, ddof=1), 1.0)
    svals = np.linalg.svd(X_std, compute_uv=False)
    cond_num = float(svals[0] / svals[-1]) if svals[-1] > 0 else float("inf")

    # KR-20
    p_vec = clean.mean(axis=0)
    var_tot = float(clean.sum(axis=1).var(ddof=1))
    kr20 = float((k / (k - 1.0)) * (1.0 - float((p_vec * (1.0 - p_vec)).sum()) / var_tot)) if var_tot > 0 else 0.0

    # Pairwise Pearson and tetrachoric summaries
    off_pearson = []
    off_tetra = []
    for i in range(k):
        for j in range(i + 1, k):
            off_pearson.append(float(corr_pearson[i, j]))
            off_tetra.append(tetrachoric_r(X[:, i], X[:, j]))

    return {
        "n_complete": int(n_cases),
        "n_items": int(k),
        "vifs": vifs,
        "max_vif": float(max(vifs.values())),
        "mean_vif": round(float(np.mean(list(vifs.values()))), 4),
        "condition_number": round(cond_num, 4),
        "kr20": round(kr20, 4),
        "mean_abs_pearson": round(float(np.mean(np.abs(off_pearson))), 4),
        "max_abs_pearson": round(float(np.max(np.abs(off_pearson))), 4),
        "mean_abs_tetrachoric": round(float(np.mean(np.abs(off_tetra))), 4),
        "max_abs_tetrachoric": round(float(np.max(np.abs(off_tetra))), 4),
    }


def audit_legacy_waterfall(df: pd.DataFrame, labels: Dict[str, str], wave_label: str) -> Dict:
    """Reproduce legacy cols[0] keyword selection and decompose step-by-step attrition."""
    core_ids = ["H1", "H2", "H3", "H4", "H5", "H6", "I1", "I2", "I3", "I4"]
    selected_cols = {}
    for iid in core_ids:
        kws = LEGACY_KEYWORDS.get(iid, [])
        hits = [c for c, lab in labels.items() if lab and any(k in str(lab).lower() for k in kws)]
        if hits:
            s_test = legacy_risk_item(df, hits[0])
            if s_test.notna().any():
                selected_cols[iid] = hits[0]

    n_total = len(df)
    alive = pd.Series(True, index=df.index)
    steps = []
    total_route_drops = 0
    total_dk_drops = 0
    total_other_drops = 0

    for iid, col in selected_cols.items():
        before = int(alive.sum())
        raw_str = df.loc[alive, col].astype(str)
        valid_yn = raw_str.isin({"Yes", "No"})
        dropped_mask = ~valid_yn
        dropped_vals = raw_str[dropped_mask]
        norm_vals = dropped_vals.str.strip().str.lower().str.replace("\x92", "'", regex=False).str.replace("\u2019", "'", regex=False)
        route_mask = norm_vals.isin({"not asked", "not applicable", "nan", "-1", "-1.0"})
        dk_mask = (~route_mask) & norm_vals.str.contains(r"don't know|refused", regex=True, na=False)
        n_route = int(route_mask.sum())
        n_dk = int(dk_mask.sum())
        n_other = int(len(dropped_vals) - n_route - n_dk)
        total_route_drops += n_route
        total_dk_drops += n_dk
        total_other_drops += n_other

        alive.loc[alive[alive].index[dropped_mask]] = False
        after = int(alive.sum())
        steps.append({
            "wave": wave_label,
            "item_id": iid,
            "selected_var": col,
            "var_label": str(labels.get(col, ""))[:90],
            "n_before": before,
            "n_after": after,
            "dropped_total": before - after,
            "dropped_not_asked_routing": n_route,
            "dropped_dk_refused": n_dk,
            "dropped_non_binary_label": n_other,
        })

    total_lost = n_total - int(alive.sum())
    # Note: non-binary value labels on insurex (e.g., 'We are not insured...') also fail legacy s.eq('Yes')/s.eq('No')!
    routing_plus_label_share = (total_route_drops + total_other_drops) / total_lost if total_lost > 0 else 0.0
    pure_routing_share = total_route_drops / total_lost if total_lost > 0 else 0.0

    # Selection bias check on business frame
    size_col = "sizeb"
    biz_mask = df[size_col].astype(str).isin({"Micro (1 to 9)", "Small (10 to 49)", "Medium (50 to 249)", "Large (250+)"})
    cc_in_biz = alive & biz_mask
    excl_in_biz = (~alive) & biz_mask
    out_str = df["Cybercrime_all"].astype(str)
    asked_b = ~out_str.isin({"Not asked", "nan"})

    cc_b = df.loc[cc_in_biz & asked_b]
    ex_b = df.loc[excl_in_biz & asked_b]
    cc_breach = float((cc_b["Cybercrime_all"].astype(str) == "Yes").mean()) if len(cc_b) > 0 else np.nan
    ex_breach = float((ex_b["Cybercrime_all"].astype(str) == "Yes").mean()) if len(ex_b) > 0 else np.nan
    cc_large = float((df.loc[cc_in_biz, size_col].astype(str) == "Large (250+)").mean()) if cc_in_biz.sum() > 0 else np.nan
    ex_large = float((df.loc[excl_in_biz, size_col].astype(str) == "Large (250+)").mean()) if excl_in_biz.sum() > 0 else np.nan

    p_breach_sel = np.nan
    if len(cc_b) > 0 and len(ex_b) > 0:
        tab = np.array([
            [int((cc_b["Cybercrime_all"].astype(str) == "Yes").sum()), int((cc_b["Cybercrime_all"].astype(str) != "Yes").sum())],
            [int((ex_b["Cybercrime_all"].astype(str) == "Yes").sum()), int((ex_b["Cybercrime_all"].astype(str) != "Yes").sum())],
        ])
        _, p_breach_sel = stats.fisher_exact(tab)

    return {
        "n_raw_interviews": int(n_total),
        "n_final_complete_case": int(alive.sum()),
        "n_final_in_business_frame": int(cc_in_biz.sum()),
        "total_rows_lost": int(total_lost),
        "lost_not_asked_routing": int(total_route_drops),
        "lost_non_binary_coding_mismatch": int(total_other_drops),
        "lost_respondent_dk_refused": int(total_dk_drops),
        "share_lost_not_asked_routing": round(pure_routing_share, 4),
        "share_lost_structural_routing_and_coding": round(routing_plus_label_share, 4),
        "selection_bias": {
            "cc_breach_rate": round(cc_breach, 4) if not np.isnan(cc_breach) else None,
            "excluded_breach_rate": round(ex_breach, 4) if not np.isnan(ex_breach) else None,
            "fisher_p_breach_difference": float(p_breach_sel) if not np.isnan(p_breach_sel) else None,
            "cc_large_250plus_share": round(cc_large, 4) if not np.isnan(cc_large) else None,
            "excluded_large_250plus_share": round(ex_large, 4) if not np.isnan(ex_large) else None,
        },
        "steps": steps,
    }


def build_unrouted_csbs_battery(df: pd.DataFrame, wave_label: str) -> pd.DataFrame:
    """Build unrouted core governance & hygiene binary gap items asked across the business frame."""
    biz = df[df["sizeb"].astype(str).isin({"Micro (1 to 9)", "Small (10 to 49)", "Medium (50 to 249)", "Large (250+)"})].copy()

    def bin_no(col: str) -> pd.Series:
        s = biz[col].astype(str)
        out = pd.Series(np.nan, index=biz.index)
        out[s == "Yes"] = 0.0
        out[s == "No"] = 1.0
        return out

    ins_s = biz["insurex"].astype(str)
    ins_gap = pd.Series(np.nan, index=biz.index)
    ins_gap[ins_s.str.contains("not insured|do not have", case=False, na=False)] = 1.0
    ins_gap[ins_s.str.contains("have cyber security cover|specific cyber security insurance", case=False, na=False)] = 0.0

    cols = {}
    for cname in ["manage1", "manage2", "manage3", "manage4", "trained", "supplyrisk_any", "incidactiona", "incidactionb"]:
        if cname in biz.columns:
            ser = bin_no(cname)
            if ser.notna().sum() > int(0.65 * len(biz)):
                cols[cname] = ser
    if ins_gap.notna().sum() > int(0.65 * len(biz)):
        cols["insurex_gap"] = ins_gap
    return pd.DataFrame(cols)


def build_unrouted_csls_battery(csls_path: Path) -> pd.DataFrame:
    df = pd.read_stata(csls_path, convert_categoricals=True)
    biz = df[df["qtypdum"].astype(str) == "Business"].copy()
    out = {}
    for k, v in [
        ("board_resp", "bgoverna"),
        ("desig_staff", "bgovernb"),
        ("incid_proc", "incidman"),
        ("sec_rules", "rulesa"),
        ("gov_docs", "gova"),
    ]:
        s = biz[v].astype(str)
        ser = pd.Series(np.nan, index=biz.index)
        ser[s == "Yes"] = 0.0
        ser[s == "No"] = 1.0
        out[k] = ser
    ins = biz["insurex"].astype(str)
    ins_b = pd.Series(np.nan, index=biz.index)
    ins_b[ins.str.contains("not insured", case=False, na=False)] = 1.0
    ins_b[ins.str.contains("specific cyber|broader insurance", case=False, na=False)] = 0.0
    out["cyber_ins_gap"] = ins_b
    return pd.DataFrame(out)


def main() -> int:
    data_dir = resolve_data_dir()
    waves = {
        "2025": data_dir / "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta",
        "2024": data_dir / "UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta",
        "2023": data_dir / "UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta",
    }
    csls_path = data_dir / "UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta"

    waterfalls = {}
    unrouted_diag = {}
    waterfall_csv_rows: List[Dict] = []
    vif_csv_rows: List[Dict] = []

    for w_lbl, w_path in waves.items():
        df = pd.read_stata(w_path, convert_categoricals=True)
        labs = variable_labels(w_path)
        wf = audit_legacy_waterfall(df, labs, w_lbl)
        waterfalls[f"CSBS_{w_lbl}"] = wf
        waterfall_csv_rows.extend(wf["steps"])

        bat = build_unrouted_csbs_battery(df, w_lbl)
        diag = compute_formative_diagnostics(bat)
        unrouted_diag[f"CSBS_{w_lbl}"] = diag
        vif_csv_rows.append({"dataset": f"CSBS_{w_lbl}", **{k: v for k, v in diag.items() if k != "vifs"}})

    csls_bat = build_unrouted_csls_battery(csls_path)
    csls_diag = compute_formative_diagnostics(csls_bat)
    unrouted_diag["CSLS_W1_W4"] = csls_diag
    vif_csv_rows.append({"dataset": "CSLS_W1_W4", **{k: v for k, v in csls_diag.items() if k != "vifs"}})

    pd.DataFrame(waterfall_csv_rows).to_csv(SUMMARY_DIR / "exp1_attrition_waterfall.csv", index=False)
    pd.DataFrame(vif_csv_rows).to_csv(SUMMARY_DIR / "exp1_vif_summary.csv", index=False)

    max_vif_overall = max(d["max_vif"] for d in unrouted_diag.values())
    min_structural_drop_share_24_25 = min(
        waterfalls["CSBS_2024"]["share_lost_structural_routing_and_coding"],
        waterfalls["CSBS_2025"]["share_lost_structural_routing_and_coding"],
    )

    total_route_all3 = sum(waterfalls[f"CSBS_{y}"]["lost_not_asked_routing"] for y in ["2023", "2024", "2025"])
    total_lost_all3 = sum(waterfalls[f"CSBS_{y}"]["total_rows_lost"] for y in ["2023", "2024", "2025"])
    pooled_3wave_not_asked_share = round(total_route_all3 / total_lost_all3, 6) if total_lost_all3 > 0 else 0.0

    result = {
        "claim_id": "K2",
        "legacy_waterfall_audit": waterfalls,
        "unrouted_formative_diagnostics": unrouted_diag,
        "summary_metrics": {
            "csbs_2023_legacy_n": waterfalls["CSBS_2023"]["n_final_complete_case"],
            "csbs_2024_legacy_n": waterfalls["CSBS_2024"]["n_final_complete_case"],
            "csbs_2025_legacy_n": waterfalls["CSBS_2025"]["n_final_complete_case"],
            "min_structural_drop_share_2024_2025": min_structural_drop_share_24_25,
            "pure_not_asked_share_2023": waterfalls["CSBS_2023"]["share_lost_not_asked_routing"],
            "pure_not_asked_share_2024": waterfalls["CSBS_2024"]["share_lost_not_asked_routing"],
            "pure_not_asked_share_2025": waterfalls["CSBS_2025"]["share_lost_not_asked_routing"],
            "pooled_3wave_not_asked_share": pooled_3wave_not_asked_share,
            "max_vif_across_all_4_datasets": max_vif_overall,
            "vif_ceiling_threshold": 3.3,
        },
    }
    out_file = OUT_DIR / "exp1_formative_and_missingness.json"
    out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(
        f"[exp1] legacy CC counts: 2023={waterfalls['CSBS_2023']['n_final_complete_case']}, "
        f"2024={waterfalls['CSBS_2024']['n_final_complete_case']}, "
        f"2025={waterfalls['CSBS_2025']['n_final_complete_case']} | "
        f"structural_drop_share_24_25={min_structural_drop_share_24_25:.4f} "
        f"(pure Not-asked: 2024={waterfalls['CSBS_2024']['share_lost_not_asked_routing']:.4f}, "
        f"2025={waterfalls['CSBS_2025']['share_lost_not_asked_routing']:.4f}) | "
        f"unrouted n: 2025={unrouted_diag['CSBS_2025']['n_complete']}, "
        f"2024={unrouted_diag['CSBS_2024']['n_complete']}, "
        f"2023={unrouted_diag['CSBS_2023']['n_complete']}, "
        f"CSLS={csls_diag['n_complete']} | max_VIF={max_vif_overall:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
