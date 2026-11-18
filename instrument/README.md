# The RAISR-SME v1.0 Instrument (`instrument/`)

Everything needed to field, score, and verify the 25-item ternary RAISR-SME v1.0 self-assessment locally with zero external dependencies and zero network telemetry.

| File | Role |
| :- | :- |
| `bank_v1.json` | Frozen 25-item v1.0 item bank (`CC BY 4.0`): wording, polarity (`risk_when`), rational domain weights, triage bands, ranked action plans, and canonical archetypes. |
| `nist_csf2_crosswalk.json` | Item-by-item crosswalk mapping all 25 items to 26 verified NIST CSF 2.0 subcategory IDs, NIST AI RMF 1.0 functions, and CISA CPG/KEV anchors (`../analysis/verify_ids.py`). |
| `scoring.py` | Reference deterministic scoring engine and CLI (pure Python 3.9+ standard library). |
| `scoring.js` | Client-side browser JavaScript port implementing identical IEEE-754 arithmetic and 9-decimal quantization. |
| `test_scoring.py` | Eight-check verification suite, including bit-exact Python vs JavaScript vs reference-engine parity across 20,000+ random response vectors. |

## Quick CLI Commands

Run from the repository root:

- Score a built-in archetype or custom JSON vector via `python3 instrument/scoring.py`
- Verify NIST CSF 2.0 subcategory mappings via `python3 analysis/verify_ids.py`
- Run the 8-check cross-runtime parity suite across 20,000 vectors via `bash analysis/run_all.sh`

## Item Bank Structure and Load-Bearing Key Order

Each item in `bank_v1.json` carries its exact question text, polarity (`risk_when: "no"` for 20 protective control-gap items; `risk_when: "yes"` for 5 active AI/cloud exposure items `A1`, `A2`, `A3`, `A4`, `V1`), and public survey or catalog anchor.

- **Dictionary key order is load-bearing for IEEE-754 floating-point summation:** Both `scoring.py` and `scoring.js` sum items and dimensions sequentially in the dictionary key order of `bank_v1.json["dimensions"]`. `display_order` governs human UI presentation and ranked-action tie-breaking only. Never sort keys in `bank_v1.json`.

## Polarity and Epistemic Uncertainty (`Don't know = 0.5`)

| Respondent Answer | Control-Gap Items (`20` items, `risk_when: "no"`) | Exposure Items (`A1..A4, V1`, `risk_when: "yes"`) |
| :- | :-: | :-: |
| `Yes` | `0.0` | **`1.0`** |
| `No` | **`1.0`** | `0.0` |
| `Don't know` | `0.5` | `0.5` |

- Under zero-AI, non-cloud operations with all 20 controls satisfied, `R(0) = 0.0` (`Low`). Because `A1..A4` and `V1` measure gross technological exposure surface in v1.0, an active cloud-and-AI SME satisfying all 20 protective controls carries a deterministic gross exposure floor `R_min = 18.333333333` (`Low` overall tier, `< 40`, with `AI/LLM` domain score `S_3 = 100.0`).
- Archetype `solo-micro-no-governance` verifies non-AI Criticality reachability (`M3`): zero AI use (`S_3 = 0.0`) and failure across all 21 non-AI items yields `Q(R) = 85.0` (`Critical`).

## Deterministic Quantization Arithmetic

1. **Division before multiplication:** Dimension score `S_k = (sum_i r_i / m_k) * 100`.
2. **Explicit sequential loops (not Python 3.12 `sum()`):** Python 3.12's builtin `sum()` uses Neumaier compensated summation, which differs in raw `binary64` ulps on `13,323 / 20,006` vectors (`0` band flips). Explicit loops keep Python and JavaScript identical prior to quantization.
3. **Nine-decimal quantization (`Q(R) = round(R * 1e9) / 1e9`):** Snaps recurring `binary64` rationals (`LCM = 1200`) onto exact rational cutpoints (`Low` `[0, 40)`, `Medium` `[40, 65)`, `High` `[65, 85)`, `Critical` `[85, 100]`), achieving `20,006 / 20,006` (`100.000%`) three-runtime score and band parity (`exp4_sensitivity_and_worked_examples.py` and `test_scoring.py`, which also cross-checks the retained v1 reference engine in `../analysis/instrument_validation.py`).

## Licensing and Scope Notes

- `bank_v1.json` is licensed under **CC BY 4.0**; if items, weights, or bands are modified, increment `meta.version`.
- Items `G3` (written incident responsibilities) and `I1` (written incident-response plan) map to distinct NIST CSF 2.0 subcategories (`GV.RR-02` vs `RS.MA-01`) while sharing a closest public CSLS proxy anchor; Arm A (`exp4`) evaluates the full 25-item cyber-AI specification synthetically, whereas Arm B (`exp1..exp3`) evaluates non-AI UK CSBS/CSLS proxy subsets empirically.
