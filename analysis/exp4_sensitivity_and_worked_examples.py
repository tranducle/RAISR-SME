#!/usr/bin/env python3
"""Experiment 4 (Claims K1, K1d, K4): Two-stage Monte Carlo latent-truth concordance, 2x2 ablation,
Dirichlet sensitivity, cross-runtime IEEE-754 parity, and 18-employee SME worked diagnostic trace.

Usage:
    python3 exp4_sensitivity_and_worked_examples.py pilot
    python3 exp4_sensitivity_and_worked_examples.py official
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BANK_PATH = REPO / "instrument" / "bank_v1.json"
SCORING_PY = REPO / "instrument" / "scoring.py"
SCORING_JS = REPO / "instrument" / "scoring.js"
OUT_DIR = HERE / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_DIR = Path(os.environ.get("RAISR_SUMMARY_DIR", str(OUT_DIR / "summaries")))
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO / "instrument"))
import scoring as ref_scoring  # noqa: E402


def resolve_data_dir() -> Path:
    env_dir = os.environ.get("RAISR_DATA_DIR")
    if env_dir and Path(env_dir).exists():
        return Path(env_dir)
    cand1 = REPO / "data"
    if (cand1 / "UKDA-9404-stata").exists():
        return cand1
    cand2 = REPO.parent / "data"
    if (cand2 / "UKDA-9404-stata").exists():
        return cand2
    raise FileNotFoundError("Could not locate UKDA data folder under data/ or RAISR_DATA_DIR")


def load_empirical_marginals(data_dir: Path, bank: Dict) -> Dict:
    """Extract empirical SME gap and Don't-know marginals from UK CSBS 2025 + Eurostat isoc_eb_ai."""
    csbs_path = data_dir / "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta"
    df = pd.read_stata(csbs_path, convert_categoricals=True)
    size_col = "sizeb" if "sizeb" in df.columns else "sizeb_comb2"
    na_labels = {"Not asked", "Not applicable", "Don't know", "Refused", "n/a"}
    biz = df[~df[size_col].astype(str).isin(na_labels)].copy()
    biz["sz"] = biz[size_col].astype(str)

    def rate_no_and_dk(sub: pd.DataFrame, col: str, no_vals: set) -> Tuple[float, float]:
        if col not in sub.columns:
            return 0.52, 0.14
        s = sub[col].astype(str)
        asked = ~s.isin({"Not asked", "Not applicable", "nan"})
        s_a = s[asked]
        if len(s_a) == 0:
            return 0.52, 0.14
        dk_rate = float(s_a.isin({"Don't know", "Refused"}).mean())
        valid = s_a[~s_a.isin({"Don't know", "Refused"})]
        gap_rate = float(valid.isin(no_vals).mean()) if len(valid) > 0 else 0.52
        return gap_rate, dk_rate

    euro_path = data_dir / "eurostat/isoc_eb_ai.json"
    euro = json.loads(euro_path.read_text(encoding="utf-8"))
    edims = euro["dimension"]
    eids = euro["id"]
    esizes = euro["size"]

    def euro_val(sz_code: str, indic: str) -> float:
        idx = 0
        coord = {
            "freq": "A",
            "size_emp": sz_code,
            "nace_r2": "C10-S951_X_K",
            "indic_is": indic,
            "unit": "PC_ENT",
            "geo": "EU27_2020",
            "time": "2025",
        }
        for dname, dsz in zip(eids, esizes):
            idx = idx * dsz + edims[dname]["category"]["index"][coord[dname]]
        val = euro["value"].get(str(idx))
        return float(val) / 100.0 if val is not None else 0.17

    ai_small_any = euro_val("10-49", "E_AI_TANY")
    ai_med_any = euro_val("50-249", "E_AI_TANY")
    ai_small_nlg = euro_val("10-49", "E_AI_TNLG")
    ai_med_nlg = euro_val("50-249", "E_AI_TNLG")

    strata_specs = {}
    for label, exact_sz, ai_any, ai_nlg, weight_share, dk_boost in [
        ("micro_1_9", "Micro (1 to 9)", max(0.14, ai_small_any * 0.85), max(0.08, ai_small_nlg * 1.15), 0.58, 0.16),
        ("small_10_49", "Small (10 to 49)", ai_small_any, ai_small_nlg, 0.28, 0.11),
        ("medium_50_249", "Medium (50 to 249)", ai_med_any, ai_med_nlg, 0.14, 0.07),
    ]:
        sub = biz[biz["sz"] == exact_sz]
        if len(sub) < 30:
            sub = biz
        pol_gap, _ = rate_no_and_dk(sub, "manage3", {"No"})       # formal cyber policy
        trn_gap, trn_dk = rate_no_and_dk(sub, "trained", {"No"})  # staff training
        ins_gap, ins_dk = rate_no_and_dk(
            sub,
            "insurex",
            {
                "We are not insured against cyber security breaches or attacks",
                "No",
                "Not insured",
                "We do not have any cyber security insurance",
            },
        )
        iam_gap, _ = rate_no_and_dk(sub, "Step6", {"No"})         # access/admin control
        vln_gap, _ = rate_no_and_dk(sub, "Step5", {"No"})         # vulnerability/patching
        ast_gap, _ = rate_no_and_dk(sub, "Step3", {"No"})         # asset/data inventory
        gov1_gap, _ = rate_no_and_dk(sub, "manage1", {"No"})      # board responsibility
        gov2_gap, _ = rate_no_and_dk(sub, "manage2", {"No"})      # risk review
        gov4_gap, _ = rate_no_and_dk(sub, "manage4", {"No"})      # documented policies
        sup_gap, _ = rate_no_and_dk(sub, "supplyrisk_any", {"No"})  # supplier risk review
        inc1_gap, inc1_dk = rate_no_and_dk(sub, "Step9", {"No"})  # incident management
        inc2_gap, inc2_dk = rate_no_and_dk(sub, "incidactionb", {"No"})
        inc3_gap, inc3_dk = rate_no_and_dk(sub, "incidactionh", {"No"})

        base_dk = float(np.clip((trn_dk + ins_dk + inc3_dk) / 3.0 + dk_boost, 0.12, 0.34))
        item_probs = {}
        dk_probs = {}
        for dname, dspec in bank["dimensions"].items():
            for idx_it, it in enumerate(dspec["items"]):
                iid = it["id"]
                if dname == "security_hygiene":
                    p_risk = [pol_gap, trn_gap, ins_gap, ast_gap * 0.72, iam_gap, vln_gap * 0.65][idx_it]
                    p_dk = [base_dk * 0.75, max(trn_dk, base_dk * 0.70), max(ins_dk, base_dk), base_dk * 0.90, base_dk * 0.95, base_dk * 0.85][idx_it]
                elif dname == "incident_readiness":
                    p_risk = [inc1_gap, inc2_gap, inc3_gap, vln_gap][idx_it]
                    p_dk = [base_dk * 0.95, max(inc2_dk, base_dk), max(inc3_dk, base_dk * 1.15), base_dk * 1.25][idx_it]
                elif dname == "ai_exposure":
                    # Active unmanaged AI exposure among SMEs (including shadow GenAI usage by staff)
                    p_risk = [min(0.72, ai_any * 1.85), min(0.68, ai_any * 1.55), min(0.64, ai_nlg * 2.40 + 0.18), min(0.70, ai_any * 1.65)][idx_it]
                    p_dk = base_dk * 1.35
                elif dname == "governance":
                    p_risk = [gov1_gap, gov2_gap, gov4_gap, sup_gap, (gov1_gap + inc2_gap) * 0.5][idx_it]
                    p_dk = base_dk * 1.05
                elif dname == "data_handling":
                    p_risk = [ast_gap, inc3_gap * 0.92, ast_gap * 0.95][idx_it]
                    p_dk = base_dk * 1.15
                else:  # vendor_dependence
                    if it["risk_when"] == "yes":
                        p_risk = 0.74 if label == "micro_1_9" else (0.66 if label == "small_10_49" else 0.56)
                    else:
                        p_risk = [0.70, ast_gap, sup_gap][idx_it]
                    p_dk = base_dk * 1.25
                item_probs[iid] = float(np.clip(p_risk, 0.08, 0.92))
                dk_probs[iid] = float(np.clip(p_dk, 0.08, 0.42))
        strata_specs[label] = {
            "n_csbs": int(len(sub)),
            "share": weight_share,
            "ai_any_eurostat": float(ai_any),
            "ai_nlg_eurostat": float(ai_nlg),
            "item_risk_prob": item_probs,
            "item_dk_prob": dk_probs,
        }
    return strata_specs


def band_index(band: str) -> int:
    return {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}[band]


def band_from_score(val: float, cuts: Tuple[float, float, float] = (40.0, 65.0, 85.0)) -> int:
    q = round(val * 1e9) / 1e9
    if q < cuts[0]:
        return 0
    if q < cuts[1]:
        return 1
    if q < cuts[2]:
        return 2
    return 3


def generate_two_stage_cohort(
    n_profiles: int,
    strata_specs: Dict,
    bank: Dict,
    seed: int,
    rho_ai_gov: float = 0.0,
    mnar_strength: float = 0.0,
) -> Dict:
    """Stage 1: latent binary hazard matrix Z in {0, 1}^{N x 25} via Gaussian copula.
       Stage 2: observed answers A in {0=no, 1=yes, 2=dk}^{N x 25} under MCAR or MNAR opacity.
    """
    rng = np.random.default_rng(seed)
    dim_keys = list(bank["dimensions"].keys())
    items_flat = [(d, it["id"], it["risk_when"]) for d in dim_keys for it in bank["dimensions"][d]["items"]]
    k_items = len(items_flat)

    # Build latent correlation matrix: positive within cyber/governance blocks, controllable rho_ai_gov with AI
    corr = np.eye(k_items)
    for i in range(k_items):
        for j in range(i + 1, k_items):
            di, _, _ = items_flat[i]
            dj, _, _ = items_flat[j]
            ai_i = di == "ai_exposure"
            ai_j = dj == "ai_exposure"
            if ai_i and ai_j:
                c = 0.55
            elif (not ai_i) and (not ai_j):
                c = 0.42 if di == dj else 0.28
            else:
                c = rho_ai_gov
            corr[i, j] = corr[j, i] = c
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = np.maximum(eigvals, 1e-4)
    corr_psd = eigvecs @ np.diag(eigvals) @ eigvecs.T
    d_inv = np.diag(1.0 / np.sqrt(np.diag(corr_psd)))
    corr_psd = d_inv @ corr_psd @ d_inv
    chol = np.linalg.cholesky(corr_psd)

    strata_names = list(strata_specs.keys())
    shares = [strata_specs[s]["share"] for s in strata_names]
    chosen_strata = rng.choice(strata_names, size=n_profiles, p=shares)

    z_normals = rng.standard_normal((n_profiles, k_items)) @ chol.T
    u_vals = stats.norm.cdf(z_normals)

    Z = np.zeros((n_profiles, k_items), dtype=np.float64)
    M_dk = np.zeros((n_profiles, k_items), dtype=bool)
    p_mat = np.zeros((n_profiles, k_items), dtype=np.float64)

    for idx_s, sname in enumerate(strata_names):
        mask_s = chosen_strata == sname
        if not np.any(mask_s):
            continue
        p_vec = np.array([strata_specs[sname]["item_risk_prob"][iid] for _, iid, _ in items_flat])
        dk_vec = np.array([strata_specs[sname]["item_dk_prob"][iid] for _, iid, _ in items_flat])
        Z[mask_s] = (u_vals[mask_s] < p_vec[None, :]).astype(np.float64)
        p_mat[mask_s] = p_vec[None, :]
        if mnar_strength > 0.0:
            # Informative MNAR: unmitigated gaps (Z=1) have elevated probability of respondent DK
            dk_eff = np.clip(dk_vec[None, :] * (1.0 + mnar_strength * (Z[mask_s] - p_vec[None, :])), 0.02, 0.65)
        else:
            dk_eff = np.broadcast_to(dk_vec[None, :], ( int(mask_s.sum()), k_items ))
        M_dk[mask_s] = rng.random((int(mask_s.sum()), k_items)) < dk_eff

    # Raw answers: 1 = Yes, 0 = No, -1 = DK
    raw_yes = np.zeros_like(Z)
    for j, (_, _, rwhen) in enumerate(items_flat):
        if rwhen == "yes":
            raw_yes[:, j] = Z[:, j]
        else:
            raw_yes[:, j] = 1.0 - Z[:, j]

    return {
        "Z": Z,
        "M_dk": M_dk,
        "raw_yes": raw_yes,
        "items_flat": items_flat,
        "strata": chosen_strata,
        "empirical_p": Z.mean(axis=0),
    }


def score_matrix(
    risk_mat: np.ndarray,
    bank: Dict,
    weights_vec: np.ndarray,
    avail_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Compute quantized [0, 100] composite scores matching bank dictionary order."""
    dim_keys = list(bank["dimensions"].keys())
    n_prof = risk_mat.shape[0]
    dim_scores = np.zeros((n_prof, len(dim_keys)), dtype=np.float64)
    offset = 0
    for d_idx, dname in enumerate(dim_keys):
        m_d = len(bank["dimensions"][dname]["items"])
        sub = risk_mat[:, offset : offset + m_d]
        if avail_mask is None:
            acc = np.zeros(n_prof, dtype=np.float64)
            for j in range(m_d):
                acc = acc + sub[:, j]
            dim_scores[:, d_idx] = (acc / m_d) * 100.0
        else:
            am = avail_mask[:, offset : offset + m_d]
            counts = am.sum(axis=1)
            sums = (sub * am).sum(axis=1)
            # If an entire dimension is DK under available-case, fall back to 50.0 midpoint
            dim_scores[:, d_idx] = np.where(counts > 0, (sums / np.maximum(counts, 1)) * 100.0, 50.0)
        offset += m_d
    totals = np.zeros(n_prof, dtype=np.float64)
    for d_idx in range(len(dim_keys)):
        totals = totals + dim_scores[:, d_idx] * weights_vec[d_idx]
    return np.round(totals * 1e9) / 1e9


def compute_consensus_reference_bands(Z: np.ndarray, bank: Dict, w_norm: np.ndarray, seed: int, n_draws: int = 500) -> np.ndarray:
    """Unmasked latent ground-truth consensus tier B*(Z) across wide Dirichlet(alpha_0 = 5) simplex draws."""
    rng = np.random.default_rng(seed)
    alpha = 5.0 * w_norm
    draws = rng.dirichlet(alpha, size=n_draws)
    n_prof = Z.shape[0]
    votes = np.zeros((n_prof, 4), dtype=np.int32)
    for m in range(n_draws):
        sc = score_matrix(Z, bank, draws[m])
        b = np.digitize(sc, [40.0, 65.0, 85.0], right=False)
        for c in range(4):
            votes[:, c] += (b == c)
    return np.argmax(votes, axis=1)


def evaluate_cohort(cohort: Dict, bank: Dict, seed: int, n_ref_draws: int = 500) -> Dict:
    Z = cohort["Z"]
    M_dk = cohort["M_dk"]
    raw_yes = cohort["raw_yes"]
    emp_p = cohort["empirical_p"]
    dim_keys = list(bank["dimensions"].keys())
    w_norm = np.array([bank["weights"][d] for d in dim_keys], dtype=np.float64)

    ref_bands = compute_consensus_reference_bands(Z, bank, w_norm, seed=seed + 99, n_draws=n_ref_draws)

    # Build risk matrices for each method/ablation
    r_full = np.where(M_dk, 0.5, Z)
    r_dk0_aligned = np.where(M_dk, 0.0, Z)
    r_dk1_aligned = np.where(M_dk, 1.0, Z)
    r_single_pol_raw = 1.0 - raw_yes  # treats Yes=0, No=1 on ALL 25 items
    r_single_dk05 = np.where(M_dk, 0.5, r_single_pol_raw)
    r_single_dk0 = np.where(M_dk, 0.0, r_single_pol_raw)
    r_prev = np.where(M_dk, emp_p[None, :], Z)

    # Naive unweighted single-polarity DK=0 checklist (item weight 1/25 -> domain weight m_d / 25)
    w_item_eq = np.array([len(bank["dimensions"][d]["items"]) / 25.0 for d in dim_keys], dtype=np.float64)
    w_dom_eq = np.full(len(dim_keys), 1.0 / 6.0, dtype=np.float64)

    arms = {
        "unmasked_oracle": score_matrix(Z, bank, w_norm),
        "raisr_full": score_matrix(r_full, bank, w_norm),
        "naive_single_polarity_dk0_unweighted": score_matrix(r_single_dk0, bank, w_item_eq),
        "single_polarity_dk0_normative": score_matrix(r_single_dk0, bank, w_norm),
        "single_polarity_dk05_normative": score_matrix(r_single_dk05, bank, w_norm),
        "aligned_polarity_dk0_mscore_adapted": score_matrix(r_dk0_aligned, bank, w_norm),
        "aligned_polarity_dk1_pessimistic": score_matrix(r_dk1_aligned, bank, w_norm),
        "available_case_dimension_mean": score_matrix(np.where(M_dk, 0.0, Z), bank, w_norm, avail_mask=(~M_dk).astype(np.float64)),
        "empirical_prevalence_dk": score_matrix(r_prev, bank, w_norm),
        "equal_domain_1_6": score_matrix(r_full, bank, w_dom_eq),
        "item_equal_1_25": score_matrix(r_full, bank, w_item_eq),
    }

    arm_metrics = {}
    oracle_bands = np.digitize(arms["unmasked_oracle"], [40.0, 65.0, 85.0], right=False)
    for aname, sc in arms.items():
        b = np.digitize(sc, [40.0, 65.0, 85.0], right=False)
        exact = float(np.mean(b == ref_bands))
        adj = float(np.mean(np.abs(b - ref_bands) <= 1))
        two_jump = float(np.mean(np.abs(b - ref_bands) >= 2))
        false_crit = float(np.mean((b == 3) & (oracle_bands < 3)))
        rho_s = float(stats.spearmanr(sc, arms["unmasked_oracle"]).statistic)
        arm_metrics[aname] = {
            "exact_concordance": exact,
            "adjacent_or_exact": adj,
            "two_band_jump_rate": two_jump,
            "false_critical_rate": false_crit,
            "spearman_vs_oracle": rho_s,
            "mean_score": float(np.mean(sc)),
            "sd_score": float(np.std(sc, ddof=1)),
        }

    # High-AI subgroup check (active AI on >= 2 of A1..A4)
    ai_indices = [idx for idx, (d, _, _) in enumerate(cohort["items_flat"]) if d == "ai_exposure"]
    high_ai_mask = Z[:, ai_indices].sum(axis=1) >= 2
    b_full = np.digitize(arms["raisr_full"], [40.0, 65.0, 85.0], right=False)
    b_sp05 = np.digitize(arms["single_polarity_dk05_normative"], [40.0, 65.0, 85.0], right=False)
    b_naive = np.digitize(arms["naive_single_polarity_dk0_unweighted"], [40.0, 65.0, 85.0], right=False)
    high_ai_polarity_gain = float(np.mean(b_full[high_ai_mask] == ref_bands[high_ai_mask]) - np.mean(b_sp05[high_ai_mask] == ref_bands[high_ai_mask])) if np.any(high_ai_mask) else 0.0

    # DK dose-response curve (0.0, 0.25, 0.50, 0.75, 1.0)
    dk_dose = {}
    for dk_val in [0.0, 0.25, 0.50, 0.75, 1.0]:
        sc_d = score_matrix(np.where(M_dk, dk_val, Z), bank, w_norm)
        b_d = np.digitize(sc_d, [40.0, 65.0, 85.0], right=False)
        dk_dose[f"{dk_val:.2f}"] = {
            "exact_concordance": float(np.mean(b_d == ref_bands)),
            "adjacent_or_exact": float(np.mean(np.abs(b_d - ref_bands) <= 1)),
            "false_critical_rate": float(np.mean((b_d == 3) & (oracle_bands < 3))),
            "mean_score": float(np.mean(sc_d)),
        }

    # Placebo control: permute item order within each dimension & vary DK on zero-DK profiles
    rng_p = np.random.default_rng(seed + 777)
    r_perm = r_full.copy()
    offset = 0
    for dname in dim_keys:
        m_d = len(bank["dimensions"][dname]["items"])
        perm = rng_p.permutation(m_d)
        r_perm[:, offset : offset + m_d] = r_perm[:, offset : offset + m_d][:, perm]
        offset += m_d
    sc_perm = score_matrix(r_perm, bank, w_norm)
    placebo_max_diff = float(np.max(np.abs(sc_perm - arms["raisr_full"])))
    placebo_band_match = float(np.mean(np.digitize(sc_perm, [40.0, 65.0, 85.0], right=False) == b_full))

    # Positive control: all-AI active vs zero-AI on micro baseline
    pos_z0 = np.zeros((1, 25), dtype=np.float64)
    pos_z1 = np.zeros((1, 25), dtype=np.float64)
    for idx_ai in ai_indices:
        pos_z1[0, idx_ai] = 1.0
    pos_shift = float(score_matrix(pos_z1, bank, w_norm)[0] - score_matrix(pos_z0, bank, w_norm)[0])

    # Multi-regime Dirichlet stability relative to RAISR-SME normative tiers b_full
    dirichlet_regimes = {}
    rng_d = np.random.default_rng(seed + 333)
    for alpha0 in [5, 20, 50]:
        w_draws = rng_d.dirichlet(alpha0 * w_norm, size=300)
        exact_list, adj_list, jump2_list, rho_list = [], [], [], []
        for m in range(300):
            sc_m = score_matrix(r_full, bank, w_draws[m])
            b_m = np.digitize(sc_m, [40.0, 65.0, 85.0], right=False)
            exact_list.append(float(np.mean(b_m == b_full)))
            adj_list.append(float(np.mean(np.abs(b_m - b_full) <= 1)))
            jump2_list.append(float(np.mean(np.abs(b_m - b_full) >= 2)))
            rho_list.append(float(stats.spearmanr(sc_m, arms["raisr_full"]).statistic))
        dirichlet_regimes[f"alpha_{alpha0}"] = {
            "exact_retention_mean": float(np.mean(exact_list)),
            "exact_retention_p05": float(np.percentile(exact_list, 5)),
            "adjacent_or_exact_mean": float(np.mean(adj_list)),
            "two_band_jump_mean": float(np.mean(jump2_list)),
            "spearman_mean": float(np.mean(rho_list)),
        }

    # Deterministic weight & cut-point benchmarks vs b_full
    det_benchmarks = {}
    for bname, sc_b, cuts in [
        ("equal_domain_1_6", arms["equal_domain_1_6"], [40.0, 65.0, 85.0]),
        ("item_equal_1_25", arms["item_equal_1_25"], [40.0, 65.0, 85.0]),
        ("cut_minus_5", arms["raisr_full"], [35.0, 60.0, 80.0]),
        ("cut_plus_5", arms["raisr_full"], [45.0, 70.0, 90.0]),
    ]:
        b_alt = np.digitize(sc_b, cuts, right=False)
        det_benchmarks[bname] = {
            "exact_retention": float(np.mean(b_alt == b_full)),
            "adjacent_or_exact": float(np.mean(np.abs(b_alt - b_full) <= 1)),
            "two_band_jump_rate": float(np.mean(np.abs(b_alt - b_full) >= 2)),
            "spearman_vs_normative": float(stats.spearmanr(sc_b, arms["raisr_full"]).statistic),
        }

    # Distance-to-boundary single-item flip rates
    sc_ref = arms["raisr_full"]
    dist_cut = np.minimum.reduce([np.abs(sc_ref - 40.0), np.abs(sc_ref - 65.0), np.abs(sc_ref - 85.0)])
    flip_any = np.zeros(len(sc_ref), dtype=bool)
    for j in range(25):
        r_pert = r_full.copy()
        r_pert[:, j] = np.where(r_full[:, j] < 1.0, np.minimum(1.0, r_full[:, j] + 0.5), 0.5)
        b_pert = np.digitize(score_matrix(r_pert, bank, w_norm), [40.0, 65.0, 85.0], right=False)
        flip_any |= (b_pert != b_full)
    boundary_bins = {}
    for lo, hi, lbl in [(0.0, 2.0, "0_to_2_pts"), (2.0, 5.0, "2_to_5_pts"), (5.0, 10.0, "5_to_10_pts"), (10.0, 50.0, "gt_10_pts")]:
        msk = (dist_cut >= lo) & (dist_cut < hi)
        boundary_bins[lbl] = {
            "n_profiles": int(msk.sum()),
            "any_single_halfstep_flip_rate": float(flip_any[msk].mean()) if np.any(msk) else 0.0,
        }

    return {
        "n_profiles": int(len(Z)),
        "arms": arm_metrics,
        "primary_gain_vs_naive_checklist": float(arm_metrics["raisr_full"]["exact_concordance"] - arm_metrics["naive_single_polarity_dk0_unweighted"]["exact_concordance"]),
        "gain_vs_mscore_dk0": float(arm_metrics["raisr_full"]["exact_concordance"] - arm_metrics["aligned_polarity_dk0_mscore_adapted"]["exact_concordance"]),
        "gain_vs_single_polarity_dk05": float(arm_metrics["raisr_full"]["exact_concordance"] - arm_metrics["single_polarity_dk05_normative"]["exact_concordance"]),
        "gain_vs_available_case_mean": float(arm_metrics["raisr_full"]["exact_concordance"] - arm_metrics["available_case_dimension_mean"]["exact_concordance"]),
        "high_ai_subgroup_polarity_gain": high_ai_polarity_gain,
        "headroom": {
            "baseline_naive_checklist": float(arm_metrics["naive_single_polarity_dk0_unweighted"]["exact_concordance"]),
            "ceiling_unmasked_oracle": float(arm_metrics["unmasked_oracle"]["exact_concordance"]),
            "room": float(arm_metrics["unmasked_oracle"]["exact_concordance"] - arm_metrics["naive_single_polarity_dk0_unweighted"]["exact_concordance"]),
            "raisr_full_achieved": float(arm_metrics["raisr_full"]["exact_concordance"]),
        },
        "controls": {
            "positive_shadow_ai_score_shift": pos_shift,
            "negative_within_dim_perm_max_diff": placebo_max_diff,
            "negative_within_dim_perm_band_match": placebo_band_match,
        },
        "dk_dose_curve": dk_dose,
        "dirichlet_regimes": dirichlet_regimes,
        "deterministic_benchmarks": det_benchmarks,
        "boundary_flip_by_distance": boundary_bins,
        "non_ai_max_scores": {
            "normative": 85.0,
            "equal_domain_1_6": round(500.0 / 6.0, 6),
            "item_equal_1_25": 84.0,
        },
    }


def verify_three_engine_parity_and_worked_case(bank: Dict, seed: int = 202703, n_vectors: int = 20000) -> Dict:
    """Run 20,000-vector parity across Python scoring.py, Node.js scoring.js, and NumPy + worked 18-emp SME."""
    rng = random.Random(seed)
    all_items = [(d, it["id"], it["risk_when"]) for d in bank["dimensions"] for it in bank["dimensions"][d]["items"]]
    vectors = []
    for _ in range(n_vectors):
        vectors.append({iid: rng.choice(["yes", "no", "dk"]) for _, iid, _ in all_items})

    # Add explicit boundary stress vectors (including solo-micro-no-governance = 85.0 and all-DK = 50.0)
    for arch in bank["archetypes"]:
        ans = {}
        for d, iid, rwhen in all_items:
            rv = arch["responses"][iid]
            if rv == 0.5:
                ans[iid] = "dk"
            elif rwhen == "yes":
                ans[iid] = "yes" if rv == 1 else "no"
            else:
                ans[iid] = "no" if rv == 1 else "yes"
        vectors.append(ans)

    # Worked 18-employee AI-adopting professional-services SME ("Northwood Tax & Advisory Ltd")
    worked_answers = {
        "H1": "no",   # no formal cybersecurity policy
        "H2": "no",   # no staff cybersecurity training
        "H3": "yes",  # holds cyber insurance
        "H4": "yes",  # important files backed up
        "H5": "no",   # admin accounts not restricted
        "H6": "yes",  # security-monitoring software installed
        "G1": "yes",  # one named person responsible
        "G2": "no",   # no annual owner/board review
        "G3": "no",   # incident responsibilities not written down
        "G4": "dk",   # unsure if supplier security requirements checked
        "G5": "no",   # staff reporting route not established
        "I1": "no",   # no written incident response plan
        "I2": "dk",   # unsure who to contact in first hour
        "I3": "no",   # incident plan not exercised in last year
        "I4": "dk",   # unsure of actively exploited vulnerabilities (KEV)
        "A1": "yes",  # uses at least one AI tool (exposure = 1)
        "A2": "yes",  # staff use generative-AI tools (exposure = 1)
        "A3": "yes",  # uses two or more AI technologies (exposure = 1)
        "A4": "dk",   # unsure whether AI tools process personal data (DK = 0.5)
        "D1": "yes",  # written policy for customer/employee data storage
        "D2": "no",   # backup restore not tested in last year
        "D3": "dk",   # unsure of every cloud location storing business data
        "V1": "yes",  # core operations depend on cloud/online services (exposure = 1)
        "V2": "no",   # no current list of software/service dependencies
        "V3": "dk",   # unsure if new tool security track record (KEV) is checked
    }
    vectors.append(worked_answers)

    py_scores = []
    unquant_neumaier_bands = []
    dim_keys = list(bank["dimensions"].keys())
    w_norm = np.array([bank["weights"][d] for d in dim_keys], dtype=np.float64)
    risk_rows = []

    for vec in vectors:
        sc = ref_scoring.score_answers(vec, bank)
        py_scores.append((ref_scoring.quantize(sc.total), sc.band))
        r_row = [ref_scoring.risk_of(vec[iid], rwhen) for _, iid, rwhen in all_items]
        risk_rows.append(r_row)
        # Unquantized Python 3.12 compensated sum() baseline without 1e-9 rounding
        dim_unq = []
        idx = 0
        for dname in dim_keys:
            m_d = len(bank["dimensions"][dname]["items"])
            dim_unq.append(sum(r_row[idx : idx + m_d]) * 100.0 / m_d)
            idx += m_d
        tot_unq = sum(dim_unq[k] * bank["weights"][dname] for k, dname in enumerate(dim_keys))
        b_unq = "Critical"
        for lbl, (lo, hi) in bank["bands"].items():
            if lo <= tot_unq < hi:
                b_unq = lbl
                break
        unquant_neumaier_bands.append((tot_unq, b_unq))

    np_totals = score_matrix(np.array(risk_rows, dtype=np.float64), bank, w_norm)
    band_names = ["Low", "Medium", "High", "Critical"]
    np_bands = [band_names[int(x)] for x in np.digitize(np_totals, [40.0, 65.0, 85.0], right=False)]

    # Node.js batch verification against scoring.js
    js_driver = f"""
const fs = require('fs');
const RAISR = require({json.dumps(str(SCORING_JS))});
const bank = JSON.parse(fs.readFileSync({json.dumps(str(BANK_PATH))}, 'utf8'));
const vectors = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = vectors.map(v => {{
  const risks = RAISR.answersToRisks(v, bank);
  const res = RAISR.scoreVector(risks, bank);
  return [RAISR.quantize(res.total), res.band];
}});
const workedRisks = RAISR.answersToRisks(vectors[vectors.length - 1], bank);
const workedRes = RAISR.scoreVector(workedRisks, bank);
const workedRanked = RAISR.rankedActions(workedRes.dimensions, bank);
process.stdout.write(JSON.stringify({{results: out, worked: {{total: RAISR.quantize(workedRes.total), band: workedRes.band, dimensions: workedRes.dimensions, ranked: workedRanked}}}}));
"""
    proc = subprocess.run(
        ["node", "-e", js_driver],
        input=json.dumps(vectors),
        text=True,
        capture_output=True,
        check=True,
    )
    js_payload = json.loads(proc.stdout)
    js_scores = js_payload["results"]

    n_total = len(vectors)
    exact_3way = 0
    unquant_float_diffs = 0
    unquant_band_flips = 0
    for idx in range(n_total):
        pq, pb = py_scores[idx]
        jq, jb = js_scores[idx]
        nq, nb = float(np_totals[idx]), np_bands[idx]
        if pq == jq == nq and pb == jb == nb:
            exact_3way += 1
        uq, ub = unquant_neumaier_bands[idx]
        if uq != pq:
            unquant_float_diffs += 1
        if ub != pb:
            unquant_band_flips += 1

    worked_py = ref_scoring.score_answers(worked_answers, bank)
    worked_ranked_py = ref_scoring.ranked_actions(worked_py, bank)
    worked_js = js_payload["worked"]

    # Also compare naive single-polarity DK=0 score on the worked 18-employee SME
    naive_risk_sum = 0.0
    for _, iid, _ in all_items:
        ans = worked_answers[iid]
        naive_risk_sum += 1.0 if ans == "no" else 0.0
    naive_worked_score = (naive_risk_sum / 25.0) * 100.0
    naive_worked_band = band_names[band_from_score(naive_worked_score)]

    return {
        "n_random_vectors": n_vectors,
        "n_total_tested": n_total,
        "exact_3runtime_agreement_count": exact_3way,
        "exact_3runtime_agreement_rate": exact_3way / n_total,
        "unquantized_neumaier_ulp_disagreements": unquant_float_diffs,
        "unquantized_neumaier_band_flips": unquant_band_flips,
        "worked_18emp_sme": {
            "case_name": "18-employee professional-services firm adopting public GenAI without formal IT staff",
            "answers": worked_answers,
            "python_quantized_total": ref_scoring.quantize(worked_py.total),
            "js_quantized_total": worked_js["total"],
            "python_band": worked_py.band,
            "js_band": worked_js["band"],
            "unknown_count": worked_py.unknown_count,
            "dimensions": {k: round(v, 4) for k, v in worked_py.dimensions.items()},
            "ranked_actions_py_equals_js": [r["dimension"] for r in worked_ranked_py] == [r["dimension"] for r in worked_js["ranked"]],
            "ranked_actions": worked_ranked_py,
            "naive_single_polarity_dk0_comparison": {
                "score": round(naive_worked_score, 2),
                "band": naive_worked_band,
                "underestimation_points": round(ref_scoring.quantize(worked_py.total) - naive_worked_score, 2),
            },
        },
    }


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "official"
    bank = ref_scoring.load_bank(BANK_PATH)
    data_dir = resolve_data_dir()
    strata_specs = load_empirical_marginals(data_dir, bank)

    if mode == "pilot":
        pilot_cohort = generate_two_stage_cohort(500, strata_specs, bank, seed=202701, rho_ai_gov=0.0, mnar_strength=0.0)
        pilot_res = evaluate_cohort(pilot_cohort, bank, seed=202701, n_ref_draws=300)
        out = {
            "phase": "pilot",
            "seed": 202701,
            "n_profiles": 500,
            "strata_marginals_summary": {
                k: {"n_csbs": v["n_csbs"], "share": v["share"], "ai_any_eurostat": v["ai_any_eurostat"]}
                for k, v in strata_specs.items()
            },
            "pilot_results": pilot_res,
        }
        out_file = OUT_DIR / "exp4_pilot_headroom.json"
        out_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
        hr = pilot_res["headroom"]
        print(
            f"[exp4 pilot] n=500 | baseline={hr['baseline_naive_checklist']:.4f} | "
            f"ceiling={hr['ceiling_unmasked_oracle']:.4f} | room={hr['room']:.4f} | "
            f"raisr_full={hr['raisr_full_achieved']:.4f} | gain={pilot_res['primary_gain_vs_naive_checklist']:.4f}"
        )
        return 0

    # Official mode: 5 independent seeds x N = 10,000 profiles + rho/MNAR sweeps + 20,000-vector 3-engine parity
    seeds = [202702, 202703, 202704, 202705, 202706]
    per_seed = []
    primary_detail = None
    for idx, sd in enumerate(seeds):
        coh = generate_two_stage_cohort(10000, strata_specs, bank, seed=sd, rho_ai_gov=0.0, mnar_strength=0.0)
        ev = evaluate_cohort(coh, bank, seed=sd, n_ref_draws=500)
        if idx == 0:
            primary_detail = ev
        per_seed.append({
            "seed": sd,
            "raisr_full_exact": ev["arms"]["raisr_full"]["exact_concordance"],
            "naive_checklist_exact": ev["arms"]["naive_single_polarity_dk0_unweighted"]["exact_concordance"],
            "mscore_dk0_exact": ev["arms"]["aligned_polarity_dk0_mscore_adapted"]["exact_concordance"],
            "single_pol_dk05_exact": ev["arms"]["single_polarity_dk05_normative"]["exact_concordance"],
            "avail_case_exact": ev["arms"]["available_case_dimension_mean"]["exact_concordance"],
            "emp_prev_exact": ev["arms"]["empirical_prevalence_dk"]["exact_concordance"],
            "dk075_exact": ev["dk_dose_curve"]["0.75"]["exact_concordance"],
            "dk100_exact": ev["arms"]["aligned_polarity_dk1_pessimistic"]["exact_concordance"],
            "oracle_exact": ev["arms"]["unmasked_oracle"]["exact_concordance"],
            "primary_gain": ev["primary_gain_vs_naive_checklist"],
            "polarity_marginal_gain": ev["gain_vs_single_polarity_dk05"],
            "dk05_marginal_gain": ev["gain_vs_mscore_dk0"],
            "alpha20_adj_or_exact": ev["dirichlet_regimes"]["alpha_20"]["adjacent_or_exact_mean"],
            "alpha20_two_band_jump": ev["dirichlet_regimes"]["alpha_20"]["two_band_jump_mean"],
            "alpha5_adj_or_exact": ev["dirichlet_regimes"]["alpha_5"]["adjacent_or_exact_mean"],
        })

    # Cross-block correlation, MNAR, & Uninflated Hierarchical Eurostat AI sensitivity sweeps (N = 10,000, seed 202702)
    sweeps = {}
    for s_lbl, rho_v, mnar_v in [
        ("rho_neg03_mcar", -0.30, 0.0),
        ("rho_zero_mcar", 0.00, 0.0),
        ("rho_pos03_mcar", 0.30, 0.0),
        ("rho_zero_mnar_strong", 0.00, 0.85),
    ]:
        coh_s = generate_two_stage_cohort(10000, strata_specs, bank, seed=202702, rho_ai_gov=rho_v, mnar_strength=mnar_v)
        ev_s = evaluate_cohort(coh_s, bank, seed=202702, n_ref_draws=400)
        realized_p_z1_dk = float(coh_s["Z"][coh_s["M_dk"]].mean()) if coh_s["M_dk"].any() else 0.0
        sweeps[s_lbl] = {
            "raisr_full_exact": ev_s["arms"]["raisr_full"]["exact_concordance"],
            "naive_checklist_exact": ev_s["arms"]["naive_single_polarity_dk0_unweighted"]["exact_concordance"],
            "mscore_dk0_exact": ev_s["arms"]["aligned_polarity_dk0_mscore_adapted"]["exact_concordance"],
            "single_pol_dk05_exact": ev_s["arms"]["single_polarity_dk05_normative"]["exact_concordance"],
            "avail_case_exact": ev_s["arms"]["available_case_dimension_mean"]["exact_concordance"],
            "emp_prev_exact": ev_s["arms"]["empirical_prevalence_dk"]["exact_concordance"],
            "dk075_exact": ev_s["dk_dose_curve"]["0.75"]["exact_concordance"],
            "dk100_exact": ev_s["arms"]["aligned_polarity_dk1_pessimistic"]["exact_concordance"],
            "primary_gain": ev_s["primary_gain_vs_naive_checklist"],
            "realized_prob_z1_given_dk": round(realized_p_z1_dk, 4),
        }

    # Uninflated Eurostat AI rates + strict subset hierarchy (A2, A3, A4 = 0 whenever A1 = 0)
    hier_specs = json.loads(json.dumps(strata_specs))
    for s_key, s_val in hier_specs.items():
        ai_base = float(s_val["ai_any_eurostat"])
        ai_nlg_raw = float(s_val["ai_nlg_eurostat"])
        s_val["item_risk_prob"]["A1"] = float(np.clip(ai_base, 0.04, 0.90))
        s_val["item_risk_prob"]["A2"] = float(np.clip(ai_base * 0.75, 0.03, ai_base))
        s_val["item_risk_prob"]["A3"] = float(np.clip(max(ai_nlg_raw, ai_base * 0.45), 0.02, ai_base))
        s_val["item_risk_prob"]["A4"] = float(np.clip(ai_base * 0.55, 0.02, ai_base))
    coh_h = generate_two_stage_cohort(10000, hier_specs, bank, seed=202702, rho_ai_gov=0.0, mnar_strength=0.0)
    ai_idx = {it_id: j for j, (_, it_id, _) in enumerate(coh_h["items_flat"]) if it_id in {"A1", "A2", "A3", "A4"}}
    no_a1 = coh_h["Z"][:, ai_idx["A1"]] == 0.0
    for sub_ai in ["A2", "A3", "A4"]:
        coh_h["Z"][no_a1, ai_idx[sub_ai]] = 0.0
        coh_h["raw_yes"][no_a1, ai_idx[sub_ai]] = 0.0
    coh_h["empirical_p"] = coh_h["Z"].mean(axis=0)
    ev_h = evaluate_cohort(coh_h, bank, seed=202702, n_ref_draws=400)
    sweeps["uninflated_hierarchical_eurostat_mcar"] = {
        "raisr_full_exact": ev_h["arms"]["raisr_full"]["exact_concordance"],
        "naive_checklist_exact": ev_h["arms"]["naive_single_polarity_dk0_unweighted"]["exact_concordance"],
        "mscore_dk0_exact": ev_h["arms"]["aligned_polarity_dk0_mscore_adapted"]["exact_concordance"],
        "single_pol_dk05_exact": ev_h["arms"]["single_polarity_dk05_normative"]["exact_concordance"],
        "avail_case_exact": ev_h["arms"]["available_case_dimension_mean"]["exact_concordance"],
        "emp_prev_exact": ev_h["arms"]["empirical_prevalence_dk"]["exact_concordance"],
        "primary_gain": ev_h["primary_gain_vs_naive_checklist"],
        "polarity_marginal_gain": ev_h["gain_vs_single_polarity_dk05"],
        "dk05_marginal_gain": ev_h["gain_vs_mscore_dk0"],
        "false_critical_raisr": ev_h["arms"]["raisr_full"]["false_critical_rate"],
        "false_critical_avail_case": ev_h["arms"]["available_case_dimension_mean"]["false_critical_rate"],
    }

    parity = verify_three_engine_parity_and_worked_case(bank, seed=202703, n_vectors=20000)

    # Export clean CSVs for ve-tikz-v6 Figure 4
    assert primary_detail is not None
    rows_fig4a = []
    for code, label in [
        ("naive_single_polarity_dk0_unweighted", "Naive_Checklist_DK0"),
        ("single_polarity_dk05_normative", "SinglePol_DK05"),
        ("aligned_polarity_dk0_mscore_adapted", "AlignedPol_DK0"),
        ("available_case_dimension_mean", "AvailCase_Mean"),
        ("empirical_prevalence_dk", "Prevalence_DK"),
        ("raisr_full", "RAISR_Full_DK05"),
        ("unmasked_oracle", "Unmasked_Oracle"),
    ]:
        m = primary_detail["arms"][code]
        rows_fig4a.append({
            "arm_id": code,
            "label": label,
            "exact_concordance": round(m["exact_concordance"], 4),
            "adjacent_or_exact": round(m["adjacent_or_exact"], 4),
            "false_critical_rate": round(m["false_critical_rate"], 4),
            "two_band_jump_rate": round(m["two_band_jump_rate"], 4),
        })
    pd.DataFrame(rows_fig4a).to_csv(SUMMARY_DIR / "fig4_ablation_arms.csv", index=False)

    rows_fig4b = []
    for rcode, rlbl in [("alpha_5", "Dirichlet_a5"), ("alpha_20", "Dirichlet_a20"), ("alpha_50", "Dirichlet_a50")]:
        rm = primary_detail["dirichlet_regimes"][rcode]
        rows_fig4b.append({
            "regime": rlbl,
            "exact_retention": round(rm["exact_retention_mean"], 4),
            "adjacent_or_exact": round(rm["adjacent_or_exact_mean"], 4),
            "two_band_jump": round(rm["two_band_jump_mean"], 4),
            "spearman_rho": round(rm["spearman_mean"], 4),
        })
    for dcode, dlbl in [
        ("equal_domain_1_6", "Equal_Domain_1_6"),
        ("item_equal_1_25", "Item_Equal_1_25"),
        ("cut_minus_5", "Cuts_Minus_5pt"),
        ("cut_plus_5", "Cuts_Plus_5pt"),
    ]:
        dm = primary_detail["deterministic_benchmarks"][dcode]
        rows_fig4b.append({
            "regime": dlbl,
            "exact_retention": round(dm["exact_retention"], 4),
            "adjacent_or_exact": round(dm["adjacent_or_exact"], 4),
            "two_band_jump": round(dm["two_band_jump_rate"], 4),
            "spearman_rho": round(dm["spearman_vs_normative"], 4),
        })
    pd.DataFrame(rows_fig4b).to_csv(SUMMARY_DIR / "fig4_weight_and_cut_regimes.csv", index=False)

    rows_dose = []
    for k_str, dv in primary_detail["dk_dose_curve"].items():
        rows_dose.append({
            "dk_scalar": float(k_str),
            "exact_concordance": round(dv["exact_concordance"], 4),
            "adjacent_or_exact": round(dv["adjacent_or_exact"], 4),
            "false_critical_rate": round(dv["false_critical_rate"], 4),
        })
    pd.DataFrame(rows_dose).to_csv(SUMMARY_DIR / "fig4_dk_dose_curve.csv", index=False)

    out_official = {
        "phase": "official",
        "seeds": seeds,
        "n_profiles_per_seed": 10000,
        "strata_marginals": strata_specs,
        "primary_seed_202702": primary_detail,
        "multi_seed_summary": per_seed,
        "multi_seed_means": {
            "raisr_full_exact_mean": float(np.mean([r["raisr_full_exact"] for r in per_seed])),
            "naive_checklist_exact_mean": float(np.mean([r["naive_checklist_exact"] for r in per_seed])),
            "mscore_dk0_exact_mean": float(np.mean([r["mscore_dk0_exact"] for r in per_seed])),
            "single_pol_dk05_exact_mean": float(np.mean([r["single_pol_dk05_exact"] for r in per_seed])),
            "avail_case_exact_mean": float(np.mean([r["avail_case_exact"] for r in per_seed])),
            "emp_prev_exact_mean": float(np.mean([r["emp_prev_exact"] for r in per_seed])),
            "dk075_exact_mean": float(np.mean([r["dk075_exact"] for r in per_seed])),
            "dk100_exact_mean": float(np.mean([r["dk100_exact"] for r in per_seed])),
            "dk075_exact_sd": float(np.std([r["dk075_exact"] for r in per_seed], ddof=1)),
            "dk100_exact_sd": float(np.std([r["dk100_exact"] for r in per_seed], ddof=1)),
            "primary_gain_mean": float(np.mean([r["primary_gain"] for r in per_seed])),
            "polarity_marginal_gain_mean": float(np.mean([r["polarity_marginal_gain"] for r in per_seed])),
            "dk05_marginal_gain_mean": float(np.mean([r["dk05_marginal_gain"] for r in per_seed])),
            "alpha20_adj_or_exact_mean": float(np.mean([r["alpha20_adj_or_exact"] for r in per_seed])),
            "alpha20_two_band_jump_mean": float(np.mean([r["alpha20_two_band_jump"] for r in per_seed])),
        },
        "correlation_and_mnar_sweeps": sweeps,
        "three_engine_parity_and_worked_case": parity,
    }
    out_path = OUT_DIR / "exp4_sensitivity_and_worked_examples.json"
    out_path.write_text(json.dumps(out_official, indent=2), encoding="utf-8")
    mm = out_official["multi_seed_means"]
    w18 = parity["worked_18emp_sme"]
    print(
        f"[exp4 official] 5x10,000 profiles | RAISR exact={mm['raisr_full_exact_mean']:.4f} vs "
        f"naive={mm['naive_checklist_exact_mean']:.4f} (gain=+{mm['primary_gain_mean']:.4f}) | "
        f"pol_gain=+{mm['polarity_marginal_gain_mean']:.4f} | dk05_gain=+{mm['dk05_marginal_gain_mean']:.4f} | "
        f"alpha20_adj={mm['alpha20_adj_or_exact_mean']:.4f} (jump2={mm['alpha20_two_band_jump_mean']:.4f}) | "
        f"3-engine parity={parity['exact_3runtime_agreement_count']}/{parity['n_total_tested']} | "
        f"18-emp worked={w18['python_quantized_total']} ({w18['python_band']}) vs naive={w18['naive_single_polarity_dk0_comparison']['score']} ({w18['naive_single_polarity_dk0_comparison']['band']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
