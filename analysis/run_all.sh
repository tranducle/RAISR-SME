#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "[1/7] Verifying NIST CSF 2.0 subcategory crosswalk (26 unique IDs across 25 items)..."
python3 analysis/verify_ids.py -w

echo "[2/7] Running cross-runtime scoring parity suite (Python stdlib, Node.js V8, NumPy)..."
python3 instrument/test_scoring.py -n 20000

if [ -d "${REPO_ROOT}/../data/UKDA-9356-stata" ] || [ -d "${REPO_ROOT}/data/UKDA-9356-stata" ]; then
  echo "[3/7] Running exp1: Skip-routing waterfall and formative VIF audit..."
  python3 analysis/exp1_formative_and_missingness.py
  echo "[4/7] Running exp2: Clean panel timing, dynamic persistence, and Mundlak decomposition..."
  python3 analysis/exp2_common_sample_and_mechanisms.py
  echo "[5/7] Running exp3: Split-ballot SME size strata and 5-fold OOF ROC AUC..."
  python3 analysis/exp3_sme_size_bridge_and_auc.py
  echo "[6/7] Running exp4: Two-stage Monte Carlo sensitivity, ablations, and worked SME trace..."
  python3 analysis/exp4_sensitivity_and_worked_examples.py
else
  echo "[3-6/7] Licensed UKDA Stata microdata not present locally; verifying committed JSON outputs..."
fi

echo "[7/7] Running ICIIT 2027 output integrity and regression suite..."
python3 analysis/test_iciit_upgrades.py
echo "ALL CHECKS PASSED."
