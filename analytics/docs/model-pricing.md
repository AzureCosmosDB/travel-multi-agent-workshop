# AI models and pricing

The optimization analytics (Modules 07–09, the Optimization Console, the Fabric
notebook, and the Power BI report) put a **dollar cost** on agent turns. That cost
needs a price per model. This page explains which models the workshop deploys, where
their prices come from, and what to do when you change a model.

## Models deployed by default

`azd up` deploys these Azure OpenAI model deployments (see
`infra/main.bicep` → `deployments`):

| Deployment | Model | Role in the app |
|---|---|---|
| `gpt-5.1` | `gpt-5.1` | Default / complex-tier chat model |
| `gpt-5-mini` | `gpt-5-mini` | Routine-tier chat model (capability-tiered selection) |
| `gpt-5-nano` | `gpt-5-nano` | Trivial-tier chat model (greetings, acks) |
| *(embedding)* | `text-embedding-3-small` | Vector embeddings (not priced for turn cost) |

The **deployed models are the source of truth for *which* models exist.** At deploy
time, `python/data/seed_configuration.py` (run by the `azd` post-provision hook)
lists the deployments that were actually created and writes one priced row per model
into the Cosmos **`Configuration`** container (`type = "model_pricing"`). The app,
the notebook, and the report all read those rows — one runtime source, no CSVs and no
hardcoded pricing in DAX.

Because seeding is an **upsert**, swapping a model later (edit `infra/main.bicep`,
re-run `azd up`) adds the new model's priced row while older models' rows remain — so
the report can show cost **before and after** a model swap until the old turn data
ages out.

## Where prices come from

Prices are **list-price estimates** and can't be fetched programmatically, so they
live in one committed reference file:

```
python/data/model_pricing.json      # USD per 1M tokens: { "<model>": {"input": x, "output": y} }
```

Example:

```json
{
  "gpt-5.1":     { "input": 1.25, "output": 10.00 },
  "gpt-5-mini":  { "input": 0.25, "output": 2.00 },
  "gpt-5-nano":  { "input": 0.05, "output": 0.40 }
}
```

This file is read **only at deploy time** by `seed_configuration.py`, which looks up
each deployed model's price and upserts it into `Configuration`. It is not read on the
hot path.

## When you change a model

If you swap in a new model (or add one) in `infra/main.bicep`:

1. **Add its price** to `python/data/model_pricing.json` using the model's deployment
   name as the key and USD **per 1M tokens** for `input` and `output`.
2. Re-run `azd up` (or, against a live account, `cd python && python data/seed_configuration.py`).

If a deployed model has **no entry** in the reference file, `seed_configuration.py`
still seeds it — at a default rate — and prints a warning so you know to add the real
price. The report will show that model priced at the default until you do.

## How to find the price

- **Azure OpenAI pricing page** — the authoritative list price per model:
  <https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/>
- **Azure Pricing Calculator** — model your expected token volume:
  <https://azure.microsoft.com/pricing/calculator/>

Prices are quoted **per 1M tokens**, split into **input** and **output** rates — copy
those two numbers into `model_pricing.json`. Reasoning models bill reasoning tokens as
output, so the projected saving in a recommendation card is an estimate; the measured
before/after (the *verify* step) is the authoritative number.
