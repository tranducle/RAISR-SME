#!/usr/bin/env python3
"""Experiment 3 (Claim K4b): SME headcount size-band stratification across UK CSBS 2023 to 2025
(Micro 1 to 9, Small 10 to 49, Medium 50 to 249, Large 250+; N = 8,086 split-ballot-normalized),
Medium-SME (50 to 249) subgroup bridge in UK CSLS (N = 1,993 full panel; n = 570 multi-wave),
and 5-fold out-of-fold score-orientation + incremental Delta AUC analysis.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
import statsmodels.formula.api as smf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
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


def mann_whitney_auc(y: np.ndarray, s: np.ndarray) -> float:
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    n1, n0 = len(pos), len(neg)
    r = stats.rankdata(np.concatenate([pos, neg]))
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def build_core_gap_score(df: pd.DataFrame, mode: str = "mean") -> pd.Series:
    """Compute core gap score across asked items (mode='mean' normalizes split-ballot/routed availability; mode='sum' retains legacy sum)."""
    def risk_item(col: str | None, risk_vals: set) -> pd.Series:
        if not col or col not in df.columns:
            return pd.Series(np.nan, index=df.index)
        s = df[col].astype(str).str.replace("\x92", "'", regex=False).str.replace("\u2019", "'", regex=False)
        out = pd.Series(np.nan, index=df.index)
        out[s.isin(risk_vals)] = 1.0
        out[~s.isin(risk_vals) & ~s.isin({"Not asked", "Not applicable", "nan", "-1", "-1.0", "Don't know", "Refused"})] = 0.0
        return out

    pol = "policy_comb" if "policy_comb" in df.columns else ("policy1" if "policy1" in df.columns else None)
    items = {
        "no_formal_policy": risk_item(pol, {"No"}),
        "no_staff_training": risk_item("trained", {"No"}),
        "no_cyber_insurance": risk_item(
            "insurex",
            {
                "We are not insured against cyber security breaches or attacks",
                "No",
                "Not insured",
                "We do not have any cyber security insurance",
            },
        ),
    }
    mat = pd.concat(items.values(), axis=1)
    if mode == "sum":
        return mat.sum(axis=1, min_count=1)
    return mat.mean(axis=1)


def build_unrouted_8item_gap_score(df: pd.DataFrame) -> pd.Series:
    """8-item unrouted business governance & hygiene battery for CSBS 2024 and 2025."""
    cols = {}
    for cname in ["manage1", "manage2", "manage3", "manage4", "trained", "supplyrisk_any", "incidactiona", "incidactionb"]:
        if cname in df.columns:
            s = df[cname].astype(str)
            ser = pd.Series(np.nan, index=df.index)
            ser[s == "Yes"] = 0.0
            ser[s == "No"] = 1.0
            cols[cname] = ser
    ins_s = df["insurex"].astype(str) if "insurex" in df.columns else pd.Series(np.nan, index=df.index)
    ins_gap = pd.Series(np.nan, index=df.index)
    ins_gap[ins_s.str.contains("not insured|do not have", case=False, na=False)] = 1.0
    ins_gap[ins_s.str.contains("have cyber security cover|specific cyber security insurance", case=False, na=False)] = 0.0
    if ins_gap.notna().sum() > int(0.65 * len(df)):
        cols["insurex_gap"] = ins_gap
    if not cols:
        return pd.Series(np.nan, index=df.index)
    return pd.DataFrame(cols).mean(axis=1)


def load_csbs_all_waves(data_dir: Path) -> pd.DataFrame:
    waves = [
        ("2025", data_dir / "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta"),
        ("2024", data_dir / "UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta"),
        ("2023", data_dir / "UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta"),
    ]
    valid_sizes = {"Micro (1 to 9)", "Small (10 to 49)", "Medium (50 to 249)", "Large (250+)"}
    frames = []
    for yr, p in waves:
        df = pd.read_stata(p, convert_categoricals=True)
        biz = df[df["sizeb"].astype(str).isin(valid_sizes)].copy()
        score_mean = build_core_gap_score(biz, mode="mean")
        score_sum = build_core_gap_score(biz, mode="sum")
        score_unr8 = build_unrouted_8item_gap_score(biz)
        out = biz["Cybercrime_all"].astype(str)
        asked = ~out.isin({"Not asked", "nan"})
        y = pd.Series(np.nan, index=biz.index)
        y[asked] = (out[asked] == "Yes").astype(float)
        sec = biz["sector_comb2"].astype(str) if "sector_comb2" in biz.columns else pd.Series("Other", index=biz.index)
        part = pd.DataFrame({
            "wave": yr,
            "size4": biz["sizeb"].astype(str),
            "sector": sec.replace({"NA": "Other", "nan": "Other"}),
            "weight": pd.to_numeric(biz["weight"], errors="coerce"),
            "gap_score": score_mean,
            "gap_score_legacy_sum": score_sum,
            "gap_score_unrouted8": score_unr8,
            "y": y,
        }).dropna(subset=["gap_score", "y", "weight", "size4"])
        frames.append(part)
    return pd.concat(frames, ignore_index=True)


def fit_csbs_stratum(sub: pd.DataFrame, include_wave: bool = True) -> Dict:
    d = sub.copy()
    sd = float(d["gap_score"].std(ddof=1))
    d["gap_z"] = (d["gap_score"] - float(d["gap_score"].mean())) / sd if sd > 0 else 0.0
    d["maturity_z"] = -d["gap_z"]
    formula = "y ~ gap_z + C(sector) + C(wave)" if (include_wave and d["wave"].nunique() > 1) else "y ~ gap_z + C(sector)"
    res = smf.glm(formula, data=d, family=sm.families.Binomial()).fit(cov_type="HC3")
    b_gap = float(res.params["gap_z"])
    se_gap = float(res.bse["gap_z"])
    p_val = float(res.pvalues["gap_z"])
    lo_g, hi_g = b_gap - 1.96 * se_gap, b_gap + 1.96 * se_gap

    # Weighted version
    w = d["weight"] / d["weight"].mean()
    res_w = smf.glm(formula, data=d, family=sm.families.Binomial(), freq_weights=w).fit()
    bw = float(res_w.params["gap_z"])
    sew = float(res_w.bse["gap_z"])

    return {
        "n": int(len(d)),
        "events": int(d["y"].sum()),
        "breach_rate": round(float(d["y"].mean()), 4),
        "gap_score_beta": round(b_gap, 5),
        "gap_score_or": round(float(np.exp(b_gap)), 4),
        "gap_score_ci95_or": [round(float(np.exp(lo_g)), 4), round(float(np.exp(hi_g)), 4)],
        "maturity_score_or": round(float(np.exp(-b_gap)), 4),
        "maturity_score_ci95_or": [round(float(np.exp(-hi_g)), 4), round(float(np.exp(-lo_g)), 4)],
        "p_hc3": round(p_val, 6),
        "weighted_gap_score_or": round(float(np.exp(bw)), 4),
        "weighted_maturity_or": round(float(np.exp(-bw)), 4),
        "weighted_p": round(float(res_w.pvalues["gap_z"]), 6),
    }


def out_of_fold_delta_auc(df_wave: pd.DataFrame, seed: int = 202731, n_folds: int = 5, n_boot: int = 400) -> Dict:
    """Compute exact score orientation AUCs + 5-fold stratified OOF covariate-only vs full AUC."""
    d = df_wave.reset_index(drop=True).copy()
    y = d["y"].to_numpy()
    s_gap = d["gap_score"].to_numpy()
    raw_gap_auc = mann_whitney_auc(y, s_gap)
    inverted_mat_auc = mann_whitney_auc(y, -s_gap)

    rng = np.random.default_rng(seed)
    pos_idx = rng.permutation(np.where(y == 1)[0])
    neg_idx = rng.permutation(np.where(y == 0)[0])
    folds = np.zeros(len(d), dtype=int)
    for k, idx_arr in enumerate([pos_idx, neg_idx]):
        for pos, r_i in enumerate(idx_arr):
            folds[r_i] = pos % n_folds

    X_cov = pd.get_dummies(d[["size4", "sector"]], drop_first=True, dtype=float)
    p_cov = np.zeros(len(d), dtype=float)
    p_full = np.zeros(len(d), dtype=float)

    for f in range(n_folds):
        tr = folds != f
        te = folds == f
        X0_tr = sm.add_constant(X_cov.loc[tr], has_constant="add")
        X0_te = sm.add_constant(X_cov.loc[te], has_constant="add")
        m0 = sm.GLM(y[tr], X0_tr, family=sm.families.Binomial()).fit()
        p_cov[te] = m0.predict(X0_te)

        mu_s = float(s_gap[tr].mean())
        sd_s = float(s_gap[tr].std(ddof=1)) or 1.0
        X1_tr = X0_tr.copy()
        X1_tr["gap_z"] = (s_gap[tr] - mu_s) / sd_s
        X1_te = X0_te.copy()
        X1_te["gap_z"] = (s_gap[te] - mu_s) / sd_s
        m1 = sm.GLM(y[tr], X1_tr, family=sm.families.Binomial()).fit()
        p_full[te] = m1.predict(X1_te)

    auc_cov = mann_whitney_auc(y, p_cov)
    auc_full = mann_whitney_auc(y, p_full)
    delta_auc = auc_full - auc_cov

    boot_deltas = []
    for _ in range(n_boot):
        b_idx = rng.integers(0, len(d), size=len(d))
        if len(np.unique(y[b_idx])) < 2:
            continue
        boot_deltas.append(mann_whitney_auc(y[b_idx], p_full[b_idx]) - mann_whitney_auc(y[b_idx], p_cov[b_idx]))
    bd = np.array(boot_deltas)

    return {
        "n": int(len(d)),
        "raw_gap_score_auc": round(raw_gap_auc, 5),
        "inverted_maturity_score_auc": round(inverted_mat_auc, 5),
        "orientation_sum_check": round(raw_gap_auc + inverted_mat_auc, 8),
        "oof_covariate_only_auc": round(auc_cov, 5),
        "oof_full_model_auc": round(auc_full, 5),
        "oof_delta_auc": round(delta_auc, 5),
        "oof_delta_auc_ci95": [round(float(np.percentile(bd, 2.5)), 5), round(float(np.percentile(bd, 97.5)), 5)],
    }


def run_csls_medium_sme_bridge(data_dir: Path) -> Dict:
    spec = importlib.util.spec_from_file_location("exp2_mod", HERE / "exp2_common_sample_and_mechanisms.py")
    exp2 = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(exp2)

    df = exp2.load_csls_panel(data_dir)
    full_cc, _, common = exp2.build_common_sample(df)

    bridge: Dict[str, Dict] = {}
    for label, is_large in [("medium_sme_50_249", 0.0), ("large_250_plus", 1.0)]:
        sub = common[common["large"] == is_large].copy()
        sub["p_c_z"] = exp2.zscore(sub["posture"])
        sub["p_l_z"] = exp2.zscore(sub["posture_lag"])
        mc = smf.glm("breach ~ p_c_z + C(wave_c)", data=sub, family=sm.families.Binomial()).fit(
            cov_type="cluster", cov_kwds={"groups": sub["LongId"]}
        )
        ml = smf.glm("breach ~ p_l_z + C(wave_c)", data=sub, family=sm.families.Binomial()).fit(
            cov_type="cluster", cov_kwds={"groups": sub["LongId"]}
        )
        # Stacked cluster-robust delta_beta within stratum
        d_c = sub[["LongId", "breach", "wave_c"]].copy()
        d_c["arm_c"] = 1.0
        d_c["pz"] = sub["p_c_z"].to_numpy()
        d_l = sub[["LongId", "breach", "wave_c"]].copy()
        d_l["arm_c"] = 0.0
        d_l["pz"] = sub["p_l_z"].to_numpy()
        st_sub = pd.concat([d_c, d_l], ignore_index=True)
        ms = smf.glm("breach ~ pz + arm_c:pz + arm_c * C(wave_c)", data=st_sub, family=sm.families.Binomial()).fit(
            cov_type="cluster", cov_kwds={"groups": st_sub["LongId"]}
        )
        db = float(ms.params["arm_c:pz"])
        sdb = float(ms.bse["arm_c:pz"])
        pdb = float(2.0 * (1.0 - stats.norm.cdf(abs(db / sdb))))

        # Full-panel Mundlak on N=1993 Medium vs N=1068 Large
        f_sub = full_cc[full_cc["large"] == is_large].copy()
        mund_full_sub = exp2.run_mundlak(f_sub, f"full_{label}", col="posture")
        mund_lag_sub = exp2.run_mundlak(sub, f"lag_{label}", col="posture_lag")

        bc, sc = float(mc.params["p_c_z"]), float(mc.bse["p_c_z"])
        bl, sl = float(ml.params["p_l_z"]), float(ml.bse["p_l_z"])
        bridge[label] = {
            "n": int(len(sub)),
            "n_firms": int(sub["LongId"].nunique()),
            "n_full_panel": mund_full_sub["n"],
            "n_full_firms": mund_full_sub["n_firms"],
            "breach_rate": round(float(sub["breach"].mean()), 4),
            "contemp_beta": round(bc, 5),
            "contemp_or": round(float(np.exp(bc)), 4),
            "contemp_ci95_or": [round(float(np.exp(bc - 1.96 * sc)), 4), round(float(np.exp(bc + 1.96 * sc)), 4)],
            "contemp_p": round(float(mc.pvalues["p_c_z"]), 6),
            "lagged_beta": round(bl, 5),
            "lagged_or": round(float(np.exp(bl)), 4),
            "lagged_ci95_or": [round(float(np.exp(bl - 1.96 * sl)), 4), round(float(np.exp(bl + 1.96 * sl)), 4)],
            "lagged_p": round(float(ml.pvalues["p_l_z"]), 6),
            "delta_beta": round(db, 5),
            "delta_beta_se": round(sdb, 5),
            "delta_beta_ci95": [round(db - 1.96 * sdb, 5), round(db + 1.96 * sdb, 5)],
            "delta_beta_p_wald": round(pdb, 6),
            "full_mundlak_beta_between": mund_full_sub["beta_between"],
            "full_mundlak_ci95_between": mund_full_sub["ci95_between"],
            "full_mundlak_or_between": mund_full_sub["or_between"],
            "full_mundlak_p_between": mund_full_sub["p_between"],
            "lag_mundlak_beta_within": mund_lag_sub["beta_within"],
            "lag_mundlak_p_within": mund_lag_sub["p_within"],
        }

    # Stacked 3-way interaction testing whether delta_beta differs between Medium SMEs and Large firms
    c_all = common.copy()
    dc_a = c_all[["LongId", "breach", "large", "wave_c"]].copy()
    dc_a["arm_c"] = 1.0
    dc_a["pz"] = c_all.groupby("large")["posture"].transform(exp2.zscore).to_numpy()
    dl_a = c_all[["LongId", "breach", "large", "wave_c"]].copy()
    dl_a["arm_c"] = 0.0
    dl_a["pz"] = c_all.groupby("large")["posture_lag"].transform(exp2.zscore).to_numpy()
    st_all = pd.concat([dc_a, dl_a], ignore_index=True)
    m_int = smf.glm(
        "breach ~ arm_c * large * pz + arm_c * large * C(wave_c)",
        data=st_all,
        family=sm.families.Binomial(),
    ).fit(cov_type="cluster", cov_kwds={"groups": st_all["LongId"]})
    b_int = float(m_int.params["arm_c:large:pz"])
    s_int = float(m_int.bse["arm_c:large:pz"])
    p_int = float(2.0 * (1.0 - stats.norm.cdf(abs(b_int / s_int))))
    bridge["medium_vs_large_delta_beta_interaction"] = {
        "diff_large_minus_medium_delta_beta": round(b_int, 5),
        "se": round(s_int, 5),
        "p_wald": round(p_int, 6),
    }
    return bridge


def main() -> int:
    data_dir = resolve_data_dir()
    csbs = load_csbs_all_waves(data_dir)

    strata_order = [
        ("micro_1_9", "Micro (1 to 9)", "Micro (1-9)"),
        ("small_10_49", "Small (10 to 49)", "Small (10-49)"),
        ("medium_50_249", "Medium (50 to 249)", "Medium (50-249)"),
        ("large_250_plus", "Large (250+)", "Large (250+)"),
    ]

    pooled_strata = {}
    per_wave_strata: Dict[str, Dict] = {}
    fig2_rows: List[Dict] = []

    p_raw_list = []
    for key, raw_lbl, short_lbl in strata_order:
        sub = csbs[csbs["size4"] == raw_lbl]
        fit_s = fit_csbs_stratum(sub, include_wave=True)
        pooled_strata[key] = fit_s
        p_raw_list.append((key, fit_s["p_hc3"]))
        fig2_rows.append({
            "dataset": "CSBS_Pooled",
            "stratum_id": key,
            "stratum_label": short_lbl,
            "n": fit_s["n"],
            "breach_rate": fit_s["breach_rate"],
            "gap_or": fit_s["gap_score_or"],
            "gap_or_lo": fit_s["gap_score_ci95_or"][0],
            "gap_or_hi": fit_s["gap_score_ci95_or"][1],
            "maturity_or": fit_s["maturity_score_or"],
            "maturity_or_lo": fit_s["maturity_score_ci95_or"][0],
            "maturity_or_hi": fit_s["maturity_score_ci95_or"][1],
            "p_hc3": fit_s["p_hc3"],
        })

    # Holm-Bonferroni across the 4 pooled size strata
    sorted_p = sorted(p_raw_list, key=lambda x: x[1])
    m_fam = len(sorted_p)
    holm_adj = {}
    running_max = 0.0
    for rank_i, (k_id, pv) in enumerate(sorted_p):
        adj = min(1.0, pv * (m_fam - rank_i))
        running_max = max(running_max, adj)
        holm_adj[k_id] = round(running_max, 6)
    for k_id, adj_v in holm_adj.items():
        pooled_strata[k_id]["p_holm"] = adj_v

    for yr in ["2025", "2024", "2023"]:
        per_wave_strata[yr] = {}
        for key, raw_lbl, _ in strata_order:
            sub_w = csbs[(csbs["wave"] == yr) & (csbs["size4"] == raw_lbl)]
            per_wave_strata[yr][key] = fit_csbs_stratum(sub_w, include_wave=False)

    # Robustness: legacy 3-item sum and 2024/2025 8-item unrouted battery
    legacy_sum_strata = {}
    unrouted_8item_strata = {}
    csbs_2425 = csbs[csbs["wave"].isin(["2024", "2025"])].dropna(subset=["gap_score_unrouted8"]).copy()
    for key, raw_lbl, _ in strata_order:
        sub_l = csbs[csbs["size4"] == raw_lbl].copy()
        sub_l["gap_score"] = sub_l["gap_score_legacy_sum"]
        legacy_sum_strata[key] = fit_csbs_stratum(sub_l, include_wave=True)
        sub_u = csbs_2425[csbs_2425["size4"] == raw_lbl].copy()
        sub_u["gap_score"] = sub_u["gap_score_unrouted8"]
        unrouted_8item_strata[key] = fit_csbs_stratum(sub_u, include_wave=True)

    csls_bridge = run_csls_medium_sme_bridge(data_dir)

    # Append CSLS Medium SME and Large rows to fig2 CSV for visual bridge comparison
    for bkey, blbl in [("medium_sme_50_249", "CSLS_Medium_50_249"), ("large_250_plus", "CSLS_Large_250plus")]:
        bm = csls_bridge[bkey]
        fig2_rows.append({
            "dataset": f"{blbl}_Contemp",
            "stratum_id": f"csls_{bkey}_contemp",
            "stratum_label": f"{blbl}_Contemp",
            "n": bm["n"],
            "breach_rate": bm["breach_rate"],
            "gap_or": round(1.0 / bm["contemp_or"], 4),
            "gap_or_lo": round(1.0 / bm["contemp_ci95_or"][1], 4),
            "gap_or_hi": round(1.0 / bm["contemp_ci95_or"][0], 4),
            "maturity_or": bm["contemp_or"],
            "maturity_or_lo": bm["contemp_ci95_or"][0],
            "maturity_or_hi": bm["contemp_ci95_or"][1],
            "p_hc3": bm["contemp_p"],
        })
        fig2_rows.append({
            "dataset": f"{blbl}_Lagged",
            "stratum_id": f"csls_{bkey}_lagged",
            "stratum_label": f"{blbl}_Lagged",
            "n": bm["n"],
            "breach_rate": bm["breach_rate"],
            "gap_or": round(1.0 / bm["lagged_or"], 4),
            "gap_or_lo": round(1.0 / bm["lagged_ci95_or"][1], 4),
            "gap_or_hi": round(1.0 / bm["lagged_ci95_or"][0], 4),
            "maturity_or": bm["lagged_or"],
            "maturity_or_lo": bm["lagged_ci95_or"][0],
            "maturity_or_hi": bm["lagged_ci95_or"][1],
            "p_hc3": bm["lagged_p"],
        })
    pd.DataFrame(fig2_rows).to_csv(SUMMARY_DIR / "fig2_csbs_size_strata.csv", index=False)

    # 5-seed OOF Delta AUC across CSBS waves
    auc_by_wave = {}
    auc_csv_rows = []
    for yr in ["2025", "2024", "2023"]:
        sub_y = csbs[csbs["wave"] == yr]
        seed_runs = [out_of_fold_delta_auc(sub_y, seed=202731 + s) for s in range(5)]
        primary_auc = seed_runs[0]
        primary_auc["five_seed_mean_oof_delta_auc"] = round(float(np.mean([r["oof_delta_auc"] for r in seed_runs])), 5)
        primary_auc["five_seed_values_oof_full_auc"] = [r["oof_full_model_auc"] for r in seed_runs]
        primary_auc["five_seed_values_oof_cov_auc"] = [r["oof_covariate_only_auc"] for r in seed_runs]
        auc_by_wave[yr] = primary_auc
        auc_csv_rows.append({"wave": yr, **{k: v for k, v in primary_auc.items() if not isinstance(v, list)}})
    pd.DataFrame(auc_csv_rows).to_csv(SUMMARY_DIR / "fig2_auc_decomposition.csv", index=False)

    # Count how many of the 4 SME strata checks match the reporting-salience direction:
    # (1) CSBS Micro gap_or < 1, (2) CSBS Small gap_or < 1, (3) CSBS Medium gap_or < 1,
    # (4) CSLS Medium SME (50-249) delta_beta > 0 (contemporaneous > lagged)
    sme_checks = {
        "csbs_micro_gap_or_lt_1": pooled_strata["micro_1_9"]["gap_score_or"] < 1.0,
        "csbs_small_gap_or_lt_1": pooled_strata["small_10_49"]["gap_score_or"] < 1.0,
        "csbs_medium_gap_or_lt_1": pooled_strata["medium_50_249"]["gap_score_or"] < 1.0,
        "csls_medium_sme_attenuates": csls_bridge["medium_sme_50_249"]["delta_beta"] > 0.0,
    }
    sme_consistency_fraction = sum(1 for v in sme_checks.values() if v) / 4.0

    out = {
        "claim_id": "K4b",
        "total_csbs_complete_case": int(len(csbs)),
        "csbs_pooled_by_size": pooled_strata,
        "csbs_pooled_legacy_sum_robustness": legacy_sum_strata,
        "csbs_2024_2025_unrouted_8item_robustness": unrouted_8item_strata,
        "csbs_per_wave_by_size": per_wave_strata,
        "csls_medium_vs_large_bridge": csls_bridge,
        "auc_orientation_and_oof_delta": auc_by_wave,
        "sme_strata_checks": sme_checks,
        "sme_strata_consistency_fraction": sme_consistency_fraction,
    }
    out_file = OUT_DIR / "exp3_sme_size_bridge_and_auc.json"
    out_file.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(
        f"[exp3] CSBS N={len(csbs)} gap ORs (<1 means higher maturity -> more breach reports): "
        f"Micro={pooled_strata['micro_1_9']['gap_score_or']:.3f} (p={pooled_strata['micro_1_9']['p_hc3']:.4f}), "
        f"Small={pooled_strata['small_10_49']['gap_score_or']:.3f} (p={pooled_strata['small_10_49']['p_hc3']:.4f}), "
        f"Medium={pooled_strata['medium_50_249']['gap_score_or']:.3f} (p={pooled_strata['medium_50_249']['p_hc3']:.4f}), "
        f"Large={pooled_strata['large_250_plus']['gap_score_or']:.3f} | "
        f"CSLS Medium SME (n={csls_bridge['medium_sme_50_249']['n']}): contemp OR={csls_bridge['medium_sme_50_249']['contemp_or']:.3f} -> "
        f"lagged OR={csls_bridge['medium_sme_50_249']['lagged_or']:.3f} (delta_beta={csls_bridge['medium_sme_50_249']['delta_beta']:+.4f}) | "
        f"SME consistency={sme_consistency_fraction:.2f} | "
        f"2025 AUC: raw_gap={auc_by_wave['2025']['raw_gap_score_auc']:.3f}, inv_mat={auc_by_wave['2025']['inverted_maturity_score_auc']:.3f}, "
        f"OOF cov={auc_by_wave['2025']['oof_covariate_only_auc']:.3f} -> full={auc_by_wave['2025']['oof_full_model_auc']:.3f} (Delta={auc_by_wave['2025']['oof_delta_auc']:+.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
