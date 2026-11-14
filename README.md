# PipelineGuard

**Contract-driven CSV pipeline checks, reviewable repairs, and verification evidence — by Tabish Syed.**

PipelineGuard finds schema changes, missing values, invalid numeric types, duplicate keys, and failures in declared arithmetic transformations. It proposes bounded repairs from explicit contract rules, validates the repaired candidate, and replays a fixed plan against independently authored cases. It runs locally using Python's standard library, with no model API calls.

## Quick start

Python 3.11+ is required. From a source checkout:

```sh
python -m unittest discover -s tests -v
python -m pipelineguard.demo
```

Open `runs/demo/inspection/report.html`, `runs/demo/repair/report.html`, and `runs/demo/verification/report.html`. The demo writes to a new directory and refuses to overwrite previous evidence. To repeat it, use `python -m pipelineguard.demo --out runs/demo-2`.

The fixture has two seeded problems: `unit_cost` replaces `unit_price`, and one row lacks a quantity. Its contract explicitly approves that alias and defines missing quantities as `1`. PipelineGuard proposes those two repairs and computes per-line revenue using decimal arithmetic. A healthy control must pass without findings. Six separate replay cases check unseen quantities, fractional prices, zero, canonical headers, and faults that must remain blocked.

## Inspect your CSV

```sh
python -m pipelineguard inspect \
  --input examples/orders-broken.csv \
  --contract examples/contract.json \
  --out runs/inspection
```

Read the HTML/JSON report and review `runs/inspection/plan.json`. Inspection returns exit code **1** when it finds problems; that is expected for this broken example.

## Apply a reviewed plan to a separate output

```sh
python -m pipelineguard apply \
  --input examples/orders-broken.csv \
  --contract examples/contract.json \
  --plan runs/inspection/plan.json \
  --out runs/repair
```

`apply` checks that every operation is permitted by the contract and that the contract hash matches the plan. It writes `repaired.csv`, including computed columns, only when all post-repair checks pass. It always writes a validation report for a valid plan, including cases where data remains invalid. Inputs and existing output directories are never overwritten. Running `apply` is the explicit application step; inspection alone does not change data.

## Verify the fixed plan on separate cases

```sh
python -m pipelineguard verify \
  --contract examples/contract.json \
  --plan runs/inspection/plan.json \
  --cases examples/heldout.json \
  --out runs/verification
```

The planner accepts only the inspected CSV and contract. The verifier reads expected results after the plan has been selected, replays that plan, and compares both validation verdicts and exact computed output strings. Cases include invalid data expected to fail; a successful verification means the tool accepted and rejected the appropriate cases, not that every input was repaired.

The example cases are public synthetic fixtures, not a secure hidden benchmark. There is no claim that a model has been evaluated or that this small suite predicts performance on other data.

## Contract format

See `examples/contract.json`. Supported rules:

| Rule | Behavior |
| --- | --- |
| `type` | Required: `string`, `integer`, or `decimal`; numeric values must be finite |
| `nullable` | Allow blank/whitespace-only cells; defaults to false |
| `unique` | Require distinct nonblank typed values within a column |
| `aliases` | Explicit source names eligible for a rename when the canonical column is absent |
| `default` | An explicit CSV string used only for blank cells in an existing or renamed column |
| `allow_extra_columns` | Defaults to false; additional headers produce findings |
| `transforms` | Ordered `multiply`, `divide`, `add`, or `subtract` operations over earlier numeric columns |

Transform fields are `output`, `op`, `left`, and `right`. Output names must be new. Transformation outputs already present in an input CSV are rejected to avoid silent overwrite. Numeric operations use Python Decimal with precision 28 and its default half-even rounding. Values are formatted as decimal strings without unnecessary trailing zeros. This is not a configurable accounting policy: explicit currency-scale rounding is a future feature.

Missing whole columns are reported and never invented. Ambiguous aliases are not guessed. Invalid numbers, duplicate IDs, and division by zero remain failures. Defaults are business decisions authored in the contract; a syntactically valid default does not establish business correctness. No arbitrary Python or SQL is executed.

## CLI and reports

Exit codes: **0** clean/verified, **1** findings or verification mismatch, **2** input/setup error. Output directories must be new. `report.html` is portable alongside `report.json`; it uses no external scripts or services. Reports include column names, row numbers, contract/plan fingerprints, and finding codes, but omit raw input rows. Repaired CSV files contain your data and should stay private. Generated `runs/` files are ignored by Git.

For an installed CLI, create a virtual environment and run `python -m pip install -e .`, then use `pipelineguard` in place of `python -m pipelineguard`. The demo uses repository fixtures and should be run from a source checkout.

## Validation

`AGENTS.md` records the required test-driven development workflow and mandatory unit/component and integration checks. `docs/evaluation.md` records the fixture results. GitHub Actions runs the tests and demo on Python 3.11 and 3.12 and uploads generated evidence.

## Limits and next milestone

This release supports small CSV files loaded into memory and declarative arithmetic pipelines. It does not monitor running schedulers, execute existing Python/dbt/Airflow jobs, infer undocumented schemas, detect statistical distribution drift, or generate arbitrary code repairs. It has no language-model planner. Treat local contracts and fixture files as trusted inputs, and review business rules before applying a plan.

Next: add an optional model-assisted explanation/planning layer that produces the same constrained plan format, then evaluate it separately from this deterministic checker and verifier.

## Authorship

Created by Tabish Syed with AI assistance for implementation, testing, and documentation. MIT License; see LICENSE.
