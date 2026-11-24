# Transfer and run instructions (updated November 22, 2026)

Read README.md, then MEMORY.md. docs/coding_handbook.md has the field rules and docs/edge_case_coverage.md maps the tests to EDGE_CASES.md.

```sh
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q                                       # 230 tests
cra preflight                                             # offline: 44/44 hashes, no key needed
cra estimate --group all                                  # offline cost estimate, no spend
cra rehearse                                              # MOCK plumbing check on the 4 development PDFs
```

## Paid run order (nothing is sent until you pass --yes-spend)
```sh
export ANTHROPIC_API_KEY=...          # you set this; never put it in a file or chat
cra preflight --online                # model identity, ledger headroom (no spend)
cra extract --group development --run-id dev1 --yes-spend            # add --batch for half price
cra flags --run-id dev1 ; cra validate --run-id dev1                 # review together
cra extract --group calibration --run-id cal1 --yes-spend --batch
cra freeze --output reports/freeze_v1.json --note "after calibration"
cra extract --group holdout --run-id hold1 --freeze reports/freeze_v1.json --yes-spend --batch
cra packet --group holdout --output reviews/packet_holdout            # build this BEFORE looking at predictions
cra review submit-reference --forms <dir> --reviewer "Name" --started ... --finished ... --attest-blind [--coverage coverage.json]   # coverage lists the tables you coded per document; see reviews/packet_holdout/INSTRUCTIONS.md
cra predictions --database data/staging/staging.sqlite --group holdout --output reports/holdout_predictions.json
cra score --reference reviews/submissions/reference_*.json --predictions reports/holdout_predictions.json --output reports/holdout_scores.json
cra review mark-reviewed --run-id dev1 --pe-id ... ; cra review accept --run-id dev1 --pe-id ...
cra export --scores reports/holdout_scores.json --indicators reports/mortgage_indicators_reviewed.json
```
`cra export` writes `exports/vN/` only if every gate passes; otherwise `exports/DRAFT-.../` with the unmet gates.

Never glob `data/pilot_cache`; follow the final manifest. Do not treat the partial baseline or the rehearsal database as research data.
