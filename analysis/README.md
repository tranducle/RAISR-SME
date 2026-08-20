# Analysis

The scripts behind every estimate the paper reports, and their committed outputs.

```bash
pip install -r requirements.txt
# obtain the microdata first — see ../data/README.md
python3 analysis/arm1_cross_sectional.py
python3 analysis/arm2_panel_lagged.py
python3 analysis/instrument_validation.py
python3 analysis/auxiliary_analyses.py
```

Run from the **repository root**, not from this directory: each script resolves `data/` and
`results/` relative to its own location, so the paths work either way, but the commands above are
the ones that have been exercised.

---

## What each script is

| Script | Needs | Emits | Reported in the paper as |
| --- | --- | --- | --- |
| `arm1_cross_sectional.py` | CSBS 9404, 9285, 9101 | `results/arm1_cross_sectional.json` | Arm 1 — cross-sectional criterion test |
| `arm2_panel_lagged.py` | CSLS 9356 | `results/arm2_panel_lagged.json` | Arm 2 — lagged-posture panel test |
| `instrument_validation.py` | CSBS ×3, CSLS 9356, Eurostat | `results/instrument_validation.json` | Coverage audit, reliability, scoring mechanics |
| `auxiliary_analyses.py` | CSBS 9404 + 8971 | `results/auxiliary_analyses.json` | Secondary: matched-pair diagnostic, trend series |
| `csbs_common.py` | — | — | **Library, not an entry point** (see below) |

`csbs_common.py` is imported by the other CSBS scripts for wave loading, item risk-coding, the core
score, AUC, KR-20 and the power calculation. It is executable, but running it directly fits the
*earlier* bivariate specification — retained because `arm1_cross_sectional.py` extends rather than
replaces it. **Nothing the paper reports comes from its `__main__`.** The same caution applies to the
provisional item→variable map inside it: the mapping the paper reports is the audited one in
`instrument_validation.py`.

---

## The four analyses, in one paragraph each

### `arm1_cross_sectional.py` — Arm 1

Weighted GLM Binomial (`freq_weights` = normalised survey weights) of reported breach
(`Cybercrime_all`, among those asked) on core-score *z* + size + sector, one model per wave. Size and
sector are in the primary model because the pre-registered specification requires them, not because
they improved it. Robustness: the same specification unweighted. Reported per wave: n business, n
asked, n complete-case, outcome rate, 80%-power detectable OR (Hsieh et al. 1998), odds ratio per SD
with 95% CI, rank-based AUC, and missingness counts.

The core score is a **gap** score, so an OR below 1 means *more gaps, fewer reported breaches*. The
result is negative and is reported as such. `detection_diagnostic` in the output carries the
plain-language version — the breach rate among firms with a formal policy against those without.

### `arm2_panel_lagged.py` — Arm 2

The timing test Arm 1 cannot run: posture measured in one wave, outcome in the next, on the same
organisations. Two specification decisions were pre-committed rather than chosen after seeing the
estimates, and both are visible in the output:

1. **Frame.** The primary frame is business organisations; the high-income charity sub-sample is
   estimated separately as a robustness frame rather than pooled into the headline. All three frames
   (`business`, `charity`, `pooled`) are emitted.
2. **Sample harmonisation.** The lagged logit and the firm-fixed-effects model run on **one**
   harmonised sample, so the two estimates differ by specification and not by who is in them. The
   maximal-sample FE is kept as a labelled robustness row.

Logits are clustered by `LongId` with size and wave fixed effects; the FE row is a within-firm linear
probability model. The 5-item row is the same specification without cyber insurance. Each model in
`models[]` carries its own `label`, `n`, `n_clusters`, estimate, CI, `p`, and a `direction` field
(`paradox` / `protective`) so a row cannot be quoted without its sign.

### `instrument_validation.py` — the engine of record

Reads `instrument/bank_v1.json` and runs four things: (1) a **coverage audit** mapping each item onto
variables in each dataset by scanning variable labels for concept keywords — label-level only, and
the output says so; (2) **KR-20 reliability** with item-total correlations on the CSBS criterion-core
items; (3) **scoring mechanics** — five archetypes, monotonicity, band boundaries, action coverage,
and a ±20% weight-sensitivity sweep; (4) a coverage × respondent-burden comparison against the
closest published SME self-assessment instruments.

`score_vector()` in this file is the arithmetic the paper's numbers came from.
`instrument/scoring.py` is a dependency-free port of it, and `instrument/test_scoring.py` holds the
two side by side — so the engine here is checkable without pandas, numpy, or licensed data.

### `auxiliary_analyses.py` — secondary

A governance matched-pair diagnostic within size × sector strata on CSBS 9404, and the 2016–2025
posture trend series. Both are **descriptive and secondary**: the matched-pair comparison is
unadjusted and uses a proxy governance index, and its own output note says "suggestive only". The
trend crosses the 2020 CSBS mode change (face-to-face → online), which is why it is a trend
descriptive and not an estimate.

---

## Reading the committed results

`results/*.json` are the outputs the paper reports. A successful replication overwrites them with
identical values.

Three fields are easy to misread:

- **`or_per_sd` in Arm 1 is per SD of the *gap* score.** Below 1 = more gaps, fewer reported
  breaches. The direction of the substantive claim is the opposite of the direction of the number.
- **`coef_pp` in Arm 2** is a percentage-point coefficient from a linear probability model. It does
  not share a scale with `or_per_sd` and cannot be plotted on the same axis without conversion.
- **`kr20` values in `reliability_csbs`** are computed on 4–6 mapped items, not on the 25-item bank,
  and two of the three waves rest on 24 and 25 complete cases. They are reported because omitting
  them would be worse, not because they support the instrument.

## What is not reproducible from this repository

The `n` in every model depends on the licensed microdata, so the numbers cannot be re-derived from
what is committed here — only re-checked against it once you have obtained the data. The instrument
half of the repository has no such dependency: bank, engines, and the full test suite run offline.
