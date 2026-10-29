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
- **Status:** Superseded by #18
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
- **Status:** Superseded by #20
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
- **Status:** Open, proposed answer in #23
- **Question:** Which open recipe dataset do we batch load? Candidates: Food.com (Kaggle), TheMealDB, others.
- **Decide by:** End of week 1. Check license, size, and how clean the ingredient lists and instructions are.
- **Update (2026-10-09):** Food.com (Kaggle) is the first candidate we're investigating. The dataset pages we checked list no license, and the data was scraped from Food.com for a research paper, so confirm the license before loading it. Fallbacks: TheMealDB (terms allow copying API content; free key covers development and education) and RecipeNLG (non-commercial research and education only). See #20.
- **Update (2026-10-12):** Audited the two Food.com Kaggle datasets: the [2019 one](https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions) (232k recipes) and the [more recent 2020 one](https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews) (523k recipes). Both are scrapes of the same site, and the 2020 one contains nearly all of the 2019 one's recipes. Both have names, ingredients, steps, times, and tags, but **neither has ingredient units**. The 2019 one has no quantities at all. The 2020 one has bare numbers with no units, and in 78% of rows they can't be matched to ingredients. Licensing is unresolved: the Kaggle labels (`copyright-authors` vs `CC0`) are the uploaders' claims, and Food.com's own terms are unread. Options, in order:
  1. Read Food.com's terms, or ask them for permission.
  2. Audit TheMealDB and RecipeNLG for units and license.
  3. If we proceed with the 2020 dataset, plan at the ingredient level without amounts (no grocery totals) and load only a weeknight-dinner subset (~69k recipes, to fit the 500 MB tier).

### 9. Store data from Google Places
- **Date:** 2026-10-02
- **Status:** Proposed
- **Decision:** Look up stores at query time and only persist Google place IDs. In Neo4j, model store *categories* (e.g. Asian grocery) linked to ingredients they likely carry, rather than individual stores.
- **Why:** Google's terms restrict caching most Places content. Categories also generalize to any user's location.
- **Impact:** Verify the current Places caching terms before building.

### 10. Cloud provider
- **Date:** 2026-10-02
- **Status:** Accepted
- **Decision:** GCP: Cloud Run for the API, Artifact Registry for images, Cloud Scheduler + Cloud Run Jobs for scheduled pipelines (DECISIONS #17). Infra managed with Terraform; state in a GCS bucket.
- **Why:** Cloud Run runs our FastAPI Docker image as-is and scales to zero when idle, so a low-traffic demo costs close to nothing. Cloud Run Jobs runs scheduled pipelines from the same image (#17). The AWS option needs more glue: Lambda needs an adapter to serve FastAPI. One cloud keeps IAM, registry, and deploy in one place.
- **Impact:** CI/CD targets Cloud Run. Week 1 CD and later pipeline scheduling follow GCP services. Terraform lives under `infra/`.

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

### 18. Repo docs are the source of truth, now five files
- **Date:** 2026-10-07
- **Status:** Accepted
- **Decision:** Same as #1, with `docs/CONCEPTS.md` added as a fifth file. `docs/` holds PROJECT.md (what and why), DECISIONS.md (this file), ROADMAP.md (plan and status), DATA_MODEL.md (which data lives where), and CONCEPTS.md (running glossary of the concepts, tools, and patterns the code uses). If chat and docs disagree, docs win.
- **Why:** CONCEPTS.md was added with CLAUDE.md (PR #1) but #1 still listed four files, so the source-of-truth set and the repo disagreed.
- **Impact:** CLAUDE.md lists CONCEPTS.md in the docs to read at the start of every session. A new concept in code gets its CONCEPTS.md entry in the same PR, like any other doc change.

### 19. Weekly review posts
- **Date:** 2026-10-08
- **Status:** Accepted
- **Decision:** Each week (Wednesday to Wednesday) gets a blog-style post in `review_sessions/` covering the sessions, key code with reasoning, diagrams, and PRs. Format is set in CLAUDE.md.
- **Why:** Learning is a core goal. A readable narrative of each week makes it easier to explain the stack later and doubles as portfolio writing.
- **Impact:** Every PR updates that week's post. `review_sessions/` is not one of the source-of-truth files in #18; docs win if they disagree.

### 20. Drop Spoonacular from the core build
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** The app doesn't depend on Spoonacular. All recipes and ingredients come from data we're allowed to store: an open recipe dataset (#8), user-saved recipes, and USDA FoodData Central. Substitutions come only from our own model. Supersedes #5.
- **Why:** Spoonacular's terms only let us keep the recipe id, title, and image URL. Everything else, ingredients included, may be cached for at most 1 hour and only with their written permission, and the ban covers "derived, hashed, or transformed data". So we couldn't store its ingredients, map them to USDA, or train on them. Using it live would mean re-fetching every recipe on each plan build (the free plan is 50 points a day and needs a backlink), and all data must be deleted if we stop using the API. Sources: spoonacular.com/food-api/terms and spoonacular.com/food-api/pricing, checked 2026-10-09.
- **Impact:** The open dataset is the only recipe source for search and planning, so picking it (#8) blocks week 2. Spoonacular could come back later as an optional live search that stores only recipe ids, under a new decision.

### 21. Keyless CI auth to GCP (Workload Identity Federation)
- **Date:** 2026-10-14
- **Status:** Accepted
- **Decision:** GitHub Actions authenticates to GCP with Workload Identity Federation and impersonates the `github-deploy` service account. We do not store a service-account JSON key in GitHub Secrets. The WIF provider only accepts tokens from `andrewtclim/meal-prep-app` on `refs/heads/main`.
- **Why:** Long-lived keys are easy to leak and slow to rotate. WIF issues short-lived credentials scoped to our repo and branch. Restricting to `main` means feature-branch or PR workflows cannot push images; we can split push vs deploy accounts later if needed.
- **Impact:** `infra/github_wif.tf` and `infra/outputs.tf`. A later CD workflow will use the WIF provider name and SA email from Terraform outputs. PR workflows cannot use this provider until we add a separate path.

### 22. uv for Python dependencies and environments
- **Date:** 2026-10-17
- **Status:** Accepted
- **Decision:** Dependencies live in `pyproject.toml` (ranges, with a `dev` group) and are locked in `uv.lock`. Local dev uses uv (`uv sync`, `uv add`, `uv run`) and the Docker image installs with `uv sync --locked --no-dev`. Replaces the conda env plus `requirements.txt` plan in PR #7 (its proposed #21 is not used), and replaces main's pinned `requirements.txt` and `requirements-dev.txt`.
- **Why:** Conda plus pip left two copies of the package list to keep in sync and had no lockfile, so sub-dependencies could still change between builds. Main's exact pins covered only the packages we named. One `pyproject.toml` plus a lockfile gives the same versions on a laptop, in CI, and in Docker, with one spec to edit. uv is also much faster than pip.
- **Impact:** `Dockerfile` copies uv in and installs from the lock. New dependencies go in with `uv add`, and `pyproject.toml` and `uv.lock` are committed together. PR #7 is closed. Packages for the rest of the stack are added as each piece is built, with their decisions.

### 23. Food.com 2020 as the recipe dataset, with LLM-inferred units
- **Date:** 2026-10-25
- **Status:** Proposed
- **Decision:** Use the Food.com 2020 dataset (Kaggle `irkaal/foodcom-recipes-and-reviews`, `recipes.parquet`) as the persistent recipe store. Answers #8. The team accepts the licensing position for this project: the Kaggle labels are the uploaders' claims and Food.com's own terms were not reviewed. Revisit before any public or commercial release. The dataset has no ingredient units, so an LLM infers a quantity and unit for each ingredient from the recipe text.
- **Why:** It is the largest candidate (523k recipes) with names, ingredients, steps, times, and categories (audit in #8). Its ingredient quantities line up with the ingredient list in only about 22% of recipes, and units are absent everywhere, so the text-reading step is needed either way. Alternatives (TheMealDB, RecipeNLG) were not audited for units or size.
- **Impact:** `pipelines/foodcom/`. Inferred units carry model error, so we measure accuracy on a hand-checked sample before the full run. If the license position changes, the recipe store must be replaced.

### 24. Food.com load pipeline design
- **Date:** 2026-10-25
- **Status:** Proposed
- **Decision:** Recipes reach Postgres in stages: Python cleans the file (`clean.py`), an LLM adds units and cuisines (`augment.py`), the result loads into `raw.foodcom_prepared`, dbt builds staging models, and an upsert writes into the Alembic-owned `public` tables (#2). Amends #14: the untouched Food.com file is not stored in Postgres. It stays local at `data/raw/recipes.parquet`, re-downloadable from Kaggle and pinned by dataset version and SHA-256.
- **Why:** Python handles text cleanup and LLM calls, and dbt handles SQL transforms and tests (#15). The full cleaned set is about 635 MB of data by our estimate, so a second untouched copy would not fit the free tier. LLM output is paid for, so it is written to a local file that a rerun resumes from.
- **Impact:** `pipelines/foodcom/` and `dbt/`. `raw` holds prepared Food.com data, not the source file, so the "land untouched in `raw`" rule in #14 no longer holds for this source. The paid `augment_results.jsonl` must be backed up somewhere other than a laptop.

### 25. Food.com subset: 212,846 recipes
- **Date:** 2026-10-25
- **Status:** Proposed
- **Decision:** Load recipes with a total time of 90 minutes or less and 3 to 20 ingredients, excluding categories that are clearly not dinner (desserts, breads, drinks, breakfast, sauces, spreads, non-food), after removing empty recipes and duplicate names. This leaves 212,846 of 428,419 cleaned recipes. A rating is not required. The filters are named constants in `pipelines/foodcom/clean.py`.
- **Why:** The app plans weeknight dinners, and the LLM step is paid per recipe, so we cut before paying. An include list of dinner categories missed vegetarian and cuisine-filed dinners, so we exclude the clearly-not-dinner groups instead. Half of all recipes are unrated, so a rating filter would drop many valid recipes. The 90-minute cutoff is a judgment call from the weeknight-dinner idea, not derived from the data. With the other filters fixed, the subset is 180,740 recipes at 60 minutes, 212,846 at 90, 222,269 at 120, and 232,064 at 180, so the count flattens above 90. Total time includes passive time such as marinating.
- **Impact:** Our estimate is about 310 MB of data per copy. With a `raw` copy, indexes, and embeddings, this exceeds the 500 MB free tier, so we need a larger Supabase plan (a paid service, to be agreed before stage 3) or a single stored copy. Open until measured on a 1,000-recipe sample in stage 3.
