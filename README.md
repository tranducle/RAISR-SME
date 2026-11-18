# RAISR-SME: Rapid AI and Information Security Readiness for Small and Medium-Sized Enterprises

Open 25-item ternary (`Yes` / `No` / `Don't know`) cyber-AI self-assessment checklist, three bit-exact client-side/offline scoring engines, and deterministic synthetic and UK survey audit suite accompanying our **ICIIT 2027** (ACM ICPS) manuscript:

> **RAISR-SME: Auditable Cyber-AI Triage and the Limits of Breach-Based Validation**
> Anonymous Authors (author names and affiliations withheld during peer review)

- **Interactive Zero-Telemetry Browser App**: https://raisr-sme.vercel.app
- **Code License**: MIT (`LICENSE`) | **Item Bank License**: CC BY 4.0 (`instrument/bank_v1.json`)

## Repository Structure

| Directory / File | Contents |
| :- | :- |
| `instrument/bank_v1.json` | Frozen 25-item ternary item bank across 6 domains (`LCM = 1200` proportional weights, per-item `risk_when` polarity, action templates) |
| `instrument/nist_csf2_crosswalk.json` | Crosswalk linking all 25 items to 26 unique NIST CSF 2.0 subcategory IDs, NIST AI RMF 1.0, and CISA CPG/KEV anchors |
| `instrument/scoring.py` | Zero-dependency Python 3.9+ reference scoring engine (`1e-9` quantization in fixed `bank_v1.json` key order) |
| `instrument/scoring.js` | Zero-dependency browser/Node.js JavaScript scoring engine (digit-for-digit parity with `scoring.py`) |
| `instrument/test_scoring.py` | Automated property and 20,000-vector cross-engine parity test suite |
| `analysis/run_all.sh` | Entry script running NIST ID verification, cross-engine parity, `exp1` to `exp4`, retrospective robustness checks, and assertions |
| `analysis/verify_ids.py` | Standalone verifier checking `nist_csf2_crosswalk.json` against `catalogs_nist_csf_2_0.csv` (106 NIST CSF 2.0 subcategories) |
| `analysis/exp1_formative_and_missingness.py` | UK CSBS 2023 to 2025 structural skip-routing audit (`95.44%` lost-row attribution) and unrouted VIF/KR-20 diagnostics |
| `analysis/exp2_common_sample_and_mechanisms.py` | UK CSLS Waves 1 to 4 (`N = 3,061`, `2,196` firms; `n = 865` matched transitions, `575` firms) timing, dynamic, and Mundlak models |
| `analysis/exp3_sme_size_bridge_and_auc.py` | UK CSBS size-band associations (`N = 8,086`) and 2025 5-fold OOF ROC AUC comparisons (`+0.0162` paired lift) |
| `analysis/exp4_sensitivity_and_worked_examples.py` | Five-seed synthetic cohort evaluation (`5 x 10,000` profiles), polarity/unknown comparators, parity tests, and worked 18-employee trace |
| `analysis/retrospective_robustness.py` | Signed half-step boundary checks, equal-domain-centred consensus reference, and `[L, H]` completion bounds (`87.86%` multi-band span) |
| `analysis/results/*.json` | Committed deterministic outputs backing Tables 3 to 8 and Figures 1 to 4 in the manuscript |
| `data/README.md` & `data/CHECKSUMS.sha256` | Data access instructions and SHA-256 checksums for UK Data Archive End User Licence microdata and Eurostat `isoc_eb_ai` |

## Quick Start (No Licensed Microdata Required)

```bash
# 1. Verify all 26 NIST CSF 2.0 subcategory mappings
python3 analysis/verify_ids.py

# 2. Run 20,000-vector parity and property tests across Python, Node.js, and NumPy
python3 instrument/test_scoring.py

# 3. Verify all committed JSON outputs and run retrospective robustness checks
python3 analysis/test_iciit_upgrades.py
python3 analysis/retrospective_robustness.py
```

## Full Empirical & Synthetic Pipeline

After obtaining the UK Data Archive Stata files listed in `DATA.md` (`SN 8969, 8971, 9067, 9101, 9284, 9285, 9356, 9404`) and Eurostat `isoc_eb_ai.json`:

```bash
pip install -r requirements.txt
bash analysis/run_all.sh
```
