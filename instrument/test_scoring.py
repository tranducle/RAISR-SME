#!/usr/bin/env python3
"""Check the scoring engine against its own fixtures, and against the JavaScript port.

Run it with nothing installed::

    python3 instrument/test_scoring.py

A scoring engine is a small pile of arithmetic whose errors are silent -- an inverted dimension
still returns a plausible number, and a band read off the wrong side of a cut point still shows a
respondent a word. So the checks below are about the failure modes that have actually occurred in
this instrument, not about coverage for its own sake:

1. **Fixtures.** The bank ships five archetypes with the total and band they must produce. These
   are exact-match: the all-risk archetype totals exactly 85.000, sitting *on* the Critical cut
   point, where one bit of drift changes what a respondent is told.
2. **Polarity.** The v1 freeze corrected a defect where a single global Yes=0 mapping inverted the
   AI-exposure dimension: an AI-free firm scored 100 and a heavy AI user scored 0. The test asserts
   the direction of all five exposure items (A1-A4, V1) separately from the twenty gap items.
3. **Boundaries.** Vectors landing exactly on 40 / 65 / 85 must fall in the band *above*.
4. **Monotonicity.** Raising any one item's risk never lowers the total.
5. **Don't know.** An unanswered item costs half a point of risk and is counted, not skipped.
6. **Cross-engine parity.** N pseudo-random vectors over {0, 0.5, 1}^25 scored by this engine and
   by ``scoring.js`` under Node, compared digit for digit on the total, on every dimension, and on
   the band. Skipped -- loudly -- if Node is absent.

Optionally (``--reference PATH``) the same vectors are compared against the numpy engine in
``analysis/instrument_validation.py``, which is the code that produced the paper's numbers. That
comparison carries a tolerance of 1e-9 rather than being exact, because numpy does not sum a
dimension the way a sequential loop does: its reduction is SIMD-vectorised, pairing lanes rather
than accumulating left to right, and floating-point addition is not associative. The residual is
~1e-14 on a 0-100 scale. Bands are compared after quantisation on both sides, which is the
comparison that means anything -- see ``quantize`` in ``scoring.py``.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scoring  # noqa: E402  (path is set immediately above)

TOLERANCE = 1e-9
EXPOSURE_ITEMS = {"A1", "A2", "A3", "A4", "V1"}


class Failure(Exception):
    """A check that did not hold."""


def check(condition: bool, message: str) -> None:
    """Raise :class:`Failure` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise Failure(message)


# --------------------------------------------------------------------------- fixtures


def test_archetypes(bank: Dict) -> int:
    """Every archetype reproduces the total and band recorded in the bank, exactly."""
    for archetype in bank["archetypes"]:
        result = scoring.score_risks(archetype["responses"], bank)
        check(
            result.total == archetype["expected_total"],
            f"{archetype['id']}: total {result.total!r} != {archetype['expected_total']!r}",
        )
        check(
            result.band == archetype["expected_band"],
            f"{archetype['id']}: band {result.band} != {archetype['expected_band']}",
        )
    return len(bank["archetypes"])


def test_polarity(bank: Dict) -> int:
    """Exposure items carry risk on Yes; gap items carry risk on No.

    Asserted per item rather than per dimension, because the defect this guards against was
    invisible at the total: an inverted AI dimension still returns a number in range.
    """
    checked = 0
    for name, spec in bank["dimensions"].items():
        for item in spec["items"]:
            expected = "yes" if item["id"] in EXPOSURE_ITEMS else "no"
            check(
                item["risk_when"] == expected,
                f"{item['id']} declares risk_when={item['risk_when']}, expected {expected}",
            )
            risky, safe = ("yes", "no") if expected == "yes" else ("no", "yes")
            check(scoring.risk_of(risky, item["risk_when"]) == 1.0, f"{item['id']}: {risky}")
            check(scoring.risk_of(safe, item["risk_when"]) == 0.0, f"{item['id']}: {safe}")
            check(scoring.risk_of("dk", item["risk_when"]) == 0.5, f"{item['id']}: dk")
            checked += 1

    # And at the dimension level, which is what the freeze defect actually broke.
    ai_free = {item["id"]: ("no" if item["id"] in EXPOSURE_ITEMS else "yes")
               for item in _all_items(bank)}
    result = scoring.score_answers(ai_free, bank)
    check(
        result.dimensions["ai_exposure"] == 0.0,
        f"a firm using no AI scores ai_exposure {result.dimensions['ai_exposure']}, expected 0",
    )
    check(result.total == 0.0, f"a firm answering safely everywhere scores {result.total}")
    return checked


def test_bands(bank: Dict) -> int:
    """Bands are half-open: a total sitting on a cut point belongs to the band above."""
    cut_points = [low for low, _ in bank["bands"].values()]
    for cut in cut_points:
        # A uniform vector at risk r totals exactly r*100 -- the weights sum to 1.
        risks = {item["id"]: cut / 100.0 for item in _all_items(bank)}
        result = scoring.score_risks(risks, bank)
        expected = next(label for label, (low, high) in bank["bands"].items() if low <= cut < high)
        check(
            result.band == expected,
            f"total {result.total!r} on cut point {cut} banded {result.band}, expected {expected}",
        )
    check(
        scoring.band_for(39.999999999999996, bank["bands"]) == "Medium",
        "a total one ulp below 40 must still read Medium after quantisation",
    )
    return len(cut_points) + 1


def test_monotonicity(bank: Dict, trials: int, rng: random.Random) -> int:
    """Raising one item's risk never lowers the total."""
    ids = scoring.item_ids(bank)
    for _ in range(trials):
        risks = {item_id: rng.choice([0.0, 0.5, 1.0]) for item_id in ids}
        before = scoring.score_risks(risks, bank).total
        target = rng.choice([i for i in ids if risks[i] < 1.0] or ids)
        risks[target] = min(1.0, risks[target] + 0.5)
        after = scoring.score_risks(risks, bank).total
        check(after >= before, f"raising {target} lowered the total: {before} -> {after}")
    return trials


def test_dont_know(bank: Dict) -> int:
    """An item left unanswered costs half a point of risk, and is counted."""
    result = scoring.score_answers({}, bank)
    check(result.total == 50.0, f"all-unanswered totals {result.total}, expected 50.0")
    check(result.unknown_count == 25, f"unknown_count {result.unknown_count}, expected 25")

    partial = {item["id"]: "yes" for item in _all_items(bank)}
    partial.pop("H1")
    check(scoring.score_answers(partial, bank).unknown_count == 1, "one omission, one unknown")
    return 3


def test_rejects_bad_input(bank: Dict) -> int:
    """A typo is refused, not coerced into 'don't know'."""
    checks = 0
    for bad in ("Yes", "y", "true", "unknown"):
        try:
            scoring.risk_of(bad, "no")
        except ValueError:
            checks += 1
        else:
            raise Failure(f"answer {bad!r} was accepted")
    try:
        scoring.score_risks({item["id"]: 2.0 for item in _all_items(bank)}, bank)
    except ValueError:
        checks += 1
    else:
        raise Failure("a risk value of 2.0 was accepted")
    return checks


# --------------------------------------------------------------------------- parity


def random_vectors(bank: Dict, count: int, rng: random.Random) -> List[Dict[str, float]]:
    """``count`` pseudo-random risk vectors over {0, 0.5, 1}^25."""
    ids = scoring.item_ids(bank)
    return [{i: rng.choice([0.0, 0.5, 1.0]) for i in ids} for _ in range(count)]


def score_with_node(vectors: List[Dict[str, float]], bank_path: Path) -> Optional[List[Dict]]:
    """Score every vector with ``scoring.js`` under Node, or None if Node is unavailable."""
    if not _have_node():
        return None
    harness = """
      const fs = require('fs');
      const RAISR = require(process.argv[2]);
      const bank = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
      const vectors = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
      const out = vectors.map(v => RAISR.scoreVector(v, bank));
      process.stdout.write(JSON.stringify(out));
    """
    with tempfile.TemporaryDirectory() as tmp:
        runner = Path(tmp) / "runner.js"
        payload = Path(tmp) / "vectors.json"
        runner.write_text(harness, encoding="utf-8")
        payload.write_text(json.dumps(vectors), encoding="utf-8")
        completed = subprocess.run(
            ["node", str(runner), str(HERE / "scoring.js"), str(bank_path), str(payload)],
            capture_output=True, text=True, check=True,
        )
    return json.loads(completed.stdout)


def test_js_parity(bank: Dict, bank_path: Path, vectors: List[Dict[str, float]]) -> Optional[int]:
    """The JavaScript port must agree digit for digit -- both engines sum sequentially.

    Compared with ``==`` on the parsed doubles rather than on their text: JSON.stringify emits
    the shortest round-tripping form, so a whole number crosses as ``75`` where Python writes
    ``75.0``. Both parse to the same float64, and float equality on finite values is a bit
    comparison -- exactly the standard this check wants.
    """
    js_results = score_with_node(vectors, bank_path)
    if js_results is None:
        return None
    for vector, js in zip(vectors, js_results):
        py = scoring.score_risks(vector, bank)
        check(py.total == js["total"],
              f"total drift: python {py.total!r} vs js {js['total']!r}")
        check(py.band == js["band"], f"band drift at {py.total}: {py.band} vs {js['band']}")
        for name, value in py.dimensions.items():
            check(value == js["dimensions"][name],
                  f"{name} drift: python {value!r} vs js {js['dimensions'][name]!r}")
    return len(vectors)


def load_reference(path: Path) -> Optional[Tuple[object, Dict]]:
    """Import the numpy engine that produced the paper's numbers, or None if unavailable."""
    import importlib.util

    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
    except ImportError:
        return None
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("reference_engine", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- any import-time failure means "unavailable", not "fail"
        return None
    return module, module.BANK


def test_reference_parity(bank: Dict, reference, vectors: List[Dict[str, float]]) -> int:
    """The paper's engine and this one agree within numpy's summation noise."""
    for vector in vectors:
        py = scoring.score_risks(vector, bank)
        ref_total, ref_band, ref_dims = reference.score_vector(vector)
        check(abs(py.total - ref_total) <= TOLERANCE,
              f"total drift beyond {TOLERANCE}: {py.total} vs {ref_total}")
        check(py.band == scoring.band_for(ref_total, bank["bands"]),
              f"band drift at {py.total}: {py.band} vs {ref_band}")
        for name, value in py.dimensions.items():
            check(abs(value - ref_dims[name]) <= TOLERANCE,
                  f"{name} drift beyond {TOLERANCE}: {value} vs {ref_dims[name]}")
    return len(vectors)


# --------------------------------------------------------------------------- plumbing


def _all_items(bank: Dict) -> List[Dict]:
    return [item for dim in bank["dimensions"].values() for item in dim["items"]]


def _have_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--vectors", type=int, default=5000,
                        help="how many random vectors to compare across engines")
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--bank", type=Path, default=scoring.BANK_PATH)
    parser.add_argument("--reference", type=Path,
                        default=HERE.parent / "analysis" / "instrument_validation.py",
                        help="the numpy engine to compare against, if its dependencies are present")
    args = parser.parse_args(argv)

    bank = scoring.load_bank(args.bank)
    rng = random.Random(args.seed)
    vectors = random_vectors(bank, args.vectors, rng)

    results: List[Tuple[str, str]] = []
    failures = 0

    plan = [
        ("archetypes", lambda: test_archetypes(bank)),
        ("polarity", lambda: test_polarity(bank)),
        ("band boundaries", lambda: test_bands(bank)),
        ("monotonicity", lambda: test_monotonicity(bank, 500, rng)),
        ("don't know", lambda: test_dont_know(bank)),
        ("input validation", lambda: test_rejects_bad_input(bank)),
        ("parity vs scoring.js", lambda: test_js_parity(bank, args.bank, vectors)),
    ]

    reference = load_reference(args.reference)
    if reference is None:
        plan.append(("parity vs paper engine", lambda: None))
    else:
        module, ref_bank = reference
        if ref_bank["dimensions"] != bank["dimensions"]:
            raise SystemExit("the reference engine is loaded against a different item bank")
        plan.append(("parity vs paper engine", lambda: test_reference_parity(bank, module, vectors)))

    for name, run in plan:
        try:
            count = run()
        except Failure as failure:
            results.append((name, f"FAIL  {failure}"))
            failures += 1
        else:
            if count is None:
                results.append((name, "SKIP  dependency not installed -- not a pass"))
            else:
                results.append((name, f"ok    {count} check(s)"))

    width = max(len(name) for name, _ in results)
    for name, outcome in results:
        print(f"{name:<{width}}  {outcome}")
    skipped = sum(1 for _, outcome in results if outcome.startswith("SKIP"))
    print(f"\n{len(results) - failures - skipped} passed, {failures} failed, {skipped} skipped")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
