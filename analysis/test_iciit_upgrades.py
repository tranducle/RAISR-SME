#!/usr/bin/env python3
"""Deterministic integrity and regression checks for RAISR-SME ICIIT 2027 outputs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ANALYSIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ANALYSIS_DIR.parent
RESULTS_DIR = ANALYSIS_DIR / "results"


def load_json(name: str) -> dict:
    path = RESULTS_DIR / name
    if not path.exists():
        raise AssertionError(f"Missing result artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def check_nist_catalog() -> None:
    proc = subprocess.run(
        [sys.executable, str(ANALYSIS_DIR / "verify_ids.py")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "unique=26 | problems=0" in proc.stdout, proc.stdout
    res = load_json("nist_csf2_id_verification.json")
    assert res["unique_ids_count"] == 26
    assert res["problems"] == 0


def check_exp1() -> None:
    res = load_json("exp1_formative_and_missingness.json")
    sm = res["summary_metrics"]
    assert abs(sm["pure_not_asked_share_2023"] - 0.8664) < 1e-4
    assert abs(sm["pure_not_asked_share_2024"] - 0.9979) < 1e-4
    assert abs(sm["pure_not_asked_share_2025"] - 0.9990) < 1e-4
    assert sm["pooled_3wave_not_asked_share"] > 0.95
    assert sm["max_vif_across_all_4_datasets"] == 1.9144 < 3.3


def check_exp2() -> None:
    res = load_json("exp2_common_sample_and_mechanisms.json")
    m = res["models"]
    assert m["full_business_contemporaneous_N3061"]["n"] == 3061
    assert m["full_business_contemporaneous_N3061"]["n_firms"] == 2196
    assert m["common_sample_contemporaneous_n865"]["n"] == 865
    assert m["common_sample_contemporaneous_n865"]["n_firms"] == 575
    assert abs(res["delta_beta_tests"]["stacked_glm_wald"]["delta_beta_log_odds"] - 0.06033) < 1e-4
    md = res["mundlak_decomposition"]
    assert abs(md["full_n3061_contemporaneous"]["beta_between"] - 0.19156) < 1e-4
    assert abs(md["clean_n865_prewindow_lagged"]["beta_within"] - (-0.3485)) < 1e-4
    assert abs(md["stacked_full_between_minus_clean_lag_within"]["contrast_between_minus_lag_within"] - 0.54048) < 1e-4
    dyn = m["common_sample_dynamic_with_breach_lag"]
    assert abs(dyn["or_breach_lag"] - 3.1215) < 1e-3
    assert abs(dyn["ci95_breach_lag"][0] - 0.75611) < 1e-4
    assert abs(dyn["ci95_breach_lag"][1] - 1.52052) < 1e-4
    assert abs(res["placebo_permutation_500"]["empirical_p_stacked_contrast"] - 0.00998) < 1e-4


def check_exp3() -> None:
    res = load_json("exp3_sme_size_bridge_and_auc.json")
    assert res["total_csbs_complete_case"] == 8086
    for band in ("micro_1_9", "small_10_49", "medium_50_249", "large_250_plus"):
        assert res["csbs_pooled_by_size"][band]["maturity_score_or"] > 1.20
    auc25 = res["auc_orientation_and_oof_delta"]["2025"]
    assert abs(auc25["raw_gap_score_auc"] + auc25["inverted_maturity_score_auc"] - 1.0) < 1e-8
    assert abs(auc25["oof_delta_auc"] - 0.0162) < 1e-4


def check_exp4() -> None:
    res = load_json("exp4_sensitivity_and_worked_examples.json")
    mm = res["multi_seed_means"]
    assert abs(mm["raisr_full_exact_mean"] - 0.71188) < 1e-4
    assert abs(mm["primary_gain_mean"] - 0.23424) < 1e-4
    assert abs(mm["dk075_exact_mean"] - 0.69886) < 1e-4
    assert abs(mm["dk100_exact_mean"] - 0.51886) < 1e-4
    sw = res["correlation_and_mnar_sweeps"]
    assert abs(sw["rho_zero_mnar_strong"]["realized_prob_z1_given_dk"] - 0.7356) < 1e-4
    assert sw["uninflated_hierarchical_eurostat_mcar"]["primary_gain"] > 0.14
    parity = res["three_engine_parity_and_worked_case"]
    assert parity["exact_3runtime_agreement_count"] == 20006
    assert parity["exact_3runtime_agreement_rate"] == 1.0
    assert abs(parity["worked_18emp_sme"]["python_quantized_total"] - 68.208333333) < 1e-9


def main() -> int:
    checks = [
        ("NIST CSF 2.0 catalog crosswalk", check_nist_catalog),
        ("exp1 skip-routing & VIF", check_exp1),
        ("exp2 clean panel & Mundlak", check_exp2),
        ("exp3 SME size strata & OOF AUC", check_exp3),
        ("exp4 Monte Carlo & 3-engine parity", check_exp4),
    ]
    for label, fn in checks:
        fn()
        print(f"  [ok] {label}")
    print(f"test_iciit_upgrades: {len(checks)}/{len(checks)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
