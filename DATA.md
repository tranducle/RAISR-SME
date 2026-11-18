# Data Access and Integrity Manifest (`RAISR-SME`)

This repository distributes no licensed survey microdata. Detailed dataset descriptions, exact extracted Stata paths, and download instructions live in `data/README.md`, with cryptographic verification hashes in `data/CHECKSUMS.sha256`.

## 1. Licensed UK Data Archive Microdata (Withheld Under End User Licence)

The UK Cyber Security Breaches Survey (`SN 9101` 2023, `SN 9285` 2024, `SN 9404` 2025, plus trend context `SN 8971`) and UK Cyber Security Longitudinal Survey (`SN 9356` Waves 1 to 4 Master Panel, plus wave slices `SN 8969`, `SN 9067`, `SN 9284`) are governed by the UK Data Archive End User Licence (<https://ukdataservice.ac.uk>), which prohibits public redistribution of respondent-level microdata. Registered researchers may obtain identical files from the catalogue URLs in `data/README.md` and verify exact byte equivalence via:

```bash
cd data && shasum -a 256 -c CHECKSUMS.sha256
```

## 2. Public AI Adoption Marginals (`isoc_eb_ai`)

European Union enterprise AI adoption rates (`17.00%` small, `30.36%` medium, `55.03%` large; `doi:10.2908/ISOC_EB_AI`) are fetched directly from the Eurostat Dissemination API (`data/README.md` Section 3), with exact SHA-256 checksum verification (`2026-06-15` vintage) recorded in `data/CHECKSUMS.sha256`.

## 3. Public Normative Security Catalogs and Item Bank

- **RAISR-SME v1.0 Item Bank (`instrument/bank_v1.json`)**: Frozen 25-item ternary specification (`CC BY 4.0`).
- **NIST CSF 2.0 Subcategory Catalog (`analysis/catalogs_nist_csf_2_0.csv`)**: US Public Domain catalog containing 106 active subcategories used by `analysis/verify_ids.py` to check `instrument/nist_csf2_crosswalk.json` (`26/26` unique IDs verified).
- **CISA Known Exploited Vulnerabilities (KEV)**: Public catalog (<https://www.cisa.gov/known-exploited-vulnerabilities-catalog>), `2026-08-17` snapshot (`1,666` entries).
