# Analysis and Replication Suite (ICIIT 2027)

Deterministic scripts behind every empirical and Monte Carlo estimate reported in the ICIIT 2027 manuscript, along with their committed JSON outputs in `analysis/results/`.

## Single-Command Execution

Run from the repository root:

```bash
pip install -r requirements.txt
bash analysis/run_all.sh
```

When licensed UK Data Archive (UKDA) `.dta` files are placed in `data/` (or supplied via `RAISR_DATA_DIR`; see `DATA.md` and `data/README.md` for SHA-256 checksums and End User Licence access routes), `run_all.sh` executes the full empirical and simulation pipeline end to end. When UKDA microdata is absent, `run_all.sh` runs offline NIST CSF 2.0 catalog verification, 20,006-vector three-runtime parity tests, and regression verification against the committed `analysis/results/*.json` outputs. Exported plot-summary CSVs write to `analysis/results/summaries/` by default (`RAISR_SUMMARY_DIR` optional override).

## Script-to-Manuscript Claim Map

| Script | Data Inputs | Output File | Manuscript Section & Claims |
| :- | :- | :- | :- |
| `verify_ids.py` | `catalogs_nist_csf_2_0.csv`, `../instrument/nist_csf2_crosswalk.json` | `results/nist_csf2_id_verification.json` | Section 3.1, Table 2 (`26/26` NIST CSF 2.0 subcategory IDs) |
| `exp1_formative_and_missingness.py` | UK CSBS 2023, 2024, 2025; UK CSLS W1 to W4 | `results/exp1_formative_and_missingness.json` | Section 5.1, Table 4 (`95.44%` 3-wave skip-routing loss; max `VIF = 1.9144`) |
| `exp2_common_sample_and_mechanisms.py` | UK CSLS Waves 1 to 4 (SN 9356) | `results/exp2_common_sample_and_mechanisms.json` | Section 5.3, Figure 3, Table 6 (`N = 3,061` across `2,196` firms; `n = 865` genuine transitions across `575` firms; Mundlak, dynamic persistence, cross-lagged, placebo) |
| `exp3_sme_size_bridge_and_auc.py` | UK CSBS 2023 to 2025 (`N = 8,086`) + UK CSLS | `results/exp3_sme_size_bridge_and_auc.json` | Section 5.2, Figure 2, Table 5 (split-ballot-normalized SME size strata, CSLS Medium-SME bridge, 5-fold OOF ROC AUC) |
| `exp4_sensitivity_and_worked_examples.py` | UK CSBS 2025 + Eurostat `isoc_eb_ai` + `bank_v1.json` | `results/exp4_sensitivity_and_worked_examples.json` | Section 3.3, Table 3, Section 5.4, Figure 4, Table 7 (`5 x 10,000` SME profiles, `2x2` ablations, uninflated Eurostat check, Dirichlet stability, `20,006`-vector parity, 18-employee trace) |
| `test_iciit_upgrades.py` | Committed `results/*.json` + `verify_ids.py` | stdout exit status | Automated verification of all central manuscript numbers |

Legacy baseline scripts (`arm1_cross_sectional.py`, `arm2_panel_lagged.py`, `instrument_validation.py`, `auxiliary_analyses.py`, `csbs_common.py`) are preserved intact for historical provenance.

## Important Interpretation Notes

1. **Empty Stata `LongId` strings in UK CSLS (`exp2`)**: In `csls_waves_1-4.dta`, 482 Wave-4 Fresh single-wave businesses carry empty-string `LongId == ""` rather than `NaN`. `exp2` assigns distinct `FRESH_<idx>` cluster IDs in full-panel models (`N = 3,061`, `2,196` firms) and restricts lagged and within-firm panel transitions strictly to non-empty `LongId` multi-wave firms (`n = 865`, `575` firms, 100% `wave_gap = 1`).
2. **Score orientation (`exp3`)**: Raw survey gap scores measure control *absence* (`OR < 1` indicates fewer reported breaches among higher-gap firms); negated maturity scores satisfy `OR_maturity = 1 / OR_gap > 1` and `AUC(-s, y) = 1 - AUC(s, y)` identically.
3. **Data Redistribution Policy**: UK Data Archive Stata `.dta` files cannot be redistributed publicly under the UKDA End User Licence. All `.dta` checksums and official download study numbers (SN 8969, 8971, 9067, 9101, 9284, 9285, 9356, 9404) are documented in `../DATA.md`, `../data/CHECKSUMS.sha256`, and `../data/README.md`.
