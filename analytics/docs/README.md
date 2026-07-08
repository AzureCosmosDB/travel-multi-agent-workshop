# Analytics Initiative — Knowledge Base

This directory is the persisted knowledge base for the **Agent Analytics and Optimization** work in this repository. It is written for **two audiences**: humans contributing to the project, and AI agents that need to understand what was built and why so they can make intelligent suggestions and fixes.

## Contents

| Path | Purpose |
|------|---------|
| `vision/agent-analytics-and-optimization-vision.md` | The north-star product vision (verbatim reference artifact). |
| `charter.md` | The concrete scope, maturity target, and first principles governing this effort. Start here. |
| `adr/` | Architecture Decision Records — every architectural decision, with the evidence behind it. |
| `adr/README.md` | Index of all ADRs and the decision process. |
| `adr/adr-template.md` | Template for new ADRs. |

## Working principles (summary — see `charter.md` for the authoritative statement)

1. **Everything is grounded in data.** No assertion — by a human or an agent — ships into code, docs, or decisions unless it has been tested and observed to be true. "Should work" is not "works."
2. **Every architectural decision becomes an ADR.** Decisions are recorded with context, options, evidence, and consequences, and kept up to date.
3. **Deep docs are a first-class deliverable.** Implementation detail is documented for both humans and agents, and kept current as the code evolves.

## For agents reading this repo

If you are an AI agent exploring this solution:
- Read `charter.md` first for scope and constraints, then the ADR log in `adr/README.md` for the decisions and their rationale.
- Treat ADRs marked **Accepted** as binding constraints unless a newer ADR supersedes them.
- When you make or propose an architectural change, add or update an ADR and cite the evidence (files, commands run, observed output). Do not assert feasibility you have not verified.
