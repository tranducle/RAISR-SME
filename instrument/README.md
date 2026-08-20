# The instrument

Everything needed to field, score, and check RAISR-SME — with no data, no dependencies, and no
network.

| File | What it is |
| --- | --- |
| `bank_v1.json` | The frozen item bank. The only source of truth for wording, weights, bands, and action plans. |
| `scoring.py` | Reference engine + CLI. Pure standard-library Python 3.9+. |
| `scoring.js` | Browser port of the same arithmetic, for interactive use. |
| `test_scoring.py` | Eight checks, including cross-engine parity. |

```bash
python3 scoring.py --list-items                       # every item, with its polarity
python3 scoring.py --archetype small-trained          # score a worked example
echo '{"H1":"no","A1":"yes"}' | python3 scoring.py    # score your own answers
python3 scoring.py --json < answers.json              # machine-readable output
python3 test_scoring.py -n 20000 --seed 7             # prove the engines agree
```

---

## Bank schema

```jsonc
{
  "meta":          { "version": "v1", "item_count": 25, "scale": "risk 0-100, higher = more exposure", … },
  "freeze_record": { "weights": …, "items": …, "fixes_at_freeze": [ … ] },
  "dimensions": {
    "security_hygiene": {
      "label": "Security hygiene",
      "items": [
        { "id": "H1",
          "q": "Does your business have a formal cybersecurity policy?",
          "risk_when": "no",                                  // ← polarity, per item
          "anchor": "CSBS 9404 policy_comb: Yes 2,070 / No 37 (among asked)" }
      ]
    }, …
  },
  "display_order":  ["security_hygiene", "incident_readiness", "ai_exposure", … ],
  "weights":        { "security_hygiene": 0.25, … },
  "bands":          { "Low": [0, 40], "Medium": [40, 65], "High": [65, 85], "Critical": [85, 101] },
  "response_scale": { "options": ["Yes", "No", "Don't know"], "risk_when_no": …, "risk_when_yes": … },
  "action_plans":   { "<dimension>": { "Low": "…", "Medium": "…", "High": "…", "Critical": "…" } },
  "archetypes":     [ { "id": …, "responses": {…}, "expected_total": …, "expected_band": … } ],
  "known_and_accepted": [ … ]
}
```

Every item carries an **`anchor`**: the public-survey variable and its marginal distribution that the
item is grounded in. It is what makes the item bank auditable rather than asserted — a reader can
open the same dataset and check the anchor.

### `dimensions` key order is load-bearing; `display_order` is not

The engines sum dimensions in the **key order of the `dimensions` object**, and items in their order
within it. Floating-point addition is not associative, so re-ordering the keys changes the last bit
of the total, which can change the band on a vector that lands on a cut point. `display_order` is
what a human reads and is never used for arithmetic. Reformatting the JSON is safe; **sorting its
keys is not.**

---

## Polarity — the thing to get right

Twenty items are **gap** items (`risk_when: "no"`): risk when the control is absent.
Five are **exposure** items (`risk_when: "yes"`): **A1, A2, A3, A4, V1** — risk when the exposure is
present.

| Answer | `risk_when: "no"` | `risk_when: "yes"` |
| --- | :---: | :---: |
| Yes | 0.0 | **1.0** |
| No | **1.0** | 0.0 |
| Don't know | 0.5 | 0.5 |

A single global `Yes = 0` mapping scores an AI-free firm at AI-exposure **100** and a heavy AI user
at **0** — the dimension inverted. That was a real defect in the draft bank, and correcting it is
recorded in `freeze_record.fixes_at_freeze` along with the other fix made at the freeze (a
double-barrelled backup item that charged a firm without backups twice, across two separately
weighted dimensions).

The archetype `solo-micro-no-governance` is the standing check: every gap item failing, no AI in use,
total **85.0 / Critical**, and **AI exposure 0.0**. If that dimension ever reads 100, the polarity has
been re-broken.

---

## Scoring, exactly

```
item risk       ∈ {0, 0.5, 1}                      per the polarity table above
dimension score = (Σ item risks / n_items) × 100    division BEFORE the ×100
total           = Σ (dimension score × weight)      in bank key order, sequential addition
band            = the [lo, hi) interval containing round(total × 1e9) / 1e9
```

Three details in `scoring.py` look tidy-able and are not — the module docstring states each, and
`test_scoring.py` fails if any is "fixed":

1. **Division before multiplication.** `(sum / n) * 100` matches `numpy.mean(...) * 100`;
   `sum * 100 / n` does not, in the last bit.
2. **Explicit summation loops, not `sum()`.** Since Python 3.12 the builtin applies Neumaier
   compensated summation — more accurate than the reference engines, and therefore *wrong* for
   parity. On 1,023 of 5,000 random vectors the two totals differ (`56.125` vs `56.12499999999999`).
3. **Quantise to nine decimals before the band lookup.** Bands are half-open, so exactly 40.0 must
   read `Medium`. Across 50,000 random vectors, 83 land exactly on a cut point — about one
   respondent in 600.

---

## The test suite

```
$ python3 test_scoring.py

archetypes              ok    5 check(s)   every archetype hits its expected total, band, dimensions
polarity                ok   25 check(s)   per item and per dimension, both directions
band boundaries         ok    5 check(s)   40/65/85 resolve upward
monotonicity            ok  500 check(s)   flipping any item toward risk never lowers the total
don't know              ok    3 check(s)   dk = 0.5, counted and surfaced
input validation        ok    5 check(s)   unknown answers and out-of-range risks are rejected
parity vs scoring.js    ok 5000 check(s)   EXACT — bit comparison on float64, not a tolerance
parity vs paper engine  ok 5000 check(s)   1e-9; bands compared after quantisation on both sides

8 passed, 0 failed, 0 skipped
```

`-n` sets the random-vector count and `--seed` makes a run reproducible. When Node or numpy is
missing, the affected check prints `SKIP … -- not a pass` and the summary counts it as skipped.
**A skip is never reported as a pass**, because an absent dependency is exactly the situation in
which a silent green line would be most misleading.

---

## Using it in your own work

The bank is **CC BY 4.0** — field it, translate it, adapt the wording, cut it down. Two requests, one
of them technical:

- If you change items, weights, or bands, **bump `meta.version`**. `scoring.py` validates only the
  25-item/6-dimension shape, so a silently modified v1 will still score, and its numbers will not be
  comparable to anyone else's.
- If you re-implement the scoring, run `test_scoring.py` against your engine. The parity harness is
  the reason three implementations agree here; it will work the same way on a fourth.

## Known and accepted

Recorded in `known_and_accepted` in the bank itself, and repeated here because it belongs in front of
anyone using the instrument:

- **G3** (incident responsibilities written down) and **I1** (written incident-response plan) both
  anchor to the same CSLS variable. They are distinct constructs — accountability against runbook —
  and are kept as separate items. The shared anchor is a limit of the *source coverage*, not a
  double-count in the scoring.
- **Reliability of the full 25-item battery is open.** It has never been fielded as a battery. Only
  the CSBS-mapped core (policy, training, insurance) admits a criterion test, and the coverage audit
  in `analysis/instrument_validation.py` reports exactly how thin that is.
