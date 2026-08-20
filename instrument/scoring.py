#!/usr/bin/env python3
"""Reference scoring engine for the RAISR-SME instrument (bank v1, frozen 2026-08-18).

Standalone and dependency-free: the arithmetic below is the same arithmetic the validation
battery runs (``analysis/instrument_validation.py``), lifted out so that scoring the instrument
does not require pandas, numpy, statsmodels, or the licensed microdata. ``test_scoring.py``
checks the two engines against each other, and against the JavaScript port in ``scoring.js``,
digit for digit.

Three details are load-bearing and must not be "tidied":

1. **Order of operations.** A dimension score is ``(sum(items) / n) * 100`` -- the division
   first, exactly as ``numpy.mean(...) * 100`` does it. Rearranging to ``sum * 100 / n`` changes
   the last bit of the float.
2. **Summation order, and plain sequential addition.** Dimensions are summed in the bank's own
   key order and items in their bank order, because floating-point addition is not associative;
   ``display_order`` is for things a person reads, never for things that get summed. The
   accumulation is an explicit loop rather than ``sum()``, because since Python 3.12 ``sum()``
   compensates its float error and so disagrees with the two engines this one must match -- on
   a fifth of random response vectors, in the last bits.
3. **Half-open bands.** ``[lo, hi)``, so a score sitting exactly on a cut point belongs to the
   band above. This is decided by the last bit of the total, which is why (1) and (2) matter --
   and why the total is quantised to nine decimals before the band is read off (see
   :func:`quantize`).

Usage as a library::

    from scoring import load_bank, score_answers
    bank = load_bank()
    result = score_answers({"H1": "no", "A1": "yes", ...}, bank)
    result.total, result.band, result.dimensions

Usage as a command (reads a JSON object of answers on stdin, or scores an archetype)::

    python3 scoring.py --archetype solo-micro-no-governance
    echo '{"H1": "no", "H2": "dk"}' | python3 scoring.py
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

BANK_PATH = Path(__file__).resolve().parent / "bank_v1.json"

#: Respondent-facing answers. Anything else is rejected rather than coerced -- a typo that
#: silently became "don't know" would score half a point of risk and never be noticed.
ANSWERS = ("yes", "no", "dk")


@dataclass(frozen=True)
class Score:
    """The result of scoring one completed questionnaire.

    Attributes:
        total: Weighted total on 0-100. Higher means *more* exposure, not more maturity.
        band: One of ``Low``, ``Medium``, ``High``, ``Critical``.
        dimensions: Per-dimension score on 0-100, keyed by dimension id.
        unknown_count: How many items were answered ``dk``. Reported, never hidden: a total
            resting on eight "don't know"s is a different object from one resting on none.
    """

    total: float
    band: str
    dimensions: Dict[str, float]
    unknown_count: int


def load_bank(path: Optional[Path] = None) -> Dict:
    """Load the frozen item bank.

    Args:
        path: Bank location. Defaults to ``bank_v1.json`` beside this file.

    Returns:
        The parsed bank. Key order is preserved, and is load-bearing (see module docstring).

    Raises:
        FileNotFoundError: If the bank is missing.
        ValueError: If the bank does not hold the expected 25 items in 6 dimensions.
    """
    bank_path = path or BANK_PATH
    with open(bank_path, encoding="utf-8") as handle:
        bank = json.load(handle)

    n_items = sum(len(d["items"]) for d in bank["dimensions"].values())
    if n_items != bank["meta"]["item_count"] or len(bank["dimensions"]) != 6:
        raise ValueError(
            f"bank is not v1: {n_items} items in {len(bank['dimensions'])} dimensions"
        )
    return bank


def item_ids(bank: Dict) -> List[str]:
    """Every item id, in the order the engine sums them (bank order, not display order)."""
    return [item["id"] for dim in bank["dimensions"].values() for item in dim["items"]]


def risk_of(answer: Optional[str], risk_when: str) -> float:
    """Map one respondent answer onto risk in [0, 1].

    Gap items (``risk_when == "no"``) carry risk when a control is *absent*; exposure items
    (A1-A4, V1, ``risk_when == "yes"``) carry risk when the exposure is *present*. A single
    global Yes=0 mapping inverts the AI dimension -- that was the defect corrected at the v1
    freeze, recorded in ``freeze_record.fixes_at_freeze``.

    Args:
        answer: ``"yes"``, ``"no"``, ``"dk"``, or None (treated as ``"dk"``).
        risk_when: ``"yes"`` or ``"no"``, declared per item by the bank.

    Returns:
        1.0 (risk present), 0.0 (risk absent), or 0.5 (don't know).

    Raises:
        ValueError: On an answer outside :data:`ANSWERS`.
    """
    if answer is None or answer == "dk":
        return 0.5
    if answer not in ANSWERS:
        raise ValueError(f"answer must be one of {ANSWERS}, got {answer!r}")
    if risk_when == "yes":
        return 1.0 if answer == "yes" else 0.0
    return 1.0 if answer == "no" else 0.0


def quantize(value: float) -> float:
    """Round to nine decimals before a band boundary is tested.

    Bands are half-open, so a vector whose exact total is 40 must read ``Medium``. Accumulated
    left to right the same vector can land at 39.999999999999996 and read ``Low`` -- and this is
    not hypothetical: across 50,000 random response vectors, 83 total to exactly 40, 65 or 85,
    about one respondent in 600. Nine decimals sits far below any difference a person could act
    on and far above the ~1e-14 accumulation noise.
    """
    return round(value * 1e9) / 1e9


def band_for(total: float, bands: Dict[str, List[float]]) -> str:
    """The band a total falls in, half-open ``[lo, hi)``, after :func:`quantize`."""
    quantized = quantize(total)
    for label, (low, high) in bands.items():
        if low <= quantized < high:
            return label
    raise ValueError(f"total {total} falls in no band -- bank bands do not cover 0-100")


def score_risks(risks: Dict[str, float], bank: Dict) -> Score:
    """Score a vector of already risk-coded responses (0 / 0.5 / 1 per item id).

    This is the arithmetic the paper's validation battery runs. :func:`score_answers` is the
    respondent-facing wrapper around it.

    Args:
        risks: Item id -> risk in [0, 1]. Every item in the bank must be present.
        bank: A loaded bank.

    Returns:
        The :class:`Score`.

    Raises:
        KeyError: If an item is missing from ``risks``.
        ValueError: If a risk value falls outside [0, 1], or the total falls in no band.
    """
    for value in risks.values():
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"risk values must lie in [0, 1], got {value!r}")

    # Accumulated with an explicit loop, NOT with builtin sum(). Since Python 3.12 sum() applies
    # Neumaier compensated summation to floats, which is *more* accurate than adding left to
    # right -- and therefore disagrees with both engines this one has to match. On 1,023 of 5,000
    # random response vectors the compensated total differs from the sequential total in the last
    # bits (56.125 against 56.12499999999999), which is enough to move a vector across a band cut
    # point. Parity means reproducing the reference arithmetic, not improving on it.
    dimensions: Dict[str, float] = {}
    for name, spec in bank["dimensions"].items():
        items = spec["items"]
        accumulator = 0.0
        for item in items:
            accumulator += float(risks[item["id"]])
        dimensions[name] = (accumulator / len(items)) * 100

    weights = bank["weights"]
    total = 0.0
    for name in dimensions:
        total += dimensions[name] * weights[name]

    band = band_for(total, bank["bands"])
    unknown = sum(1 for value in risks.values() if float(value) == 0.5)
    return Score(total=total, band=band, dimensions=dimensions, unknown_count=unknown)


def score_answers(answers: Dict[str, Optional[str]], bank: Dict) -> Score:
    """Score a set of respondent answers.

    Args:
        answers: Item id -> ``"yes"`` / ``"no"`` / ``"dk"``. Items left out are scored as
            ``"dk"``, which costs half a point of risk rather than being skipped -- an
            unanswered item is missing information, and missing information is exposure.
        bank: A loaded bank.

    Returns:
        The :class:`Score`.
    """
    risks = {}
    for spec in bank["dimensions"].values():
        for item in spec["items"]:
            risks[item["id"]] = risk_of(answers.get(item["id"]), item["risk_when"])
    return score_risks(risks, bank)


def ranked_actions(score: Score, bank: Dict) -> List[Dict]:
    """Order the six dimensions by their weighted contribution to the total, largest first.

    **This ranking is a presentation choice, not a result from the paper.** The instrument
    defines a total, six dimension scores, four bands, and one action per (dimension, band); it
    does not define what to fix first. Ranking by ``dimension_score x weight`` reads "largest
    gap" as "largest contribution to the total", so the item that moves the score most is fixed
    first -- one defensible reading among several. Ranking by raw score, or by remediation cost,
    would order the same result differently. Anywhere this list is shown to a respondent, say so.

    Ties break by weight, then by display order, so the output is deterministic.

    Args:
        score: A computed :class:`Score`.
        bank: The bank the score came from.

    Returns:
        One row per dimension: ``dimension``, ``label``, ``score``, ``weight``,
        ``contribution``, ``band`` (that dimension's own band), ``action``, ``criterion_status``.
    """
    rows = []
    for index, name in enumerate(bank["display_order"]):
        value = score.dimensions[name]
        weight = bank["weights"][name]
        band = band_for(value, bank["bands"])
        rows.append({
            "dimension": name,
            "label": bank["dimensions"][name]["label"],
            "score": value,
            "weight": weight,
            "contribution": value * weight,
            "band": band,
            "action": bank["action_plans"][name][band],
            "criterion_status": bank["dimensions"][name]["criterion_status"],
            "order": index,
        })
    rows.sort(key=lambda row: (-row["contribution"], -row["weight"], row["order"]))
    return rows


def _format(score: Score, bank: Dict) -> str:
    """Render a score for a terminal."""
    lines = [
        f"Total {score.total:.1f}/100   band {score.band}"
        f"   ({score.unknown_count} item(s) answered \"don't know\")",
        "",
        f"{'dimension':<28}{'score':>7}{'weight':>8}{'contrib':>9}  next step",
    ]
    for row in ranked_actions(score, bank):
        lines.append(
            f"{row['label']:<28}{row['score']:>7.1f}{row['weight']:>8.2f}"
            f"{row['contribution']:>9.1f}  {row['action']}"
        )
    lines += [
        "",
        "Higher is worse: the total is exposure, not maturity. The ordering above is a",
        "presentation choice (weighted contribution); the instrument does not define one.",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """Score answers from stdin, or a named archetype from the bank."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--archetype",
        help="score one of the bank's archetypes instead of reading stdin",
    )
    parser.add_argument("--bank", type=Path, default=None, help="path to bank_v1.json")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--list-items", action="store_true", help="print the 25 items in display order and exit"
    )
    args = parser.parse_args(argv)

    bank = load_bank(args.bank)

    if args.list_items:
        for name in bank["display_order"]:
            print(f"\n[{bank['dimensions'][name]['label']}]")
            for item in bank["dimensions"][name]["items"]:
                risky = "Yes" if item["risk_when"] == "yes" else "No"
                print(f"  {item['id']:<4} ({risky} = risk)  {item['q']}")
        return 0

    if args.archetype:
        matches = [a for a in bank["archetypes"] if a["id"] == args.archetype]
        if not matches:
            available = ", ".join(a["id"] for a in bank["archetypes"])
            print(f"unknown archetype {args.archetype!r}; available: {available}", file=sys.stderr)
            return 2
        score = score_risks(matches[0]["responses"], bank)
    else:
        try:
            answers = json.load(sys.stdin)
        except json.JSONDecodeError as error:
            print(f"stdin is not JSON: {error}", file=sys.stderr)
            return 2
        score = score_answers(answers, bank)

    if args.json:
        print(json.dumps(
            {
                "total": score.total,
                "band": score.band,
                "dimensions": score.dimensions,
                "unknown_count": score.unknown_count,
            },
            indent=2,
        ))
    else:
        print(_format(score, bank))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
