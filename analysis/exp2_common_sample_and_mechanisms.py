#!/usr/bin/env python3
"""Experiment 2 (Claims K3 and K3b): Genuine multi-wave (n = 865, 575 LongId firms) and full-panel
(N = 3,061, 2,196 unique organizations) longitudinal decomposition on UK CSLS Waves 1 to 4 (SN 9356).

Executes:
  1. Contemporaneous, One-Wave-Lagged, Joint (P_t + P_{t-1}), Dynamic (P_{t-1} + Y_{t-1}),
     and Within-Firm Fixed-Effects models on the exact n = 865 consecutive multi-wave transitions
     (plus attrition comparison against Full N = 3,061 and Multi-Wave n = 1,455, and survey-weighted
     sensitivity).
  2. Paired B = 2,000 firm-cluster bootstrap (across 5 independent seeds x 400 draws = 2,000)
     and Stacked-GLM (1,730 rows clustered by LongId) Wald test for delta_beta = beta_contemp - beta_lag
     (both log-odds and LPM/AME probability points).
  3. Mundlak (1978) correlated random-effects decomposition (between-firm mean bar_P_i vs
     within-firm deviation P_{it} - bar_P_i) on n = 865 and full N = 3,061, plus stacked
     2,196-cluster contrast (beta_{B,full} - beta_{W,lag}).
  4. Cross-lagged reverse-causation test (posture_t and Delta_posture_t regressed on breach_{t-1}).
  5. Within-stratum firm-trajectory permutation placebo (500 shuffles, seed 202720) preserving exact
     within-firm serial correlation.
"""
from __future__ import annotations

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

POSTURE_ITEMS = {
    "board_responsibility": "bgoverna",
    "designated_staff": "bgovernb",
    "incident_processes": "incidman",
    "rules_controls": "rulesa",
    "governance_docs": "gova",
}


def resolve_data_dir() -> Path:
    env_dir = os.environ.get("RAISR_DATA_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    for cand in [REPO / "data", REPO.parent / "data"]:
        if (cand / "UKDA-9356-stata").exists():
            return cand
    raise FileNotFoundError("Could not locate UKDA CSLS data directory under data/ or RAISR_DATA_DIR")


def zscore(s: pd.Series) -> pd.Series:
    sd = float(s.std(ddof=1))
    return (s - float(s.mean())) / sd if sd > 0 else s * 0.0


def load_csls_panel(data_dir: Path) -> pd.DataFrame:
    csls_path = data_dir / "UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta"
    df = pd.read_stata(csls_path, convert_categoricals=True).copy()
    df["breach"] = df["brk_outcome"].astype(str).map({"Yes": 1.0, "No": 0.0})
    df.loc[~df["brk_outcome"].astype(str).isin({"Yes", "No"}), "breach"] = np.nan

    items = {}
    for k, v in POSTURE_ITEMS.items():
        s = df[v].astype(str)
        ser = pd.Series(np.nan, index=df.index)
        ser[s == "Yes"] = 1.0
        ser[s == "No"] = 0.0
        items[k] = ser
    post_df = pd.DataFrame(items)

    ins = df["insurex"].astype(str)
    ins_bin = pd.Series(np.nan, index=df.index)
    ins_bin[ins.str.contains("specific cyber security insurance|broader insurance policy", case=False, na=False)] = 1.0
    ins_bin[ins.str.contains("not insured", case=False, na=False)] = 0.0
    post_df["cyber_insurance"] = ins_bin

    df["posture"] = post_df.sum(axis=1, min_count=1)
    df["wave_num"] = pd.to_numeric(df["wave"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    df["wave_c"] = df["wave_num"].astype("Int64").astype(str)
    large_map = {"250 to 499": 1.0, "500 to 999": 1.0, "1,000 or more": 1.0, "50 to 249": 0.0}
    df["large"] = df["qsize"].astype(str).map(large_map)
    df["org_type"] = df["qtypdum"].astype(str)
    df["wght_num"] = pd.to_numeric(df["wght"], errors="coerce") if "wght" in df.columns else 1.0
    return df


def build_common_sample(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    biz = df[df["org_type"] == "Business"].copy()
    raw_lid = biz["LongId"].fillna("").astype(str).str.strip()
    biz["panel_id"] = raw_lid.where(raw_lid != "", np.nan)
    biz["cluster_id"] = np.where(
        raw_lid != "",
        raw_lid,
        ["FRESH_" + str(idx) for idx in biz.index],
    )
    # Use cluster_id for full-panel firm means so single-wave Wave-4 Fresh firms are never merged into one '' group
    firm_means = biz.groupby("cluster_id")["posture"].transform("mean")
    firm_counts = biz.groupby("cluster_id")["posture"].transform("count")
    biz["firm_mean_posture_allwaves"] = firm_means
    biz["firm_within_posture_allwaves"] = biz["posture"] - firm_means
    biz["n_waves_firm"] = firm_counts
    biz["LongId"] = biz["cluster_id"]

    full_cc = biz.dropna(subset=["breach", "posture", "large", "wave_num", "cluster_id"]).copy()
    multi_cc = full_cc[full_cc["panel_id"].notna() & (full_cc["n_waves_firm"] >= 2)].copy()

    # Genuine multi-wave longitudinal transitions strictly within non-empty panel_id organizations (n = 865 across 575 firms)
    panel_biz = biz[biz["panel_id"].notna()].sort_values(["panel_id", "wave_num"]).copy()
    panel_biz["prev_wave"] = panel_biz.groupby("panel_id")["wave_num"].shift(1)
    panel_biz["wave_gap"] = panel_biz["wave_num"] - panel_biz["prev_wave"]
    panel_biz["posture_lag"] = panel_biz.groupby("panel_id")["posture"].shift(1)
    panel_biz["breach_lag"] = panel_biz.groupby("panel_id")["breach"].shift(1)

    common = panel_biz.dropna(subset=["breach", "posture", "posture_lag", "large", "wave_num", "panel_id"]).copy()
    return full_cc, multi_cc, common


def fit_clustered_logit(df: pd.DataFrame, formula: str, param_name: str, weights: pd.Series | None = None) -> Dict:
    if weights is not None:
        w = weights / weights.mean()
        res = smf.glm(formula, data=df, family=sm.families.Binomial(), freq_weights=w).fit(
            cov_type="cluster", cov_kwds={"groups": df["LongId"]}
        )
    else:
        res = smf.glm(formula, data=df, family=sm.families.Binomial()).fit(
            cov_type="cluster", cov_kwds={"groups": df["LongId"]}
        )
    b = float(res.params[param_name])
    se = float(res.bse[param_name])
    z_stat = b / se if se > 0 else 0.0
    p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(z_stat))))
    lo, hi = b - 1.96 * se, b + 1.96 * se
    # Average Marginal Effect (AME) in probability points per 1 unit of param_name
    lin_pred = res.predict(df)
    ame = float(np.mean(lin_pred * (1.0 - lin_pred)) * b)
    return {
        "n": int(len(df)),
        "n_firms": int(df["LongId"].nunique()),
        "beta": round(b, 5),
        "se": round(se, 5),
        "ci95_beta": [round(lo, 5), round(hi, 5)],
        "or": round(float(np.exp(b)), 4),
        "ci95_or": [round(float(np.exp(lo)), 4), round(float(np.exp(hi)), 4)],
        "p": round(p_val, 6),
        "ame_pp": round(ame * 100.0, 4),
    }


def stacked_delta_beta_wald(common: pd.DataFrame) -> Dict:
    """Exact stacked-GLM cluster-robust Wald test for delta_beta = beta_contemp - beta_lag on common panel."""
    d_c = common[["LongId", "breach", "large", "wave_c"]].copy()
    d_c["arm_contemp"] = 1.0
    d_c["post_z"] = zscore(common["posture"]).to_numpy()

    d_l = common[["LongId", "breach", "large", "wave_c"]].copy()
    d_l["arm_contemp"] = 0.0
    d_l["post_z"] = zscore(common["posture_lag"]).to_numpy()

    stacked = pd.concat([d_c, d_l], ignore_index=True)
    # Fully interacted covariates so each arm has its own intercept, size, and wave slopes
    formula = "breach ~ post_z + arm_contemp:post_z + arm_contemp * (large + C(wave_c))"
    res = smf.glm(formula, data=stacked, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": stacked["LongId"]}
    )
    delta_b = float(res.params["arm_contemp:post_z"])
    se = float(res.bse["arm_contemp:post_z"])
    z_val = delta_b / se
    p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(z_val))))

    # Also LPM stacked difference (immune to logit non-collapsibility)
    res_lpm = smf.ols(formula, data=stacked).fit(cov_type="cluster", cov_kwds={"groups": stacked["LongId"]})
    delta_lpm_pp = float(res_lpm.params["arm_contemp:post_z"]) * 100.0
    se_lpm_pp = float(res_lpm.bse["arm_contemp:post_z"]) * 100.0
    p_lpm = float(res_lpm.pvalues["arm_contemp:post_z"])

    return {
        "n_stacked_rows": int(len(stacked)),
        "n_clusters": int(stacked["LongId"].nunique()),
        "delta_beta_log_odds": round(delta_b, 5),
        "se_log_odds": round(se, 5),
        "ci95_log_odds": [round(delta_b - 1.96 * se, 5), round(delta_b + 1.96 * se, 5)],
        "z_stat": round(z_val, 4),
        "p_wald": round(p_val, 6),
        "delta_lpm_pp": round(delta_lpm_pp, 4),
        "se_lpm_pp": round(se_lpm_pp, 4),
        "ci95_lpm_pp": [round(delta_lpm_pp - 1.96 * se_lpm_pp, 4), round(delta_lpm_pp + 1.96 * se_lpm_pp, 4)],
        "p_lpm": round(p_lpm, 6),
    }


def cluster_bootstrap_delta_beta(common: pd.DataFrame, n_boot: int = 400, seed: int = 202711) -> Dict:
    rng = np.random.default_rng(seed)
    c_reset = common.reset_index(drop=True)
    firms = c_reset["LongId"].unique()
    n_firms = len(firms)
    idx_map = {fid: grp.index.to_numpy() for fid, grp in c_reset.groupby("LongId")}
    y_arr = c_reset["breach"].to_numpy(dtype=float)
    p_c_arr = c_reset["posture"].to_numpy(dtype=float)
    p_l_arr = c_reset["posture_lag"].to_numpy(dtype=float)
    cov_mat = pd.get_dummies(c_reset[["large", "wave_c"]], drop_first=True, dtype=float).to_numpy()

    deltas, b_conts, b_lags = [], [], []
    for _ in range(n_boot):
        sampled_ids = rng.choice(firms, size=n_firms, replace=True)
        r_idx = np.concatenate([idx_map[fid] for fid in sampled_ids])
        yb = y_arr[r_idx]
        pc = p_c_arr[r_idx]
        pl = p_l_arr[r_idx]
        pc_z = (pc - pc.mean()) / (pc.std(ddof=1) or 1.0)
        pl_z = (pl - pl.mean()) / (pl.std(ddof=1) or 1.0)
        cov_b = cov_mat[r_idx]
        Xc = np.column_stack([np.ones(len(yb)), pc_z, cov_b])
        Xl = np.column_stack([np.ones(len(yb)), pl_z, cov_b])
        try:
            mc = sm.GLM(yb, Xc, family=sm.families.Binomial()).fit()
            ml = sm.GLM(yb, Xl, family=sm.families.Binomial()).fit()
            bc = float(mc.params[1])
            bl = float(ml.params[1])
            b_conts.append(bc)
            b_lags.append(bl)
            deltas.append(bc - bl)
        except Exception:
            continue
    arr = np.array(deltas)
    return {
        "seed": seed,
        "n_boot_completed": int(len(arr)),
        "mean_contemp": round(float(np.mean(b_conts)), 5),
        "mean_lag": round(float(np.mean(b_lags)), 5),
        "mean_delta_beta": round(float(np.mean(arr)), 5),
        "sd_delta_beta": round(float(np.std(arr, ddof=1)), 5),
        "ci95_percentile": [round(float(np.percentile(arr, 2.5)), 5), round(float(np.percentile(arr, 97.5)), 5)],
        "prob_delta_gt_0": round(float(np.mean(arr > 0.0)), 4),
        "prob_delta_ge_010": round(float(np.mean(arr >= 0.10)), 4),
        "raw_deltas": [float(x) for x in arr],
    }


def run_mundlak(df: pd.DataFrame, label: str, col: str = "posture") -> Dict:
    d = df.copy()
    raw_sd = float(d[col].std(ddof=1))
    f_mean = d.groupby("LongId")[col].transform("mean")
    d["p_between"] = (f_mean - float(d[col].mean())) / raw_sd
    d["p_within"] = (d[col] - f_mean) / raw_sd

    formula = (
        "breach ~ p_between + p_within + large + C(wave_c)"
        if d["large"].nunique() > 1
        else "breach ~ p_between + p_within + C(wave_c)"
    )
    res = smf.glm(formula, data=d, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": d["LongId"]}
    )
    b_B = float(res.params["p_between"])
    se_B = float(res.bse["p_between"])
    b_W = float(res.params["p_within"])
    se_W = float(res.bse["p_within"])
    cov_BW = float(res.cov_params().loc["p_between", "p_within"])
    diff = b_B - b_W
    se_diff = float(np.sqrt(max(1e-12, se_B ** 2 + se_W ** 2 - 2.0 * cov_BW)))
    z_diff = diff / se_diff
    p_diff = float(2.0 * (1.0 - stats.norm.cdf(abs(z_diff))))

    return {
        "sample_label": label,
        "n": int(len(d)),
        "n_firms": int(d["LongId"].nunique()),
        "beta_between": round(b_B, 5),
        "se_between": round(se_B, 5),
        "ci95_between": [round(b_B - 1.96 * se_B, 5), round(b_B + 1.96 * se_B, 5)],
        "or_between": round(float(np.exp(b_B)), 4),
        "p_between": round(float(res.pvalues["p_between"]), 6),
        "beta_within": round(b_W, 5),
        "se_within": round(se_W, 5),
        "ci95_within": [round(b_W - 1.96 * se_W, 5), round(b_W + 1.96 * se_W, 5)],
        "or_within": round(float(np.exp(b_W)), 4),
        "p_within": round(float(res.pvalues["p_within"]), 6),
        "contrast_between_minus_within": round(diff, 5),
        "se_contrast": round(se_diff, 5),
        "ci95_contrast": [round(diff - 1.96 * se_diff, 5), round(diff + 1.96 * se_diff, 5)],
        "p_wald_equal_slopes": round(p_diff, 6),
    }


def main() -> int:
    data_dir = resolve_data_dir()
    df = load_csls_panel(data_dir)
    full_cc, multi_cc, common = build_common_sample(df)

    common = common.copy()
    common["posture_t_z"] = zscore(common["posture"])
    common["posture_lag_z"] = zscore(common["posture_lag"])
    full_cc["posture_z"] = zscore(full_cc["posture"])
    multi_cc["posture_z"] = zscore(multi_cc["posture"])

    # 1. Core specifications on identical n = 865 (plus full_cc and multi_cc attrition checks)
    m_full_contemp = fit_clustered_logit(full_cc, "breach ~ posture_z + large + C(wave_c)", "posture_z")
    m_multi_contemp = fit_clustered_logit(multi_cc, "breach ~ posture_z + large + C(wave_c)", "posture_z")
    m_common_contemp = fit_clustered_logit(common, "breach ~ posture_t_z + large + C(wave_c)", "posture_t_z")
    m_common_biv = fit_clustered_logit(common, "breach ~ posture_t_z", "posture_t_z")
    m_common_lag = fit_clustered_logit(common, "breach ~ posture_lag_z + large + C(wave_c)", "posture_lag_z")

    # Survey-weighted sensitivity on n = 865
    w_valid = common.dropna(subset=["wght_num"]).copy()
    m_common_contemp_w = fit_clustered_logit(w_valid, "breach ~ posture_t_z + large + C(wave_c)", "posture_t_z", weights=w_valid["wght_num"])
    m_common_lag_w = fit_clustered_logit(w_valid, "breach ~ posture_lag_z + large + C(wave_c)", "posture_lag_z", weights=w_valid["wght_num"])

    # Joint model (breach_t ~ posture_t_z + posture_lag_z + large + C(wave_c))
    res_joint = smf.glm("breach ~ posture_t_z + posture_lag_z + large + C(wave_c)", data=common, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": common["LongId"]}
    )
    m_joint = {
        "n": int(len(common)),
        "beta_posture_t": round(float(res_joint.params["posture_t_z"]), 5),
        "se_posture_t": round(float(res_joint.bse["posture_t_z"]), 5),
        "p_posture_t": round(float(res_joint.pvalues["posture_t_z"]), 6),
        "beta_posture_lag": round(float(res_joint.params["posture_lag_z"]), 5),
        "se_posture_lag": round(float(res_joint.bse["posture_lag_z"]), 5),
        "p_posture_lag": round(float(res_joint.pvalues["posture_lag_z"]), 6),
    }

    # Dynamic panel controlling for lagged breach Y_{i,t-1}
    dyn_df = common.dropna(subset=["breach_lag"]).copy()
    res_dyn = smf.glm("breach ~ posture_lag_z + breach_lag + large + C(wave_c)", data=dyn_df, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": dyn_df["LongId"]}
    )
    ci_b = res_dyn.conf_int().loc["breach_lag"]
    m_dynamic = {
        "n": int(len(dyn_df)),
        "n_firms": int(dyn_df["LongId"].nunique()),
        "beta_posture_lag": round(float(res_dyn.params["posture_lag_z"]), 5),
        "se_posture_lag": round(float(res_dyn.bse["posture_lag_z"]), 5),
        "p_posture_lag": round(float(res_dyn.pvalues["posture_lag_z"]), 6),
        "beta_breach_lag": round(float(res_dyn.params["breach_lag"]), 5),
        "se_breach_lag": round(float(res_dyn.bse["breach_lag"]), 5),
        "ci95_breach_lag": [round(float(ci_b.iloc[0]), 5), round(float(ci_b.iloc[1]), 5)],
        "or_breach_lag": round(float(np.exp(res_dyn.params["breach_lag"])), 4),
        "p_breach_lag": round(float(res_dyn.pvalues["breach_lag"]), 6),
    }

    # Within-firm Fixed Effects LPM on n = 865 (demean within LongId)
    fe_df = common.copy()
    for col in ["breach", "posture_lag_z", "posture_t_z"]:
        fe_df[f"{col}_dm"] = fe_df[col] - fe_df.groupby("LongId")[col].transform("mean")
    res_fe_lag = smf.ols("breach_dm ~ posture_lag_z_dm + C(wave_c)", data=fe_df).fit(
        cov_type="cluster", cov_kwds={"groups": fe_df["LongId"]}
    )
    res_fe_cont = smf.ols("breach_dm ~ posture_t_z_dm + C(wave_c)", data=fe_df).fit(
        cov_type="cluster", cov_kwds={"groups": fe_df["LongId"]}
    )
    m_firm_fe = {
        "n": int(len(fe_df)),
        "n_firms": int(fe_df["LongId"].nunique()),
        "lagged_fe_pp_per_sd": round(float(res_fe_lag.params["posture_lag_z_dm"]) * 100.0, 4),
        "lagged_fe_se_pp": round(float(res_fe_lag.bse["posture_lag_z_dm"]) * 100.0, 4),
        "lagged_fe_p": round(float(res_fe_lag.pvalues["posture_lag_z_dm"]), 6),
        "contemp_fe_pp_per_sd": round(float(res_fe_cont.params["posture_t_z_dm"]) * 100.0, 4),
        "contemp_fe_se_pp": round(float(res_fe_cont.bse["posture_t_z_dm"]) * 100.0, 4),
        "contemp_fe_p": round(float(res_fe_cont.pvalues["posture_t_z_dm"]), 6),
    }

    # 2. Stacked Wald + 5 seeds x 400 = 2,000 firm-cluster bootstrap resamples
    stacked_wald = stacked_delta_beta_wald(common)
    boot_seeds = [202711, 202712, 202713, 202714, 202715]
    per_seed_boot = []
    all_boot_deltas: List[float] = []
    for bsd in boot_seeds:
        br = cluster_bootstrap_delta_beta(common, n_boot=400, seed=bsd)
        all_boot_deltas.extend(br["raw_deltas"])
        per_seed_boot.append({k: v for k, v in br.items() if k != "raw_deltas"})
    arr_2000 = np.array(all_boot_deltas)
    pooled_boot_2000 = {
        "total_resamples": int(len(arr_2000)),
        "point_delta_beta": round(m_common_contemp["beta"] - m_common_lag["beta"], 5),
        "boot_mean_delta_beta": round(float(np.mean(arr_2000)), 5),
        "boot_sd_delta_beta": round(float(np.std(arr_2000, ddof=1)), 5),
        "boot_ci95": [round(float(np.percentile(arr_2000, 2.5)), 5), round(float(np.percentile(arr_2000, 97.5)), 5)],
        "prob_delta_gt_0": round(float(np.mean(arr_2000 > 0.0)), 4),
        "prob_delta_ge_010": round(float(np.mean(arr_2000 >= 0.10)), 4),
    }

    # 3. Mundlak correlated random-effects decomposition on clean genuine panel (n = 865, 575 firms) and full business frame (N = 3,061, 2,196 firms)
    mundlak_common_lagged = run_mundlak(common, "clean_panel_n865_prewindow_lagged", col="posture_lag")
    mundlak_common_contemp = run_mundlak(common, "clean_panel_n865_contemporaneous", col="posture")
    mundlak_multi = run_mundlak(multi_cc, "multiwave_n1454_contemporaneous", col="posture")
    mundlak_full = run_mundlak(full_cc, "full_business_n3061_contemporaneous", col="posture")

    # Stacked firm-cluster-robust GLM test of Full-Panel Between-Firm Salience (N=3,061) minus Clean Lagged Within-Firm Posture (n=865)
    fc_s = full_cc[["LongId", "breach", "large", "wave_c", "posture"]].copy()
    raw_sd_f = float(fc_s["posture"].std(ddof=1))
    f_m_f = fc_s.groupby("LongId")["posture"].transform("mean")
    fc_s["arm_full"] = 1.0
    fc_s["p_ focal"] = (f_m_f - float(fc_s["posture"].mean())) / raw_sd_f
    fc_s["p_aux"] = (fc_s["posture"] - f_m_f) / raw_sd_f

    cm_s = common[["LongId", "breach", "large", "wave_c", "posture_lag"]].copy()
    raw_sd_c = float(cm_s["posture_lag"].std(ddof=1))
    f_m_c = cm_s.groupby("LongId")["posture_lag"].transform("mean")
    cm_s["arm_full"] = 0.0
    cm_s["p_ focal"] = (cm_s["posture_lag"] - f_m_c) / raw_sd_c
    cm_s["p_aux"] = (f_m_c - float(cm_s["posture_lag"].mean())) / raw_sd_c

    st_bw = pd.concat(
        [
            fc_s[["LongId", "breach", "large", "wave_c", "arm_full", "p_ focal", "p_aux"]].rename(columns={"p_ focal": "p_focal"}),
            cm_s[["LongId", "breach", "large", "wave_c", "arm_full", "p_ focal", "p_aux"]].rename(columns={"p_ focal": "p_focal"}),
        ],
        ignore_index=True,
    )
    st_bw["arm_lag"] = 1.0 - st_bw["arm_full"]
    res_st_bw = smf.glm(
        "breach ~ p_focal + arm_full:p_focal + arm_full:p_aux + arm_lag:p_aux + arm_full * (large + C(wave_c))",
        data=st_bw,
        family=sm.families.Binomial(),
    ).fit(cov_type="cluster", cov_kwds={"groups": st_bw["LongId"]})
    bw_diff = float(res_st_bw.params["arm_full:p_focal"])
    bw_se = float(res_st_bw.bse["arm_full:p_focal"])
    bw_z = bw_diff / bw_se
    bw_p = float(2.0 * (1.0 - stats.norm.cdf(abs(bw_z))))
    stacked_between_minus_lagwithin = {
        "n_full": int(len(full_cc)),
        "n_lag": int(len(common)),
        "n_clusters": int(st_bw["LongId"].nunique()),
        "beta_full_between": mundlak_full["beta_between"],
        "beta_clean_lag_within": mundlak_common_lagged["beta_within"],
        "contrast_between_minus_lag_within": round(bw_diff, 5),
        "se_contrast": round(bw_se, 5),
        "ci95_contrast": [round(bw_diff - 1.96 * bw_se, 5), round(bw_diff + 1.96 * bw_se, 5)],
        "z_stat": round(bw_z, 4),
        "p_wald": round(bw_p, 6),
    }

    # Full-panel Mundlak split by Medium SME (50-249) vs Large (250+)
    mundlak_full_medium = run_mundlak(full_cc[full_cc["large"] == 0.0], "full_medium_sme_50_249", col="posture")
    mundlak_full_large = run_mundlak(full_cc[full_cc["large"] == 1.0], "full_large_250_plus", col="posture")

    adj865 = common[common["wave_gap"] == 1].copy()
    adj865["posture_t_z"] = zscore(adj865["posture"])
    adj865["posture_lag_z"] = zscore(adj865["posture_lag"])
    adj865_contemp = fit_clustered_logit(adj865, "breach ~ posture_t_z + large + C(wave_c)", "posture_t_z")
    adj865_lag = fit_clustered_logit(adj865, "breach ~ posture_lag_z + large + C(wave_c)", "posture_lag_z")
    adj865_wald = stacked_delta_beta_wald(adj865)

    # Also Mundlak conditioning on lagged breach Y_{i,t-1}
    raw_sd_d = float(dyn_df["posture_lag"].std(ddof=1))
    f_mean_dl = dyn_df.groupby("LongId")["posture_lag"].transform("mean")
    dyn_df["p_between"] = (f_mean_dl - float(dyn_df["posture_lag"].mean())) / raw_sd_d
    dyn_df["p_within"] = (dyn_df["posture_lag"] - f_mean_dl) / raw_sd_d
    res_mund_dyn = smf.glm("breach ~ p_between + p_within + breach_lag + large + C(wave_c)", data=dyn_df, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": dyn_df["LongId"]}
    )
    mundlak_controlling_prior_breach = {
        "n": int(len(dyn_df)),
        "beta_between": round(float(res_mund_dyn.params["p_between"]), 5),
        "se_between": round(float(res_mund_dyn.bse["p_between"]), 5),
        "p_between": round(float(res_mund_dyn.pvalues["p_between"]), 6),
        "beta_within": round(float(res_mund_dyn.params["p_within"]), 5),
        "se_within": round(float(res_mund_dyn.bse["p_within"]), 5),
        "p_within": round(float(res_mund_dyn.pvalues["p_within"]), 6),
    }

    # 4. Cross-lagged reverse-causation check: posture_t and Delta_posture_t on breach_{t-1}
    dyn_df["delta_posture"] = dyn_df["posture"] - dyn_df["posture_lag"]
    res_rev_lvl = smf.ols("posture ~ breach_lag + posture_lag + large + C(wave_c)", data=dyn_df).fit(
        cov_type="cluster", cov_kwds={"groups": dyn_df["LongId"]}
    )
    res_rev_chg = smf.ols("delta_posture ~ breach_lag + large + C(wave_c)", data=dyn_df).fit(
        cov_type="cluster", cov_kwds={"groups": dyn_df["LongId"]}
    )
    reverse_causation = {
        "n": int(len(dyn_df)),
        "breach_lag_to_posture_t_coef": round(float(res_rev_lvl.params["breach_lag"]), 5),
        "breach_lag_to_posture_t_se": round(float(res_rev_lvl.bse["breach_lag"]), 5),
        "breach_lag_to_posture_t_p": round(float(res_rev_lvl.pvalues["breach_lag"]), 6),
        "breach_lag_to_delta_posture_coef": round(float(res_rev_chg.params["breach_lag"]), 5),
        "breach_lag_to_delta_posture_se": round(float(res_rev_chg.bse["breach_lag"]), 5),
        "breach_lag_to_delta_posture_p": round(float(res_rev_chg.pvalues["breach_lag"]), 6),
    }

    # 5. Firm-trajectory placebo permutation test (500 shuffles, seed 202720)
    # Permutes entire firm posture trajectories across firms sharing the exact (wave_c, large)
    # sequence signature so within-firm serial correlation and within-firm SD are 100% preserved.
    rng_pl = np.random.default_rng(202720)
    c_pl = common.sort_values(["LongId", "wave_c"]).reset_index(drop=True)
    f_pl = full_cc.sort_values(["LongId", "wave_c"]).reset_index(drop=True)
    yc_pl = c_pl["breach"].to_numpy(dtype=float)
    yf_pl = f_pl["breach"].to_numpy(dtype=float)
    cov_c_pl = pd.get_dummies(c_pl[["large", "wave_c"]], drop_first=True, dtype=float).to_numpy()
    cov_f_pl = pd.get_dummies(f_pl[["large", "wave_c"]], drop_first=True, dtype=float).to_numpy()

    def build_firm_sig_groups(df_sorted: pd.DataFrame):
        firm_rows: List[np.ndarray] = []
        sig_to_firms: Dict[tuple, List[int]] = {}
        for _, g in df_sorted.groupby("LongId", sort=False):
            idx = g.index.to_numpy(dtype=int)
            fid = len(firm_rows)
            firm_rows.append(idx)
            sig = (tuple(g["wave_c"].tolist()), tuple(g["large"].tolist()))
            sig_to_firms.setdefault(sig, []).append(fid)
        # Fallback merge for any singleton signature by wave-sequence alone so singleton trajectories still permute
        singleton_by_w: Dict[tuple, List[int]] = {}
        final_groups: List[np.ndarray] = []
        for sig, fids in sig_to_firms.items():
            if len(fids) >= 2:
                final_groups.append(np.asarray(fids, dtype=int))
            else:
                singleton_by_w.setdefault(sig[0], []).extend(fids)
        for fids in singleton_by_w.values():
            final_groups.append(np.asarray(fids, dtype=int))
        return firm_rows, final_groups

    c_firm_rows, c_sig_groups = build_firm_sig_groups(c_pl)
    f_firm_rows, f_sig_groups = build_firm_sig_groups(f_pl)

    lid_c_codes, _ = pd.factorize(c_pl["LongId"])
    n_lid_c = int(lid_c_codes.max() + 1)
    cnt_lid_c = np.bincount(lid_c_codes, minlength=n_lid_c).astype(float)
    lid_f_codes, _ = pd.factorize(f_pl["LongId"])
    n_lid_f = int(lid_f_codes.max() + 1)
    cnt_lid_f = np.bincount(lid_f_codes, minlength=n_lid_f).astype(float)
    pc_orig = c_pl["posture"].to_numpy(dtype=float)
    pl_orig = c_pl["posture_lag"].to_numpy(dtype=float)
    pf_orig = f_pl["posture"].to_numpy(dtype=float)
    raw_sd_s = float(pl_orig.std(ddof=1))
    raw_sd_f_pl = float(pf_orig.std(ddof=1))

    placebo_deltas, placebo_mundlak_contrasts, placebo_full_between, placebo_stacked_contrasts = [], [], [], []
    for _ in range(500):
        pc_s = pc_orig.copy()
        pl_s = pl_orig.copy()
        for fgrp in c_sig_groups:
            if len(fgrp) > 1:
                perm_f = rng_pl.permutation(fgrp)
                for dst_f, src_f in zip(fgrp, perm_f):
                    pc_s[c_firm_rows[dst_f]] = pc_orig[c_firm_rows[src_f]]
                    pl_s[c_firm_rows[dst_f]] = pl_orig[c_firm_rows[src_f]]
        pc_sz = (pc_s - pc_s.mean()) / (pc_s.std(ddof=1) or 1.0)
        pl_sz = (pl_s - pl_s.mean()) / (pl_s.std(ddof=1) or 1.0)
        mc_p = sm.GLM(yc_pl, np.column_stack([np.ones(len(yc_pl)), pc_sz, cov_c_pl]), family=sm.families.Binomial()).fit()
        ml_p = sm.GLM(yc_pl, np.column_stack([np.ones(len(yc_pl)), pl_sz, cov_c_pl]), family=sm.families.Binomial()).fit()
        placebo_deltas.append(float(mc_p.params[1] - ml_p.params[1]))

        f_ms = (np.bincount(lid_c_codes, weights=pl_s, minlength=n_lid_c) / cnt_lid_c)[lid_c_codes]
        pb_c = (f_ms - pl_s.mean()) / raw_sd_s
        pw_c = (pl_s - f_ms) / raw_sd_s
        mm_p = sm.GLM(yc_pl, np.column_stack([np.ones(len(yc_pl)), pb_c, pw_c, cov_c_pl]), family=sm.families.Binomial()).fit()
        placebo_mundlak_contrasts.append(float(mm_p.params[1] - mm_p.params[2]))

        pf_s = pf_orig.copy()
        for fgrp in f_sig_groups:
            if len(fgrp) > 1:
                perm_f = rng_pl.permutation(fgrp)
                for dst_f, src_f in zip(fgrp, perm_f):
                    pf_s[f_firm_rows[dst_f]] = pf_orig[f_firm_rows[src_f]]
        f_mf = (np.bincount(lid_f_codes, weights=pf_s, minlength=n_lid_f) / cnt_lid_f)[lid_f_codes]
        pb_f = (f_mf - pf_s.mean()) / raw_sd_f_pl
        pw_f = (pf_s - f_mf) / raw_sd_f_pl
        mf_p = sm.GLM(yf_pl, np.column_stack([np.ones(len(yf_pl)), pb_f, pw_f, cov_f_pl]), family=sm.families.Binomial()).fit()
        placebo_full_between.append(float(mf_p.params[1]))
        placebo_stacked_contrasts.append(float(mf_p.params[1] - mm_p.params[2]))

    obs_delta = m_common_contemp["beta"] - m_common_lag["beta"]
    obs_mund = mundlak_common_lagged["contrast_between_minus_within"]
    obs_fb = mundlak_full["beta_between"]
    obs_stacked = stacked_between_minus_lagwithin["contrast_between_minus_lag_within"]
    placebo_summary = {
        "n_permutations": 500,
        "seed": 202720,
        "permutation_unit": "whole_firm_trajectory_within_wave_size_signature",
        "placebo_delta_beta_mean": round(float(np.mean(placebo_deltas)), 5),
        "placebo_delta_beta_p95": round(float(np.percentile(placebo_deltas, 95)), 5),
        "empirical_p_delta_beta": round(float((np.sum(np.array(placebo_deltas) >= obs_delta) + 1) / 501.0), 5),
        "placebo_mundlak_contrast_n865_mean": round(float(np.mean(placebo_mundlak_contrasts)), 5),
        "placebo_mundlak_contrast_n865_p95": round(float(np.percentile(placebo_mundlak_contrasts, 95)), 5),
        "empirical_p_mundlak_contrast_n865": round(float((np.sum(np.array(placebo_mundlak_contrasts) >= obs_mund) + 1) / 501.0), 5),
        "placebo_full_between_mean": round(float(np.mean(placebo_full_between)), 5),
        "empirical_p_full_between": round(float((np.sum(np.array(placebo_full_between) >= obs_fb) + 1) / 501.0), 5),
        "placebo_stacked_contrast_mean": round(float(np.mean(placebo_stacked_contrasts)), 5),
        "placebo_stacked_contrast_p95": round(float(np.percentile(placebo_stacked_contrasts, 95)), 5),
        "empirical_p_stacked_contrast": round(float((np.sum(np.array(placebo_stacked_contrasts) >= obs_stacked) + 1) / 501.0), 5),
    }

    # Export clean CSVs for ve-tikz-v6 Figure 3
    fig3_rows = [
        {
            "model_id": "full_contemp_3061",
            "label": "Contemp_Full_N3061",
            "n": m_full_contemp["n"],
            "beta": m_full_contemp["beta"],
            "ci_lo": m_full_contemp["ci95_beta"][0],
            "ci_hi": m_full_contemp["ci95_beta"][1],
            "or_val": m_full_contemp["or"],
            "p_val": m_full_contemp["p"],
        },
        {
            "model_id": "mundlak_full_between_3061",
            "label": "Mundlak_Between_N3061",
            "n": mundlak_full["n"],
            "beta": mundlak_full["beta_between"],
            "ci_lo": mundlak_full["ci95_between"][0],
            "ci_hi": mundlak_full["ci95_between"][1],
            "or_val": mundlak_full["or_between"],
            "p_val": mundlak_full["p_between"],
        },
        {
            "model_id": "common_contemp_865",
            "label": "Contemp_Common_n865",
            "n": m_common_contemp["n"],
            "beta": m_common_contemp["beta"],
            "ci_lo": m_common_contemp["ci95_beta"][0],
            "ci_hi": m_common_contemp["ci95_beta"][1],
            "or_val": m_common_contemp["or"],
            "p_val": m_common_contemp["p"],
        },
        {
            "model_id": "common_lagged_865",
            "label": "Lagged_Common_n865",
            "n": m_common_lag["n"],
            "beta": m_common_lag["beta"],
            "ci_lo": m_common_lag["ci95_beta"][0],
            "ci_hi": m_common_lag["ci95_beta"][1],
            "or_val": m_common_lag["or"],
            "p_val": m_common_lag["p"],
        },
        {
            "model_id": "mundlak_lag_within_865",
            "label": "Mundlak_WithinLag_n865",
            "n": mundlak_common_lagged["n"],
            "beta": mundlak_common_lagged["beta_within"],
            "ci_lo": mundlak_common_lagged["ci95_within"][0],
            "ci_hi": mundlak_common_lagged["ci95_within"][1],
            "or_val": mundlak_common_lagged["or_within"],
            "p_val": mundlak_common_lagged["p_within"],
        },
        {
            "model_id": "stacked_bw_contrast",
            "label": "Between_Minus_WithinLag",
            "n": stacked_between_minus_lagwithin["n_clusters"],
            "beta": stacked_between_minus_lagwithin["contrast_between_minus_lag_within"],
            "ci_lo": stacked_between_minus_lagwithin["ci95_contrast"][0],
            "ci_hi": stacked_between_minus_lagwithin["ci95_contrast"][1],
            "or_val": round(float(np.exp(stacked_between_minus_lagwithin["contrast_between_minus_lag_within"])), 4),
            "p_val": stacked_between_minus_lagwithin["p_wald"],
        },
    ]
    pd.DataFrame(fig3_rows).to_csv(SUMMARY_DIR / "fig3_common_sample_models.csv", index=False)

    # Histogram bins of the 2,000 bootstrap delta_beta draws for Figure 3 panel B
    hist_counts, hist_edges = np.histogram(arr_2000, bins=24)
    hist_df = pd.DataFrame({
        "bin_center": np.round(0.5 * (hist_edges[:-1] + hist_edges[1:]), 4),
        "density": np.round(hist_counts / len(arr_2000), 5),
        "count": hist_counts,
    })
    hist_df.to_csv(SUMMARY_DIR / "fig3_bootstrap_delta_beta.csv", index=False)

    out = {
        "claim_ids": ["K3", "K3b"],
        "models": {
            "full_business_contemporaneous_N3061": m_full_contemp,
            "multiwave_contemporaneous_n1454": m_multi_contemp,
            "common_sample_bivariate_contemp_n865": m_common_biv,
            "common_sample_contemporaneous_n865": m_common_contemp,
            "common_sample_lagged_n865": m_common_lag,
            "common_sample_weighted_contemp": m_common_contemp_w,
            "common_sample_weighted_lagged": m_common_lag_w,
            "common_sample_joint_t_and_lag": m_joint,
            "common_sample_dynamic_with_breach_lag": m_dynamic,
            "common_sample_within_firm_fe_lpm": m_firm_fe,
            "adjacent_wave_gap1_robustness_n865": {
                "contemporaneous": adj865_contemp,
                "lagged": adj865_lag,
                "stacked_wald": adj865_wald,
            },
        },
        "delta_beta_tests": {
            "stacked_glm_wald": stacked_wald,
            "firm_cluster_bootstrap_2000": pooled_boot_2000,
            "per_seed_bootstrap_400x5": per_seed_boot,
        },
        "mundlak_decomposition": {
            "clean_n865_prewindow_lagged": mundlak_common_lagged,
            "clean_n865_contemporaneous": mundlak_common_contemp,
            "multiwave_n1454_contemporaneous": mundlak_multi,
            "full_n3061_contemporaneous": mundlak_full,
            "full_medium_sme_50_249": mundlak_full_medium,
            "full_large_250_plus": mundlak_full_large,
            "stacked_full_between_minus_clean_lag_within": stacked_between_minus_lagwithin,
            "controlling_prior_breach": mundlak_controlling_prior_breach,
        },
        "reverse_causation_cross_lagged": reverse_causation,
        "placebo_permutation_500": placebo_summary,
    }
    out_file = OUT_DIR / "exp2_common_sample_and_mechanisms.json"
    out_file.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(
        f"[exp2] Common n={m_common_contemp['n']} ({m_common_contemp['n_firms']} firms): "
        f"beta_contemp={m_common_contemp['beta']:+.4f} (OR={m_common_contemp['or']:.3f}, p={m_common_contemp['p']:.4f}) vs "
        f"beta_lag={m_common_lag['beta']:+.4f} (OR={m_common_lag['or']:.3f}, p={m_common_lag['p']:.4f}) | "
        f"delta_beta={stacked_wald['delta_beta_log_odds']:+.4f} (Wald p={stacked_wald['p_wald']:.5f}; "
        f"boot2000 CI={pooled_boot_2000['boot_ci95']}) | "
        f"Mundlak Full N={mundlak_full['n']}: beta_B={mundlak_full['beta_between']:+.4f} (p={mundlak_full['p_between']:.5f}) | "
        f"Mundlak Lag n={mundlak_common_lagged['n']}: beta_W={mundlak_common_lagged['beta_within']:+.4f} (p={mundlak_common_lagged['p_within']:.4f}) | "
        f"Stacked contrast={stacked_between_minus_lagwithin['contrast_between_minus_lag_within']:+.4f} "
        f"(p={stacked_between_minus_lagwithin['p_wald']:.4f}, placebo_p={placebo_summary['empirical_p_stacked_contrast']:.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
