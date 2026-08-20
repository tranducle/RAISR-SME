#!/usr/bin/env python3
"""Validation battery for item bank v1 -- coverage, reliability, and scoring mechanics.

Reads instrument/bank_v1.json (frozen 2026-08-18) and executes:
  1. Coverage audit: item -> variable mapping per dataset (CSBS 9404/9285/9101, CSLS 9356)
     by scanning variable labels for concept keywords. Honest: only label-level mapping;
     semantic equivalence is asserted per item in the report.
  2. Reliability: KR-20 + item-total on the CSBS criterion-core mapped items (complete cases).
  3. Archetypes and mechanics: 5 synthetic but data-grounded firm profiles (ARCHETYPES below);
     the deterministic scoring engine; monotonicity, band-boundary, action-coverage, and
     +/-20% weight-sensitivity tests.
  4. Baseline comparison: coverage x respondent-burden mapping against the closest published
     SME self-assessment instruments.

score_vector() here is the engine of record. instrument/scoring.py is a dependency-free port of
it for anyone who wants to score the questionnaire without pandas, numpy, or the licensed
microdata, and instrument/test_scoring.py checks the two against each other.

Output: analysis/results/instrument_validation.json
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)

BANK = json.load(open(HERE.parent / "instrument" / "bank_v1.json"))
DIMS = BANK["dimensions"]
WEIGHTS = BANK["weights"]
BANDS = BANK["bands"]

# keyword -> item concept mapping for label scan
KEYWORDS = {
    "H1": ["policy"], "H2": ["train"], "H3": ["insur"], "H4": ["backup"],
    "H5": ["admin", "privileg", "access control"], "H6": ["monitor", "antivirus", "anti-virus", "security software"],
    "G1": ["responsible", "in charge"], "G2": ["review"], "G3": ["incident", "documented"],
    "G4": ["supplier", "outsourc", "third party"], "G5": ["report"],
    "I1": ["incident", "response", "plan"], "I2": ["contact"], "I3": ["exercise", "test"],
    "D1": ["data"], "D2": ["backup"], "D3": ["cloud", "stored"],
    "V1": ["cloud", "saas", "online service"], "V2": ["depend", "software", "list"],
}
# explicit known CSLS mappings (from EDA 2026-08-18)
CSLS_MAP = {
    "G1": ["bgoverna", "bgovernb"], "G2": ["gova", "rulesa"], "G3": ["incidman"],
    "G4": ["supplyrisk"], "I1": ["incidman"], "I3": ["exercise"],
    "H2": ["boardtrainfreq"], "H3": ["insurex"],
}

WAVES = {
    "2025": DATA / "UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta",
    "2024": DATA / "UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta",
    "2023": DATA / "UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta",
}
CSLS = DATA / "UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta"


def variable_labels(path, n=0):
    itr = pd.read_stata(path, iterator=True)
    labels = itr.variable_labels()
    if n:
        itr.read(n)
    return labels


def scan_labels(labels):
    """Return item -> list of matching variables (label keyword scan)."""
    out = {}
    for item, kws in KEYWORDS.items():
        hits = [c for c, lab in labels.items() if lab and any(k in str(lab).lower() for k in kws)]
        out[item] = hits
    return out


def coverage_audit():
    report = {"per_dataset": {}}
    # CSBS waves
    for w, p in WAVES.items():
        labels = variable_labels(p)
        report["per_dataset"][f"CSBS_{w}"] = scan_labels(labels)
    # CSLS
    labels = variable_labels(CSLS)
    csls_scan = scan_labels(labels)
    for item, vars_ in CSLS_MAP.items():
        merged = sorted(set(csls_scan.get(item, [])) | set(vars_))
        csls_scan[item] = merged
    report["per_dataset"]["CSLS_9356"] = csls_scan
    # per-item coverage summary across criterion-core dimensions
    core_items = list(DIMS["security_hygiene"]["items"]) + list(DIMS["incident_readiness"]["items"])
    report["core_item_coverage"] = {}
    for it in core_items:
        iid = it["id"]
        ds = {}
        for dsname, scan in report["per_dataset"].items():
            v = scan.get(iid, [])
            if v:
                ds[dsname] = v
        report["core_item_coverage"][iid] = ds
    return report


def risk_item(df, col, risk_vals=None, yes_zero=True):
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    s = df[col].astype(str)
    out = pd.Series(np.nan, index=df.index)
    na = {"Not asked", "Not applicable", "nan", "Don't know", "Refused"}
    if yes_zero:
        out[s.eq("Yes")] = 0
        out[s.eq("No")] = 1
    else:
        out[s.isin(risk_vals)] = 1
        out[~s.isin(risk_vals) & ~s.isin(na)] = 0
    return out


def reliability_wave(df, mapped):
    items = {}
    for iid, cols in mapped.items():
        if cols:
            items[iid] = risk_item(df, cols[0])
    mat = pd.DataFrame(items)
    used = [c for c in mat.columns if mat[c].notna().any()]
    mat = mat[used].dropna()
    if mat.shape[1] < 2 or len(mat) < 10:
        return {"n_items": mat.shape[1], "n_cases": int(len(mat)), "kr20": None, "item_total": {}}
    k = mat.shape[1]
    p = mat.mean()
    var_total = mat.sum(axis=1).var(ddof=1)
    kr20 = (k / (k - 1)) * (1 - (p * (1 - p)).sum() / var_total) if var_total > 0 else np.nan
    itc = {c: float(np.corrcoef(mat[c], mat.sum(axis=1) - mat[c])[0, 1]) for c in mat.columns}
    return {"n_items": k, "n_cases": int(len(mat)), "kr20": float(kr20), "item_total": itc}


def reliability():
    res = {}
    for w, p in WAVES.items():
        df = pd.read_stata(p, convert_categoricals=True)
        labels = variable_labels(p)
        scan = scan_labels(labels)
        core = list(DIMS["security_hygiene"]["items"]) + list(DIMS["incident_readiness"]["items"])
        mapped = {it["id"]: scan.get(it["id"], []) for it in core}
        res[w] = reliability_wave(df, mapped)
    return res


# ---- archetypes + mechanics ----
ARCHETYPES = [
    ("solo-micro-no-governance", "0-9", "none"),
    ("solo-micro-policy-only", "0-9", "policy"),
    ("small-trained", "10-49", "policy+training"),
    ("small-insured", "10-49", "policy+training+insurance"),
    ("medium-mature", "50-249", "full-hygiene"),
]
PATTERNS = {
    "none": {"H1": 1, "H2": 1, "H3": 1, "H4": 1, "H5": 1, "H6": 1,
             "G1": 1, "G2": 1, "G3": 1, "G4": 1, "G5": 1,
             "I1": 1, "I2": 1, "I3": 1, "I4": 1,
             "A1": 0, "A2": 0, "A3": 0, "A4": 0, "D1": 1, "D2": 1, "D3": 1, "V1": 1, "V2": 1, "V3": 1},
    "policy": {"H1": 0},
    "policy+training": {"H1": 0, "H2": 0},
    "policy+training+insurance": {"H1": 0, "H2": 0, "H3": 0},
    "full-hygiene": {"H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0, "H6": 0,
                     "G1": 0, "G2": 0, "G3": 0, "I1": 0, "I2": 0, "I3": 0},
}
# DK value 0.5 variants for band-boundary test: build custom vectors directly below.


def full_response(pattern):
    base = PATTERNS["none"].copy()
    base.update(pattern)
    return base


def score_vector(resp):
    dim_scores = {}
    for d, spec in DIMS.items():
        vals = [resp[it["id"]] for it in spec["items"]]
        dim_scores[d] = float(np.mean(vals)) * 100
    total = sum(dim_scores[d] * WEIGHTS[d] for d in dim_scores)
    band = next(b for b, (lo, hi) in BANDS.items() if lo <= total < hi)
    return total, band, dim_scores


def mechanics():
    arch = []
    for name, size, pattern in ARCHETYPES:
        resp = full_response(PATTERNS[pattern] if pattern != "none" else {})
        total, band, dims = score_vector(resp)
        arch.append({"name": name, "size": size, "total": round(total, 1), "band": band})
    # monotonicity: improving one No->Yes never lowers total (verified by construction over 25 probes)
    mono_ok = True
    for name, size, pattern in ARCHETYPES:
        resp = full_response(PATTERNS[pattern] if pattern != "none" else {})
        base_total, _, _ = score_vector(resp)
        for iid in resp:
            if resp[iid] == 1:
                r2 = dict(resp); r2[iid] = 0
                t2, _, _ = score_vector(r2)
                if t2 > base_total + 1e-9:
                    mono_ok = False
    # band boundaries: craft vectors that land exactly at 40/65/85
    boundaries = {}
    for target in [40, 65, 85]:
        # uniform risk r on all items -> total = r*100; dimension weights sum to 1
        r = target / 100.0
        resp = {it["id"]: r for d in DIMS for it in DIMS[d]["items"]}
        total, band, _ = score_vector(resp)
        boundaries[target] = {"total": round(total, 1), "band": band}
    # action coverage: every band x dimension has >= 1 action in ACTION_PLANS
    action_ok = all(len(ACTION_PLANS[d][b]) > 0 for d in ACTION_PLANS for b in BANDS)
    # weight sensitivity: +/-20% each weight, band stability
    sens = {}
    for d in WEIGHTS:
        for delta in [-0.20, 0.20]:
            w2 = dict(WEIGHTS)
            w2[d] = max(0.0, WEIGHTS[d] * (1 + delta))
            z = sum(w2.values())
            w2 = {k: v / z for k, v in w2.items()}
            band_shifts = 0
            for name, size, pattern in ARCHETYPES:
                resp = full_response(PATTERNS[pattern] if pattern != "none" else {})
                t0, b0, _ = score_vector(resp)
                dim_scores = {}
                for dd, spec in DIMS.items():
                    dim_scores[dd] = float(np.mean([resp[it["id"]] for it in spec["items"]])) * 100
                t2 = sum(dim_scores[dd] * w2[dd] for dd in dim_scores)
                b2 = next(b for b, (lo, hi) in BANDS.items() if lo <= t2 < hi)
                if b2 != b0:
                    band_shifts += 1
            sens[f"{d}_{delta * 100:+.0f}%"] = band_shifts
    return {"archetypes": arch, "monotonicity_pass": mono_ok,
            "band_boundaries": boundaries, "action_coverage_pass": action_ok,
            "weight_sensitivity_band_shifts": sens}


ACTION_PLANS = {
    "security_hygiene": {"Low": "Enable multi-factor authentication and daily backups; get a basic policy.",
                         "Medium": "Add staff training and cyber insurance review.",
                         "High": "Restrict admin accounts; verify backup restoration quarterly.",
                         "Critical": "Immediate hygiene remediation sprint; external review."},
    "incident_readiness": {"Low": "Write a one-page who-to-call plan.",
                           "Medium": "Document the plan; assign a named owner.",
                           "High": "Exercise the plan annually.",
                           "Critical": "Run a tabletop exercise now; plug detected gaps."},
    "ai_exposure": {"Low": "Inventory which AI tools staff actually use.",
                    "Medium": "Add a no-personal-data rule for public AI tools.",
                    "High": "Formal usage policy; vendor AI-terms review.",
                    "Critical": "Stop high-risk AI use until governed."},
    "data_handling": {"Low": "Map where business data lives.",
                      "Medium": "Written data-handling policy; backups tested.",
                      "High": "Encrypt sensitive data; test restore twice a year.",
                      "Critical": "Data audit + breach-report readiness review."},
    "governance": {"Low": "Name one person responsible for security.",
                   "Medium": "Annual owner/board security review on the calendar.",
                   "High": "Written responsibilities; supplier security checks.",
                   "Critical": "Governance review with external support."},
    "vendor_dependence": {"Low": "List your critical software and services.",
                          "Medium": "Check security track records before adoption.",
                          "High": "Supplier security requirements in contracts.",
                          "Critical": "Dependency review; contingency for key vendors."},
}


def baseline_arm():
    """Coverage x burden mapping vs C1 (Sawang & Sornlertlamvanich) + TrustX positioning."""
    return {
        "vs_C1": {
            "c1": "AI maturity framework of internalized and ecosystem-embedded capabilities (arXiv:2603.08728); conceptual framework, no scored instrument",
            "raisr_sme": "25-item scored instrument, six dimensions, four bands, prioritized actions, public-data traceability per item",
            "coverage_overlap": "AI adoption / capability maturity concepts overlap on the AI-exposure and governance dimensions",
            "burden": "C1: framework (reading-level); RAISR-SME: ~20-minute single-respondent completion",
        },
        "trustx_position": "TrustX ARC risk-tiers internally created agentic AI systems for enterprise AI-governance practitioners; different population (enterprises), object (agentic systems), and output (risk-tier classification) than RAISR-SME.",
        "same_firm_correlation": "Not computable as specified: the full 25-item bank is not fielded in any public dataset; the criterion-core subset (3-6 mapped items in CSBS) is the only overlap. Reported instead: KR-20 on mapped core items (see reliability).",
    }


def eurostat_extra_indicators():
    d = json.load(open(DATA / "eurostat/isoc_eb_ai.json"))
    id_order = d["id"]; sizes = d["size"]; vals = d["value"]
    idx = {n: d["dimension"][n]["category"]["index"] for n in id_order}

    def decode(k):
        coords = []; n = int(k)
        for s in reversed(sizes):
            coords.append(n % s); n //= s
        return dict(zip(id_order, list(reversed(coords))))

    out = {}
    for indic in ["E_AI_TGE2", "E_AI_PDI"]:
        want = {"indic_is": idx["indic_is"][indic], "geo": idx["geo"]["EU27_2020"],
                "time": idx["time"]["2025"], "unit": idx["unit"]["PC_ENT"]}
        row = {}
        for s in ["GE10", "10-49", "50-249", "GE250"]:
            want["size_emp"] = idx["size_emp"][s]
            for k, v in vals.items():
                c = decode(k)
                if all(c[nn] == want[nn] for nn in want):
                    row[s] = v
                    break
            else:
                row[s] = None
        out[indic] = row
    return out


def main():
    results = {"bank": BANK["meta"]["name"], "bank_version": BANK["meta"]["version"],
               "bank_status": BANK["meta"]["status"]}
    results["eurostat_extra"] = eurostat_extra_indicators()
    results["coverage_audit"] = coverage_audit()
    results["reliability_csbs"] = reliability()
    results["mechanics"] = mechanics()
    results["baseline_arm"] = baseline_arm()
    (OUT / "instrument_validation.json").write_text(json.dumps(results, indent=2, default=str))

    print("=== Eurostat extra indicators (EU27, 2025) ===")
    print("  E_AI_TGE2:", results["eurostat_extra"]["E_AI_TGE2"])
    print("  E_AI_PDI :", results["eurostat_extra"]["E_AI_PDI"])
    print("\n=== Core-item coverage (criterion-core items -> datasets) ===")
    for iid, ds in results["coverage_audit"]["core_item_coverage"].items():
        print(f"  {iid}: { {k: v for k, v in ds.items()} }")
    print("\n=== Reliability (CSBS mapped core, complete cases) ===")
    for w, r in results["reliability_csbs"].items():
        print(f"  {w}: n_items={r['n_items']} n_cases={r['n_cases']} KR-20={r['kr20']}")
        if r["item_total"]:
            print("    item-total:", {k: round(v, 2) for k, v in r["item_total"].items()})
    print("\n=== Mechanics ===")
    for a in results["mechanics"]["archetypes"]:
        print(f"  {a['name']:28s} size={a['size']:6s} total={a['total']:5.1f} band={a['band']}")
    print("  monotonicity:", results["mechanics"]["monotonicity_pass"])
    print("  band boundaries:", results["mechanics"]["band_boundaries"])
    print("  action coverage:", results["mechanics"]["action_coverage_pass"])
    print(f"  weight sensitivity (band shifts / {len(ARCHETYPES)} archetypes):",
          results["mechanics"]["weight_sensitivity_band_shifts"])
    print("\n=== Baseline arm ===")
    print("  same_firm_correlation:", results["baseline_arm"]["same_firm_correlation"])
    print(f"Saved: {OUT / 'instrument_validation.json'}")


if __name__ == "__main__":
    main()