# Fabric analytics automation

This directory contains the source-controlled Microsoft Fabric deployment for the
Travel Assistant analytics experience:

- deterministic learner and solution reverse-ETL notebooks;
- a serial per-tenant controller pipeline;
- the Apply/Revert User Data Function;
- the source-controlled TMDL semantic model and PBIR report.

The report visuals are not generated or modified by the notebook workflow.

## Generate the notebooks

`_gen_funnel_notebook.py` is the sole source for both delivered notebooks. Do not
edit either `.ipynb` directly.

```powershell
# Regenerate the checked-in learner and solution notebooks.
python analytics\fabric\_gen_funnel_notebook.py

# Generate into an isolated directory without touching delivered files.
python analytics\fabric\_gen_funnel_notebook.py `
  --output-dir .local\fabric-generation-check
```

Serialization is canonical UTF-8 with LF newlines and stable JSON ordering. An
explicit output directory is treated as isolated and rejects unexpected stale
notebook files.

Prove determinism and delivered-byte identity:

```powershell
python analytics\fabric\validate_fabric_assets.py --double-generate
```

The validator starts two independent clean Python processes in distinct empty
directories, compares learner and solution bytes and SHA-256 values between runs,
then compares both runs with the checked-in files. It never writes to the
checked-in notebook paths.

## Validate locally

```powershell
python analytics\fabric\validate_fabric_assets.py
python analytics\fabric\validate_controlled_demo4_source.py
python -m pytest analytics\fabric\tests -q
python analytics\scripts\run_integration_verification.py `
  --fail-fast --phase fabric-generation
```

The asset validator retains notebook semantic checks, validates the controller
pipeline, proves the checked-in canonical bytes, and scans owned deployment
sources plus PBIR/TMDL definitions for personal paths, credentials, and embedded
environment identifiers.

The controlled Demo 4 validator extracts evaluator source from each delivered
notebook, executes learner and solution copies independently, verifies their
bytes and schemas match the application evaluator, and compares exact results
over the complete fixture matrix. The matrix covers both tenants, active and
reverted states, missing measurement and measured zero, duplicates/conflicts,
malformed tokens, unknown deployments, wrong model mix, and incomplete
snapshots.

## Provision Fabric

`provision_fabric.py` is the sole implementation. It owns configuration,
preflight, prompting for development runs, deployment, validation, status, and
evidence. `Provision-Fabric.ps1` only forwards arguments to Python and returns
the Python exit code.

Development phases remain available:

```powershell
python analytics\fabric\provision_fabric.py --phase 1
python analytics\fabric\provision_fabric.py --phase 2 `
  --connection-id <cosmos-connection-id> --solution
python analytics\fabric\provision_fabric.py --phase report
```

Phase 2 deploys the single-tenant worker notebook and the
`RefreshAllDemoTenants` pipeline. The pipeline runs serially:

1. Analytics.
2. Marvel only after Analytics succeeds.

The normal report path deploys
`TravelAssistantAnalyticsReport.SemanticModel` from TMDL and
`TravelAssistantAnalyticsReport.Report` from PBIR. Compatibility import flags
exist for development, but are rejected by the staging contract.

## Staging contract and evidence

The canonical staging command is:

```powershell
python analytics\fabric\provision_fabric.py `
  --environment staging `
  --phase all `
  --solution `
  --connection-id <cosmos-connection-id> `
  --verify-semantic-model `
  --verify-report `
  --evidence-output .local\fabric-provision-staging-evidence.json
```

The equivalent thin-wrapper form is:

```powershell
.\analytics\fabric\Provision-Fabric.ps1 `
  --environment staging `
  --phase all `
  --solution `
  --connection-id <cosmos-connection-id> `
  --verify-semantic-model `
  --verify-report `
  --evidence-output .local\fabric-provision-staging-evidence.json
```

Evidence is JSON with:

- `status`: `Verified`, `Unverified`, or `Failed`;
- `environment`;
- timestamps and an explicit reason;
- workspace, mirror, notebook, pipeline, UDF, semantic-model, and report IDs;
- SHA-256 hashes for notebook, pipeline, UDF, TMDL, and PBIR sources;
- semantic-model query evidence and report-to-model validation evidence.

`Verified` is emitted only after source-controlled semantic-model/report
deployment and successful validation. Missing credentials, capacity,
connection, configuration, or infrastructure emits explicit `Unverified`
evidence and a non-zero exit. There is no success-shaped fallback.

For a safe local contract check that makes no cloud call:

```powershell
python analytics\fabric\provision_fabric.py `
  --environment staging `
  --solution `
  --verify-semantic-model `
  --verify-report `
  --no-cloud `
  --evidence-output .local\fabric-provision-staging-evidence.json
```

This intentionally exits non-zero with `Unverified`. The integration phase
`fabric-provision-staging` uses that no-cloud mode so local verification cannot
deploy accidentally; the resulting Unverified status remains blocking.

## Controlled Demo 4 behavior

The Fabric notebook embeds the exact application evaluator at generation time
because Fabric cannot import the application package. Source data comes from one
mirror snapshot. Incomplete or conflicting snapshots never publish a successful
Before/After measurement.

Expected display behavior:

| Source data | Policy context | Display state |
|---|---|---|
| Marvel all-premium | active or reverted | Not Applied · Before |
| Analytics all-premium | active | Policy Active · Awaiting Traffic · Before |
| Complete Analytics burst | active | Applied · After |
| Complete Analytics burst | reverted | Policy Reverted · After Traffic Captured |

No measurement is represented as missing. A valid measured result of zero is
represented as measured `$0.00`; the two states are not interchangeable.

Prepare staging data off-stage. Do not reset, apply/revert, generate traffic, or
run a mutating refresh during a presentation unless that exact operation was
separately rehearsed.

`azd up` may create or idempotently ensure initial seed data, but it never invokes controlled
reset, generates the controlled burst, or silently restages an existing demonstration. Portal Live
mode performs those operations explicitly and serially. Prepared Fabric / Power BI mode performs
no mutation on stage.
