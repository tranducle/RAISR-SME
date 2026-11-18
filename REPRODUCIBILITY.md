# End-to-End Reproducibility Guide (`RAISR-SME`)

## Environment Requirements

- **Instrument Scoring & Parity (`instrument/`)**: Python 3.9+ standard library (plus Node.js 18+ for JavaScript parity checks and `numpy` for vectorized reference checks).
- **Empirical & Monte Carlo Analysis (`analysis/`)**: Python 3.14.5 with exact pinned dependencies in `requirements.txt` (`analysis/requirements.txt`):
  `pandas==2.3.3`, `numpy==2.4.6`, `scipy==1.17.1`, `statsmodels==0.14.6`.

Install dependencies from the repository root:

```bash
pip install -r requirements.txt
```

## 1. Public Offline Checks (No Licensed Microdata Required)

Verify NIST CSF 2.0 crosswalk integrity, run the 20,006-vector three-runtime IEEE-754 parity suite (`Python stdlib`, browser/Node `JavaScript`, `NumPy`), and assert all committed empirical and simulation JSON outputs:

```bash
python3 analysis/verify_ids.py
python3 instrument/test_scoring.py -n 20000
python3 analysis/test_iciit_upgrades.py
```

## 2. Full Empirical and Monte Carlo Pipeline

After downloading the UK Data Archive Stata `.dta` files and Eurostat `isoc_eb_ai.json` per `DATA.md` (either into `data/` inside the repository root or to the path set in `RAISR_DATA_DIR`), execute:

```bash
bash analysis/run_all.sh
```

`analysis/run_all.sh` runs seven deterministic steps:
1. NIST CSF 2.0 catalog crosswalk verification (`analysis/verify_ids.py -w`).
2. Cross-runtime parity verification over 20,000 random ternary vectors plus 6 canonical archetypes (`instrument/test_scoring.py -n 20000`).
3. Experiment 1 (`analysis/exp1_formative_and_missingness.py`): UK CSBS skip-routing attribution (`95.44%` pooled) and unrouted VIF/KR-20 diagnostics (`max VIF = 1.9144`).
4. Experiment 2 (`analysis/exp2_common_sample_and_mechanisms.py`): UK CSLS full-panel (`N = 3,061`, `2,196` firms) and consecutive-wave (`n = 865`, `575` firms) Mundlak, dynamic persistence (`OR = 3.1215`), cross-lagged, bootstrap (`B = 2,000`, `5` seeds), and 500-shuffle placebo tests.
5. Experiment 3 (`analysis/exp3_sme_size_bridge_and_auc.py`): Split-ballot-normalized UK CSBS size-stratum ORs (`N = 8,086`), Medium-SME CSLS bridge, and 5-fold OOF ROC AUC.
6. Experiment 4 (`analysis/exp4_sensitivity_and_worked_examples.py`): Five-seed two-stage Monte Carlo simulations (`5 x 10,000` profiles across MCAR/MNAR and Dirichlet regimes), uninflated hierarchical Eurostat check, `20,006`-vector runtime parity, and the 18-employee SME worked diagnostic trace (`Q(R) = 68.208333333`).
7. Output assertion suite (`analysis/test_iciit_upgrades.py`).
