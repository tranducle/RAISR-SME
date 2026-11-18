# Analysis and Replication Suite (ICIIT 2027)

Deterministic scripts behind the empirical and simulation diagnostics reported in **RAISR-SME: Auditable Cyber-AI Triage and the Limits of Breach-Based Validation** (ICIIT 2027), along with their committed JSON/CSV outputs in `analysis/results/`.

## Single-Command Execution

Run from the repository root:

```bash
pip install -r requirements.txt
bash analysis/run_all.sh
```

When licensed UK Data Archive (UKDA) `.dta` files are placed in `data/` (or supplied via `RAISR_DATA_DIR`; see `DATA.md` and `data/README.md` for SHA-256 checksums and End User Licence access routes), `run_all.sh` executes the empirical and simulation suite end to end. When UKDA microdata is absent, `run_all.sh` runs NIST CSF 2.0 catalog verification, 20,006-vector three-runtime parity tests, and regression verification against the committed `analysis/results/*.json` outputs. Exported plot-summary CSVs write to `analysis/results/summaries/` by default (`RAISR_SUMMARY_DIR` optional override).

## Script-to-Manuscript Claim Map

| Script | Data Inputs | Output File | Manuscript Section & Tables |
| :- | :- | :- | :- |
| `verify_ids.py` | `catalogs_nist_csf_2_0.csv`, `../instrument/nist_csf2_crosswalk.json` | `results/nist_csf2_id_verification.json` | Section 3.1, Table 2 (`26/26` NIST CSF 2.0 subcategory IDs) |
| `exp4_sensitivity_and_worked_examples.py` | UK CSBS 2025 + Eurostat `isoc_eb_ai` + `bank_v1.json` | `results/exp4_sensitivity_and_worked_examples.json` | Section 3.3, Table 3, Section 5.1, Table 4, Figure 4 (`5 x 10,000` profiles, comparators, parity, 18-employee trace) |
| `retrospective_robustness.py` | `../instrument/bank_v1.json`, `results/exp4_sensitivity_and_worked_examples.json` | `results/retrospective_robustness.{json,csv}` | Section 3.2, Section 5.1, Tables 4 and 5 (signed half-step flips, equal-domain alt. ref., `[L, H]` completion bounds `87.86%`) |
| `exp1_formative_and_missingness.py` | UK CSBS 2023 to 2025; UK CSLS W1 to W4 | `results/exp1_formative_and_missingness.json` | Section 5.2, Table 6 (`95.44%` routing share; `28.96% vs 15.57%` 2023 selection; max `VIF = 1.91`) |
| `exp3_sme_size_bridge_and_auc.py` | UK CSBS 2023 to 2025 (`N = 8,086`) + UK CSLS | `results/exp3_sme_size_bridge_and_auc.json` | Section 5.3, Table 7 (`4/4` CSBS strata ORs, 2025 OOF AUC `+0.0162`) |
| `exp2_common_sample_and_mechanisms.py` | UK CSLS Waves 1 to 4 (SN 9356) | `results/exp2_common_sample_and_mechanisms.json` | Section 5.4, Table 8 (`N = 3,061` full panel; `n = 865` matched transitions; Mundlak within/between & cross-frame contrasts) |
| `test_iciit_upgrades.py` | Committed `results/*.json` + `verify_ids.py` | stdout exit status | Automated verification of numerical artifacts |

Legacy baseline scripts (`arm1_cross_sectional.py`, `arm2_panel_lagged.py`, `instrument_validation.py`, `auxiliary_analyses.py`, `csbs_common.py`) are preserved intact for historical provenance.

## Important Interpretation Notes

1. **Empty Stata `LongId` strings in UK CSLS (`exp2`)**: In `csls_waves_1-4.dta`, 482 Wave-4 Fresh single-wave businesses carry empty-string `LongId == ""` rather than `NaN`. `exp2` assigns distinct `FRESH_<idx>` cluster IDs in full-panel models (`N = 3,061`, `2,196` firms) and restricts matched transitions strictly to non-empty `LongId` multi-wave firms (`n = 865`, `575` firms, `wave_gap = 1`).
2. **Same-frame vs. cross-frame Mundlak contrasts (`exp2`)**: Same-frame lagged Mundlak contrasts on the 865-transition subset (`+0.4054, p = 0.1031`) differ from cross-frame contrasts comparing full-panel between slopes against transition-frame within slopes (`+0.5405, p = 0.0168`), which span distinct populations.
3. **Completion bounds (`retrospective_robustness.py`)**: Conditional bounds `[L, H]` under fixed weights represent deterministic score ranges when unknown items are set to `0` vs `1`, not probability intervals.
4. **Data Redistribution Policy**: UK Data Archive Stata `.dta` files cannot be redistributed publicly under the UKDA End User Licence. All `.dta` checksums and study numbers are documented in `../DATA.md`, `../data/CHECKSUMS.sha256`, and `../data/README.md`.
