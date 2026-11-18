# RAISR-SME: Rapid AI and Information Security Readiness for Small and Medium-Sized Enterprises

Open 25-item ternary (`Yes` / `No` / `Don't know`) cyber-AI self-assessment instrument, three bit-exact client-side/offline scoring engines, and deterministic two-arm empirical and Monte Carlo replication suite accompanying our **ICIIT 2027** (ACM ICPS) paper:

> **RAISR-SME: Polarity-Separated Cyber-AI Risk Triage Under Epistemic Uncertainty and Longitudinal Breach Reporting Salience in Small and Medium-Sized Enterprises**
> Tran Duc Le, Thang Le Dinh, Manh Chien Vu, and Thi Chau Giang Tran

- **Interactive Zero-Telemetry Browser App**: https://raisr-sme.vercel.app
- **Source & Replication Repository**: https://github.com/tranducle/RAISR-SME
- **Code License**: MIT (`LICENSE`) | **Item Bank License**: CC BY 4.0 (`instrument/bank_v1.json`)

## Repository Structure

| Directory / File | Contents |
| :- | :- |
| `instrument/bank_v1.json` | Frozen 25-item ternary item bank across 6 dimensions (`LCM = 1200` rational weights, per-item `risk_when` polarity, action plans) |
| `instrument/nist_csf2_crosswalk.json` | Verified crosswalk mapping all 25 items to 26 unique NIST CSF 2.0 subcategory IDs, NIST AI RMF 1.0, and CISA CPG/KEV anchors |
| `instrument/scoring.py` | Zero-dependency Python 3.9+ reference scoring engine (`1e-9` boundary quantization in `bank_v1.json` key order) |
| `instrument/scoring.js` | Zero-dependency browser/Node.js JavaScript scoring engine (digit-for-digit parity with `scoring.py`) |
| `instrument/test_scoring.py` | Automated property and 20,000-vector cross-engine parity test suite |
| `analysis/run_all.sh` | Single-command entry script running NIST ID verification, cross-engine parity, `exp1` to `exp4`, and output assertions |
| `analysis/verify_ids.py` | Standalone verifier checking `nist_csf2_crosswalk.json` against `catalogs_nist_csf_2_0.csv` (106 NIST CSF 2.0 subcategories) |
| `analysis/exp1_formative_and_missingness.py` | UK CSBS 2023 to 2025 skip-routing waterfall audit and unrouted formative VIF (`< 3.3`) diagnostics |
| `analysis/exp2_common_sample_and_mechanisms.py` | UK CSLS Waves 1 to 4 (`N = 3,061`, `2,196` firms; `n = 865` multi-wave transitions, `575` firms) timing, dynamic persistence, and Mundlak suite |
| `analysis/exp3_sme_size_bridge_and_auc.py` | Split-ballot-normalized UK CSBS size-band regressions (`N = 8,086`), CSLS Medium-SME bridge, and 5-fold OOF ROC AUC |
| `analysis/exp4_sensitivity_and_worked_examples.py` | Two-stage Monte Carlo simulation (`5 x 10,000` SME profiles), `2x2` ablations, uninflated Eurostat check, Dirichlet stability, and 18-employee trace |
| `analysis/results/*.json` | Committed deterministic JSON outputs backing every table and figure in the manuscript |
| `data/README.md` & `data/CHECKSUMS.sha256` | Data access instructions and SHA-256 checksums for UK Data Archive End User Licence microdata and Eurostat `isoc_eb_ai` |

## Quick Start (No Licensed Microdata Required)

```bash
# 1. Verify all 26 NIST CSF 2.0 subcategory mappings
python3 analysis/verify_ids.py

# 2. Run 20,000-vector parity and property tests across Python, Node.js, and NumPy
python3 instrument/test_scoring.py

# 3. Verify all committed ICIIT 2027 JSON outputs
python3 analysis/test_iciit_upgrades.py
```

## Full Empirical & Monte Carlo Replication

After obtaining the UK Data Archive Stata files listed in `data/README.md` (`SN 8969, 8971, 9067, 9101, 9284, 9285, 9356, 9404`) and Eurostat `isoc_eb_ai.json`:

```bash
pip install -r analysis/requirements.txt
bash analysis/run_all.sh
```

## Design Notes & Validity Boundaries

1. **Higher score means higher exposure (`[0, 100]`)**: Twenty protective gap items score `1.0` on `No`, five technological exposure items (`A1` to `A4` on AI/LLM adoption and `V1` on cloud dependence) score `1.0` on `Yes`, and `Don't know` scores `0.5` under a uniform `Beta(1,1)` Laplace prior.
2. **Gross exposure floor**: Because `A1` to `A4` and `V1` capture gross technological exposure surface in v1.0, an active multi-tool AI and cloud-dependent SME satisfying all 20 protective controls carries a composite exposure floor of `18.333` (`Low` overall band, `< 40`) and an AI domain flag of `100.0` pending conditional AI-mitigation gates in Stage 2.
3. **Two-arm scope separation**: Arm A (`exp4`) validates the 25-item cyber-AI specification normatively and synthetically across 50,000 simulated SME profiles; Arm B (`exp1` to `exp3`) evaluates 3-to-8-item non-AI baseline security proxy subsets in UK CSBS (`N = 8,086`) and UK CSLS (`N = 3,061`, `>= 50` employees; zero micro/small longitudinal panel firms).
