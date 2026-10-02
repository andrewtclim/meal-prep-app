# Decisions

> Why we chose what we chose. Newest entries at the bottom.
>
> **Rules:**
> - Never edit or delete an accepted entry. To change a decision, add a new one and mark the old one `Superseded by #N`.
> - Statuses: `Proposed` (needs group sign-off at the next meeting), `Accepted`, `Superseded by #N`, `Open` (question we haven't answered yet).
> - Keep each entry short: the decision, why, and what it affects.

---

### 1. Repo docs are the source of truth
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** `docs/` holds four files: PROJECT.md (what and why), DECISIONS.md (this file), ROADMAP.md (plan and status), DATA_MODEL.md (which data lives where). The Claude Project syncs these from GitHub. If chat and docs disagree, docs win.
- **Why:** Chats drift and go stale. One reviewed source keeps teammates and Claude on the same info.
- **Impact:** Doc changes go in the same PR as the code that caused them. Claude Code proposes doc edits, people approve them.

### 2. Migrations are the schema source of truth
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Exact tables and columns live in migration files (Postgres) and the Cypher setup file (Neo4j). DATA_MODEL.md stays conceptual. Replaces the earlier idea of a column-by-column SCHEMA.md.
- **Why:** A hand-written copy of the schema drifts from the real one.
- **Impact:** DATA_MODEL.md only changes when we add an entity or a store, not on every migration.

### 3. LangGraph for orchestration, LangChain for components
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** The agent is a LangGraph `StateGraph`. LangChain integrations (models, retrievers, Neo4j, pgvector, tools) are used inside nodes. Deterministic steps are plain Python, not LLM calls.
- **Why:** The flow has real state, loops (user pushback), and branching (substitute vs buy). Plain Python nodes are cheaper, testable in CI, and easier to explain.
- **Impact:** CI tests target the deterministic nodes.

### 4. Two databases: Postgres (Supabase) and Neo4j
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Postgres on Supabase (with pgvector) is the system of record. Neo4j holds relationships (substitutions, recipe ingredients, prep tasks) and is rebuilt from Postgres by an ingestion job.
- **Why:** Substitution and prep-consolidation queries are graph-shaped. Everything else is relational or vector search.
- **Impact:** Write plain SQL with standard Postgres libraries and avoid Supabase-only features where practical, so switching Postgres hosts is mostly a connection string change.

### 5. Spoonacular is query-time only
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Call Spoonacular live for search and substitution lookups. Never store its responses in Postgres or Neo4j.
- **Why:** Their terms cap caching at 1 hour.
- **Impact:** The persistent recipe store comes from an open dataset (see #8).

### 6. Core feature is start-of-week component prep
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Core build is: pick ~3 recipes, gap analysis, substitutions, grocery task, consolidated prep task, and a shelf-life-aware daily schedule.
- **Why:** Prep consolidation is what makes this different from other meal planners, and it answers the "reheated food tastes stale" pain point.
- **Impact:** Recipe ingestion needs a prep task extraction step (moved into week 3).

### 7. Prices, routing, and recalls are future phases
- **Date:** 2026-10-02
- **Status:** Accepted, recalls part superseded by #16
- **Decision:** Grocery prices, transit routing, and FDA recall alerts are not in the core build. Real-time store inventory is out of scope entirely.
- **Why:** No public API has per-store Bay Area prices or inventory, and these would stretch scope too thin.
- **Impact:** Grocery task lists name stores that *likely* carry an item, not confirmed stock or prices.

### 8. Persistent recipe dataset
- **Date:** 2026-10-02
- **Status:** Open
- **Question:** Which open recipe dataset do we batch load? Candidates: Food.com (Kaggle), TheMealDB, others.
- **Decide by:** End of week 1. Check license, size, and how clean the ingredient lists and instructions are.

### 9. Store data from Google Places
- **Date:** 2026-10-02
- **Status:** Proposed
- **Decision:** Look up stores at query time and only persist Google place IDs. In Neo4j, model store *categories* (e.g. Asian grocery) linked to ingredients they likely carry, rather than individual stores.
- **Why:** Google's terms restrict caching most Places content. Categories also generalize to any user's location.
- **Impact:** Verify the current Places caching terms before building.

### 10. Cloud provider
- **Date:** 2026-10-02
- **Status:** Open
- **Question:** GCP (Cloud Run, Artifact Registry) or AWS (Lambda/App Runner, ECR)?
- **Decide by:** Week 1, before setting up CI/CD.

### 11. Substitution edge direction
- **Date:** 2026-10-02
- **Status:** Open
- **Question:** Are `SUBSTITUTES_FOR` edges symmetric, or directional with separate weights each way (onion for shallot may score differently than shallot for onion)?
- **Decide by:** Before week 3 graph build.

### 12. Tracing tool
- **Date:** 2026-10-02
- **Status:** Open
- **Question:** LangSmith or Langfuse?
- **Decide by:** Week 7, before agent work starts.

### 13. App name
- **Date:** 2026-10-02
- **Status:** Open
- **Question:** Name is TBD. Keep the name out of package and module names so renaming is cheap.

### 14. ELT with a raw schema
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Every source lands untouched in a `raw` schema in Postgres. Transforms produce the clean tables the app uses. Pipelines are idempotent, use watermarks for incremental loads, and log each run.
- **Why:** Ingredient normalization will keep improving. With raw data kept, we rerun transforms instead of re-pulling sources, and can tell whether a bad row came from the source or from us.
- **Impact:** Spoonacular is still never stored, not even in `raw` (#5). Google Places follows #9.

### 15. dbt for SQL transforms
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Use dbt on Postgres for raw to clean transforms and data quality tests. Python handles steps SQL can't (LLM prep extraction, embeddings).
- **Why:** Testable, versioned SQL transforms with lineage, and a common tool in DS and analytics roles.
- **Impact:** dbt tests run in CI. Set up in week 2.

### 16. FDA recalls pipeline promoted to core
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Build a scheduled, incremental openFDA recalls pipeline as part of the core build, tagged `should`. Partly supersedes #7. Prices and routing stay future phases.
- **Why:** Gives the project one real scheduled pipeline (watermarks, incremental loads, scheduling) and it's useful: it can flag recalled ingredients in a pantry or plan.
- **Impact:** Week 4 in ROADMAP. If we fall behind, it's cut before any `must` work.

### 17. Pipeline scheduling
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** Start with Cloud Scheduler + Cloud Run Jobs (or the AWS equivalent, per #10). Prefect or Dagster only as a stretch goal.
- **Why:** We only have one scheduled pipeline. A full orchestrator is overhead we don't need yet.
