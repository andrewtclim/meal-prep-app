# Roadmap

> The plan, not a contract. Update it at the weekly meeting and when tasks finish.
>
> **Rules:**
> - Only weeks in **Now** and **Next** are planned in detail. Later weeks stay rough.
> - Every task is tagged `[must]`, `[should]`, or `[stretch]`. When we fall behind, cut stretch first, then should.
> - Every task has an owner. No critical piece is understood by only one person: every PR gets a review.
> - When the plan changes, add a line to **Replans** at the bottom.

**Milestones:** week 4 data layer done, week 6 ML done, week 9 agent done, week 12 shipped.

---

## Now: Week 1, Setup

| Task | Tag | Owner | Status |
|---|---|---|---|
| Create repo with `docs/` and `CLAUDE.md`, connect Claude Project | must | | |
| Decide cloud provider (DECISIONS #10) | must | | done |
| GitHub Actions: lint + pytest on every PR | must | | |
| Dockerized FastAPI hello endpoint | must | | |
| CD: merge to main auto-deploys the endpoint | must | | |
| Create Supabase and Neo4j free tier projects (dev only) | must | | |
| Set billing alerts, check free tier limits for Supabase and Neo4j | must | | |
| Pick recipe dataset (DECISIONS #8) | must | | |

**Done when:** a merge to main deploys a live endpoint.

## Next: Week 2, Data foundation

| Task | Tag | Owner | Status |
|---|---|---|---|
| First Postgres migrations: users, pantry, recipes, ingredients, recipe_ingredients | must | | |
| Create `raw` schema, load recipe dataset into it untouched | must | | |
| Set up dbt: raw to clean recipe and ingredient models, basic data tests in CI | must | | |
| `pipeline_runs` log table | should | | |
| Ingredient name normalization v1 | must | | |
| Draft DATA_MODEL.md cross-store details | should | | |

**Done when:** we can query "all recipes using napa cabbage" in SQL.

---

## Later (rough)

| Week | Phase | Goal | Tags |
|---|---|---|---|
| 3 | Data | Neo4j graph build, seed `SUBSTITUTES_FOR`, prep task extraction, recipe embeddings in pgvector | must (prep extraction may spill into week 4) |
| 4 | Data | USDA nutrient load, FDA recalls pipeline (scheduled, incremental), Terraform resources for infra (scaffold done in week 1) | must: USDA. should: recalls. should: Terraform (can slip to week 10) |
| 5 | ML | Ingredient embeddings, ~100 hand-labeled substitution pairs, baseline comparison | must |
| 6 | ML | Write scores to Neo4j edges, expiry prioritization incl. prepped foods | must |
| 7 | Agent | LangGraph skeleton: intake, pantry check, retrieval, gap analysis | must |
| 8 | Agent | Substitute vs buy, store matching, prep consolidation, daily schedule | must |
| 9 | Agent | Review loop with interrupt + checkpointer, tracing | must |
| 10 | Product | Streamlit frontend | must: basic flow. stretch: polish |
| 11 | Eval | ~20 agent scenarios, retrieval eval, cost and latency check | must |
| 12 | Ship | README, architecture diagram, demo video, buffer | must |

**Stretch (only if ahead):** receipt scanning, MCP servers for retrieval, nutrition-aware suggestions, future-phase pipelines from PROJECT.md.

---

## Replans

_One line per change: date, what changed, why. Link a DECISIONS entry if one was made._

- 2026-10-02: Prep task extraction added to week 3 (DECISIONS #6).
- 2026-10-02: ELT with dbt added to week 2, FDA recalls pipeline added to week 4 (DECISIONS #14 to #16).
- 2026-10-07: Chose GCP as cloud provider (DECISIONS #10); Terraform scaffold landed under `infra/`.
