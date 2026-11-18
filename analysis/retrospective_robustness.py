"""Post-review robustness checks on frozen synthetic inputs; no field validation."""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json
import os

import numpy as np

ANALYSIS = Path(__file__).resolve().parent
REPO = ANALYSIS.parent
RESULTS_DIR = ANALYSIS / "results"
os.environ.setdefault("RAISR_SUMMARY_DIR", str(RESULTS_DIR / "summaries"))
spec = importlib.util.spec_from_file_location("original_exp4", ANALYSIS / "exp4_sensitivity_and_worked_examples.py")
exp4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp4)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tiers(scores):
    return np.digitize(scores, [40.0, 65.0, 85.0], right=False)


def run():
    bank_path = REPO / "instrument" / "bank_v1.json"
    original_path = RESULTS_DIR / "exp4_sensitivity_and_worked_examples.json"
    original = json.loads(original_path.read_text())
    bank = json.loads(bank_path.read_text())
    inputs = {
        str(p.relative_to(REPO)): sha(p)
        for p in [bank_path, original_path, ANALYSIS / "exp4_sensitivity_and_worked_examples.py"]
    }
    dim_keys = list(bank["dimensions"])
    weights = np.array([bank["weights"][d] for d in dim_keys])
    item_counts = np.array([len(bank["dimensions"][d]["items"]) for d in dim_keys])
    item_weights = np.repeat(weights / item_counts, item_counts)
    assert len(item_weights) == 25 and np.isclose(item_weights.sum(), 1.0)
    output_rows, seed_results = [], []
    for seed in original["seeds"]:
        cohort = exp4.generate_two_stage_cohort(original["n_profiles_per_seed"], original["strata_marginals"], bank, seed)
        z, mask = cohort["Z"], cohort["M_dk"]
        risk = np.where(mask, .5, z)
        score = exp4.score_matrix(risk, bank, weights)
        base_band = tiers(score)
        distance = np.min(np.abs(score[:, None] - np.array([40., 65., 85.])), axis=1)
        old_flip = np.zeros(len(score), dtype=bool)
        signed_flip = np.zeros(len(score), dtype=bool)
        for j in range(25):
            old = risk.copy()
            old[:, j] = np.where(risk[:, j] < 1., np.minimum(1., risk[:, j] + .5), .5)
            old_flip |= tiers(exp4.score_matrix(old, bank, weights)) != base_band
            for direction in [-.5, .5]:
                changed = risk.copy()
                changed[:, j] = np.clip(risk[:, j] + direction, 0., 1.)
                signed_flip |= tiers(exp4.score_matrix(changed, bank, weights)) != base_band
        bins = {}
        for low, high, label in [(0, 2, "0_to_2"), (2, 5, "2_to_5"), (5, 10, "5_to_10"), (10, 101, "10_or_more")]:
            selected = (distance >= low) & (distance < high)
            count = int(selected.sum())
            flips = int(signed_flip[selected].sum())
            bins[label] = {"n": count, "flip_count": flips, "flip_rate": flips / count if count else None}
            if seed == 202702:
                old_label = {"0_to_2": "0_to_2_pts", "2_to_5": "2_to_5_pts", "5_to_10": "5_to_10_pts", "10_or_more": "gt_10_pts"}[label]
                saved = original["primary_seed_202702"]["boundary_flip_by_distance"][old_label]
                assert count == saved["n_profiles"]
                assert np.isclose(old_flip[selected].mean(), saved["any_single_halfstep_flip_rate"])
        assert not np.any(signed_flip[distance > 100 * item_weights.max() / 2 + 1e-8])
        low_score = exp4.score_matrix(np.where(mask, 0., z), bank, weights)
        high_score = exp4.score_matrix(np.where(mask, 1., z), bank, weights)
        assert np.allclose(score, (low_score + high_score) / 2, atol=2e-9, rtol=0)
        assert np.all((low_score <= score + 1e-8) & (score <= high_score + 1e-8))
        assert np.allclose(low_score[~mask.any(axis=1)], high_score[~mask.any(axis=1)])
        span = tiers(low_score) != tiers(high_score)

        rng = np.random.default_rng(seed + 99)
        policy_draws = rng.dirichlet(np.full(6, 5 / 6), size=500)
        votes = np.zeros((len(z), 4), dtype=int)
        for draw in policy_draws:
            candidate = tiers(exp4.score_matrix(z, bank, draw))
            for level in range(4):
                votes[:, level] += candidate == level
        reference = votes.argmax(axis=1)
        naive = np.where(mask, 0., 1 - cohort["raw_yes"])
        models = {
            "naive": exp4.score_matrix(naive, bank, item_counts / 25),
            "aligned_dk0": low_score,
            "raisr": score,
            "dk075": exp4.score_matrix(np.where(mask, .75, z), bank, weights),
            "dk1": high_score,
            "available_case": exp4.score_matrix(np.where(mask, 0., z), bank, weights, (~mask).astype(float)),
            "prevalence": exp4.score_matrix(np.where(mask, cohort["empirical_p"][None, :], z), bank, weights),
        }
        concordance = {name: float((tiers(val) == reference).mean()) for name, val in models.items()}
        seed_results.append({
            "seed": seed,
            "boundary_bins": bins,
            "completion_span_fraction": float(span.mean()),
            "mean_interval_width": float((high_score - low_score).mean()),
            "uniform_reference_concordance": concordance,
        })
    pooled = {}
    for name in seed_results[0]["boundary_bins"]:
        n = sum(s["boundary_bins"][name]["n"] for s in seed_results)
        flip_count = sum(s["boundary_bins"][name]["flip_count"] for s in seed_results)
        pooled[name] = {"n": n, "flip_count": flip_count, "flip_rate": flip_count / n if n else None}
        output_rows.append({"analysis": "signed_halfstep", "condition": name, "n": n, "value": flip_count / n if n else ""})
    ref_means = {
        name: float(np.mean([s["uniform_reference_concordance"][name] for s in seed_results]))
        for name in seed_results[0]["uniform_reference_concordance"]
    }
    gains = [s["uniform_reference_concordance"]["raisr"] - s["uniform_reference_concordance"]["naive"] for s in seed_results]
    worked = original["three_engine_parity_and_worked_case"]["worked_18emp_sme"]
    items = [it for d in bank["dimensions"].values() for it in d["items"]]
    answer_risk = np.array([
        .5 if worked["answers"][it["id"]] == "dk"
        else float((worked["answers"][it["id"]] == "yes") == (it["risk_when"] == "yes"))
        for it in items
    ])
    unknown = np.array([worked["answers"][it["id"]] == "dk" for it in items])
    worked_low = float(exp4.score_matrix(np.where(unknown, 0., answer_risk)[None, :], bank, weights)[0])
    worked_high = float(exp4.score_matrix(np.where(unknown, 1., answer_risk)[None, :], bank, weights)[0])
    assert np.isclose((worked_low + worked_high) / 2, worked["python_quantized_total"], atol=2e-9, rtol=0)
    result = {
        "design": "retrospective exploratory check, designed after original results and reviews",
        "input_hashes": inputs,
        "seeds": original["seeds"],
        "n_profiles": sum(original["n_profiles_per_seed"] for _ in seed_results),
        "boundary_bins": pooled,
        "uniform_reference_concordance_means": ref_means,
        "uniform_reference_gain_vs_naive_mean": float(np.mean(gains)),
        "uniform_reference_gain_vs_naive_seed_range": [min(gains), max(gains)],
        "mean_completion_span_fraction": float(np.mean([s["completion_span_fraction"] for s in seed_results])),
        "worked_score_completion_interval": {
            "low": worked_low,
            "mid": worked["python_quantized_total"],
            "high": worked_high,
            "interpretation": "conditional score completions under fixed normative weights; not a confidence interval or event probability",
        },
        "seed_results": seed_results,
        "checks": {
            "original_primary_boundary_reproduced": True,
            "completion_midpoint_and_containment": True,
            "zero_unknown_interval_degenerate": True,
            "halfstep_max_change_bound": True,
        },
    }
    for name, val in ref_means.items():
        output_rows.append({"analysis": "uniform_reference", "condition": name, "n": result["n_profiles"], "value": val})
    for relative, digest in inputs.items():
        assert sha(REPO / relative) == digest
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "retrospective_robustness.json").write_text(json.dumps(result, indent=2) + "\n")
    with (RESULTS_DIR / "retrospective_robustness.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["analysis", "condition", "n", "value"])
        writer.writeheader()
        writer.writerows(output_rows)
    print(json.dumps({k: v for k, v in result.items() if k not in ["seed_results", "input_hashes"]}, indent=2))


if __name__ == "__main__":
    run()
