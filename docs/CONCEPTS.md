# Concepts

> Running glossary of the concepts, tools, and patterns this repo uses. Claude adds an entry the first time a concept shows up in code, in the same PR. One entry per concept, newest at the bottom.

## Entry template

### Concept name
- **What it is:** 2 to 4 sentences.
- **Where we use it:** file paths.
- **Why this over the alternative:** one or two sentences naming the alternative.
- **Common question:** what someone would ask about it, and the short answer (optional).

---

### Terraform
- **What it is:** Infra as code: you declare cloud resources in `.tf` files, run `plan` to preview changes, and `apply` to make GCP match. Terraform stores what it manages in a state file so reruns update resources instead of duplicating them.
- **Where we use it:** `infra/` (provider, variables, GCS remote state backend, APIs, Artifact Registry, GitHub WIF). Bootstrap narrative for this week is in the [Week 1 setup review post](../review_sessions/blog_post_10.07_10.14_week1_setup.md); day-to-day commands are in [`infra/README.md`](../infra/README.md).
- **Why this over the alternative:** Clicking in the GCP console is faster once, but it is not reviewable in a PR and drifts between teammates. Terraform keeps one shared definition.
- **Common question:** Where does state live? In the GCS bucket configured in `infra/providers.tf`, not in git.

### Artifact Registry
- **What it is:** GCP’s private registry for container images (and other packages). A “repository” here is a named shelf for images, not a GitHub source repo.
- **Where we use it:** `infra/artifact_registry.tf` — Docker repository id `api` in `var.region`.
- **Why this over the alternative:** Docker Hub works, but it’s another account and weaker IAM fit with Cloud Run. Same-cloud registry keeps push/pull permissions in one place.
- **Common question:** What is the image URL shape? `{region}-docker.pkg.dev/{project}/api/{image}:{tag}`.

### Workload Identity Federation
- **What it is:** A way for an external identity (GitHub Actions) to get short-lived GCP credentials without storing a service-account JSON key. GitHub presents an OIDC token; GCP checks the issuer and claims (e.g. repository name), then lets a service account be impersonated for that job.
- **Where we use it:** `infra/github_wif.tf` — pool + GitHub provider, `github-deploy` service account, Artifact Registry writer binding. Outputs in `infra/outputs.tf` for a later Actions workflow.
- **Why this over the alternative:** A downloaded key in GitHub Secrets is simpler to set up once, but it is long-lived and painful if leaked. WIF is the usual industry pattern for keyless CI→cloud auth.
- **Common question:** How do you avoid storing cloud credentials in GitHub? Federate CI identity to a cloud role; mint short-lived tokens per run.

### Data profiling
- **What it is:** Checking a dataset against what the app needs before building on it: which fields exist, how much is missing or malformed, how many duplicates, and how big it is. The output is a short report, not a pipeline.
- **Where we use it:** a local audit script, not in the repo, for the Food.com datasets (DECISIONS #8). Its findings are summarized there.
- **Why this over the alternative:** Loading the data first and finding gaps later costs a schema and a pipeline built on the wrong source. Profiling found that neither dataset has ingredient units before we wrote any migration.
- **Common question:** How did you know the data was fit for purpose before building on it? You list the fields the app needs, then measure each one's coverage and quality, and include checks that can surprise you (e.g. whether two parallel arrays line up).

### FastAPI and routers
- **What it is:** A Python web framework. A decorator like `@router.get("/health")` binds an HTTP method and URL path to a function, and FastAPI turns the function's return value into JSON. Endpoints are grouped into `APIRouter` files, and `main.py` plugs them into the app with `include_router`, so `main.py` only wires things together.
- **Where we use it:** `app/main.py` (creates the app), `app/routes/health.py` (`GET /health`).
- **Why this over the alternative:** Flask is older and has no built-in validation from type hints. FastAPI also generates interactive docs at `/docs`.
- **Common question:** REST vs FastAPI? REST is a style of designing URLs and methods; FastAPI is a library for building an API in that style.

### Docker image, container, and layers
- **What it is:** A Dockerfile is the recipe, an image is the built read-only result, and a container is a running copy of an image. Each Dockerfile line adds a cached layer, and a rebuild reuses layers above the first changed line. `RUN` executes at build time, `CMD` is recorded at build time and executed at `docker run`.
- **Where we use it:** `Dockerfile`. Dependencies are installed before `COPY app/` so code edits reuse the cached install layer.
- **Why this over the alternative:** Running the app straight on a machine means "works on my laptop" can break on Cloud Run (DECISIONS #10). The same image runs identically in both places.
- **Common question:** Why `--host 0.0.0.0` in a container? `127.0.0.1` inside a container is the container's own loopback, so nothing outside could reach the server.

### In-process API testing (TestClient)
- **What it is:** FastAPI's `TestClient` sends a fake request straight into the app object, with no server, port, or Docker. The test checks the status code and body.
- **Where we use it:** `tests/test_health.py`, run with `python -m pytest`.
- **Why this over the alternative:** Starting a real server and calling it with `curl` is slower and needs a free port. The tradeoff is that it proves the code works, not that the container is wired correctly (port mapping, host binding).

### Dependency pinning
- **What it is:** Fixing which version of a library gets installed so every build is the same. An exact pin (`fastapi==0.143.0`) fixes only the packages we name, not their sub-dependencies. A lockfile fixes all of them (see Lockfile below).
- **Where we use it:** `pyproject.toml` holds ranges (`fastapi>=0.143,<1`) and `uv.lock` holds the exact versions.
- **Why this over the alternative:** Unpinned `fastapi` installs whatever is newest on build day, so a build next month can break with no code change. Exact pins in a requirements file were our first version, but they left sub-dependencies free to move.

### uv
- **What it is:** One tool that replaces conda (installing Python), pip (installing packages), and venv (making environments), and adds a lockfile. `uv sync` builds `.venv` from the lock, `uv add` adds a package, and `uv run` runs a command in the project environment with no activate step. `uv add --dev` puts a package in the `dev` group in `pyproject.toml` (tools for working on the repo, such as pytest and Ruff) and updates `uv.lock` with that package and its dependencies. The Docker image runs `uv sync --locked --no-dev`, which installs only the main dependency list, so those dev tools are not in the image. CI omits `--no-dev` so the linter and tests are installed there.
- **Where we use it:** `pyproject.toml`, `uv.lock`, and `.venv/` at the repo root, and the `Dockerfile`, which copies the `uv` program in and runs `uv sync --locked --no-dev`.
- **Why this over the alternative:** Conda plus a pip requirements file needs two files kept in sync and has no lockfile. uv keeps the spec in one file and makes the lock automatic. The tradeoff is that uv is newer, so there are fewer tutorials.
- **Common question:** What is the difference between `pyproject.toml` and `uv.lock`? The first says what we want, the second records exactly what we got, and we commit both. How does Docker know to skip dev tools? It does not read your mind: the Dockerfile passes `--no-dev` to `uv sync`.

### Lockfile
- **What it is:** A generated file that records the exact version of every installed package, sub-dependencies included, plus a hash of each download. An install that doesn't match the hash fails, which guards against a tampered package (a supply-chain attack).
- **Where we use it:** `uv.lock`. It is written by uv and never edited by hand. Docker uses it through `uv sync --locked`, which fails the build if the lock and `pyproject.toml` disagree. (`--frozen` looks similar but skips that check and silently installs from a stale lock.)
- **Why this over the alternative:** A requirements file with ranges can resolve to different versions on different days. A lockfile makes the laptop, CI, and Docker install the same set. Upgrades become a deliberate step (`uv lock --upgrade-package <name>`).
- **Common question:** Why commit a lockfile? So every environment is rebuilt from the same versions, and a version change shows up as a reviewable diff.

### Docker build context and .dockerignore
- **What it is:** The build context is the folder Docker can `COPY` from when you run `docker build .`. `.dockerignore` lists paths that are never visible to the build, the same way `.gitignore` works for git. It keeps secrets (`.env`), the git history, and large local folders out of the image and out of cache checks.
- **Where we use it:** `.dockerignore` at the repo root. It hides docs, tests, infra, and local-only folders (e.g. a 1.1 GB audit folder) from the build.
- **Why this over the alternative:** Without it, a future `COPY . .` would pull `.env` and the whole repo into the image. Today it changes nothing measurable: BuildKit (Docker's current builder) only uploads files a `COPY` actually asks for, and our context was ~800 bytes with and without the file. So this is insurance, not a speedup. We exclude `tests/`; remove that line if CI ever runs pytest inside the container.
- **Common question:** What is the difference between `.gitignore` and `.dockerignore`? Different tools, separate files: git decides what is versioned, Docker decides what the build can see. They overlap but neither reads the other.

### GitHub Actions CI
- **What it is:** A YAML file GitHub reads to run commands on its own machines. `on` is when the run starts (here, every pull request and every push to `main`). A job is one machine (`ubuntu-latest`). Steps run in order on that machine: download the repo, install uv and Python 3.12, `uv sync --locked --dev`, then Ruff and pytest. The job fails if any step exits with an error. This workflow does not deploy and does not use GCP.
- **Where we use it:** `.github/workflows/ci.yml`.
- **Why this over the alternative:** Running lint and tests only on a laptop means a broken branch can still be merged. CI runs the same two commands on a clean machine for every PR. CD (build the image and deploy on merge to `main`) is a later workflow and needs Workload Identity Federation.
- **Common question:** Why does CI pass `--dev` when Docker passes `--no-dev`? CI has to install Ruff and pytest. The running API image does not.
### Database migration (Alembic)
- **What it is:** A versioned script that changes the database shape (create a table, add a column). Alembic runs the scripts in order against Postgres and records which ones already ran in an `alembic_version` table, so the same change is not applied twice. `upgrade` applies the change; `downgrade` undoes it.
- **Where we use it:** `alembic/`, `alembic.ini`, and `alembic/versions/`. `alembic/env.py` reads `DATABASE_URL` from `.env` so the password is not committed. `2beee51a1f35` creates `users`, `units`, `ingredients`, `recipes`, `recipe_ingredient`, and `user_pantry`. `fe3310413886` adds cuisines, allergens, the junction tables, ratings, and `user_events`. Once a revision has been applied, later changes are new files that point at it with `down_revision`.
- **Why this over the alternative:** Clicking tables together in the Supabase UI is faster once, but Andrew's database would not match and the shape would not be in git. DECISIONS #2 says migration files are the schema source of truth. Plain `.sql` files work too; Alembic adds the "already applied" bookkeeping.
- **Common question:** What is the difference between a migration and loading data? A migration builds the shelves. Inserts and dataset loads put rows on them.

### Junction table
- **What it is:** A table whose rows are pairs of ids from two other tables. It is how a relational database stores a many-to-many link: one user can prefer many cuisines, and one cuisine can be preferred by many users. The primary key is both ids together, so the same pair cannot be stored twice.
- **Where we use it:** `user_cuisine`, `user_allergen`, `ingredient_allergen`, and `user_recipe` in `alembic/versions/fe3310413886_create_preference_and_event_tables.py`.
- **Why this over the alternative:** A single `cuisine_id` column on `users` can store only one cuisine per person. A list stuffed into one text column is hard to query and easy to misspell.
- **Common question:** Why not just add a column? A column holds one value. A junction table holds as many links as you need.

### Parquet
- **What it is:** A compressed, typed file format that stores data by column. It keeps real types (integers, nulls, and lists of strings) instead of turning everything into text.
- **Where we use it:** `data/raw/recipes.parquet`, and the stage outputs in `data/interim/` written by `pipelines/foodcom/clean.py`.
- **Why this over the alternative:** CSV would flatten our ingredient and instruction lists into single strings that we would have to re-parse on every read, and a comma inside an ingredient name would break it. Parquet is also smaller and faster to read. The tradeoff is that you cannot open it in a text editor.
- **Common question:** Why not CSV? Parquet keeps types and nested columns, so a file can be read back exactly as it was written.

### Deterministic vs idempotent pipelines
- **What it is:** Deterministic means the same data always produces the same output, even if the rows arrive in a different order. Idempotent means running the job again leaves the system in the same state as running it once (no duplicate rows). They are separate properties.
- **Where we use it:** `pipelines/foodcom/clean.py` breaks dedupe ties by lowest `source_ref` so reruns pick the same row, and overwrites its output file. Stage 3 will use upserts (`INSERT ... ON CONFLICT`) for the database load.
- **Why this over the alternative:** An append-only load duplicates every row on a retry. Without a final tiebreaker, a rerun could keep a different recipe and break the ids that paid LLM results are keyed on.
- **Common question:** How do you make a data pipeline safe to rerun? Deterministic transforms, plus writes that overwrite or upsert on a natural key.

### Deduplication by normalized key
- **What it is:** Removing duplicate records by comparing a cleaned version of a field, not the raw value. We lowercase recipe names, drop punctuation, collapse whitespace, and singularize the last word, so "Lemonade", "lemonade!" and "Lemonades" match. One record per key is kept by a fixed rule.
- **Where we use it:** `normalize_name` and `dedupe_by_name` in `pipelines/foodcom/clean.py`.
- **Why this over the alternative:** Exact-string matching misses almost every duplicate because of case and punctuation. The tradeoff is that different recipes can share a name (187 "Banana Bread" entries), and we keep only the best-rated one.
- **Common question:** How do you handle duplicates in messy data? Normalize to a key, group, and keep one row by a deterministic rule.

### Dependency groups
- **What it is:** Named lists of packages in `pyproject.toml` that are installed only when asked for. `dev` (pytest, ruff, alembic) is installed by default; `pipelines` (pandas, pyarrow) is installed only with `--group pipelines`.
- **Where we use it:** `[dependency-groups]` in `pyproject.toml`. CI runs `uv sync --locked --dev --group pipelines`. The Docker image runs `uv sync --locked --no-dev`, so it gets neither.
- **Why this over the alternative:** One big dependency list would ship pandas to the production API image, which never reads Food.com data. The tradeoff is remembering the flag: without it, pipeline tests fail with "no module named pandas".
- **Common question:** How do you keep a production image small when the repo also has data-processing code? Dependency groups, so each environment installs only its own.


### Structured outputs and closed vocabularies
- **What it is:** Sending a JSON schema with the request so the API forces the model's answer to match it: right keys, right types, and only allowed values for any field marked as an enum (a fixed list). A closed vocabulary is that fixed list, such as our 19 units. The guarantee is on the shape of the answer, not on whether the values are correct.
- **Where we use it:** `build_output_schema`, `UNITS` and `CUISINES` in `pipelines/foodcom/augment.py`. `validate_result` checks the rules a schema cannot express, such as one entry per ingredient position.
- **Why this over the alternative:** Asking for JSON in the prompt works most of the time, but across 212,846 calls some answers would be broken or use "Tbsp." instead of "tbsp", and each fix is a second paid call. The tradeoff is that the model can still be wrong inside the shape, so we still measure accuracy on a hand-checked sample.
- **Common question:** How do you get reliable structured data out of an LLM? Constrain the output with a schema, then validate what the schema cannot check.

### Anchor and completeness check
- **What it is:** The anchor is the list that every other field attaches to; here, the recipe's `ingredient_parts`, which the model answers one-for-one by position. Like a join key, it only works if it is complete: a missing row cannot be recovered downstream. A completeness check compares the anchor with an independent signal (here, the quantities list and the steps) on real rows before building on it.
- **Where we use it:** The check found about three quarters of recipes have more quantities than names, and the steps use unlisted items such as oil. The fix is `extra_ingredients` in `build_output_schema` and `validate_result` in `pipelines/foodcom/augment.py` (DECISIONS #26 amendment).
- **Why this over the alternative:** Trusting a column because it looks tidy is cheaper but silently drops data, and we would only notice after paying for the full run. A check on 15 rows plus a keyword count cost nothing. The tradeoff is that the keyword count is rough, so we still hand-check the model's extras.
- **Common question:** How do you validate a dataset before building a pipeline on it? Compare each key column with an independent field on a sample, and measure the gap instead of assuming it.

### Label granularity and near-neighbour confusion
- **What it is:** How many classes a labeler has, and how finely they split. Too few and useful distinctions collapse into one label (filipino becomes `other`). Too many and near-neighbour labels (british and irish, szechuan and chinese) cover almost the same items, so the labeler picks between them almost at random and the data becomes inconsistent.
- **Where we use it:** `CUISINES` and `MAX_CUISINES` in `pipelines/foodcom/augment.py` (90 labels, at most 2 per recipe). We merged pairs the model cannot reliably separate, kept a few umbrella labels for countries we did not list, and allowed a region to pair with its parent.
- **Why this over the alternative:** A short list is cheaper and more consistent but loses filters users want. A very long list is expressive but costs input tokens on every call (about +677 per call here) and splits the same dishes across labels. The confusion is a risk we have not measured yet: repeat the same recipes twice and count differing labels, then look at a confusion matrix on a hand-labelled sample.
- **Common question:** How do you decide how many classes to use? Trade specificity against consistency, check a confusion matrix, and merge labels the evaluator cannot separate.

### Baseline for evaluation
- **What it is:** A simple, cheap method whose score a model has to beat to justify its cost. It is a floor, not a competitor. Coverage (how many items get a label) and accuracy (how many labels are right) are measured separately.
- **Where we use it:** `baseline_cuisines` and `CUISINE_KEYWORDS` in `pipelines/foodcom/augment.py`. It maps Food.com's own keyword and category tags to our cuisines and labels 20.1% of the subset (it was 15.9% before we widened the cuisine list to 90). It has no way to say "italian", because no tag in the data does.
- **Why this over the alternative:** Without a baseline, "the model tagged 100% of recipes" sounds good but says nothing about whether it is right. The tradeoff is that the baseline's labels are biased toward recipes whose uploader added a cuisine tag, so agreement with it does not prove accuracy on the other 84%.
- **Common question:** Why compare a model to a baseline? To show it adds value over something simple, and to separate "covers more" from "is more correct".

### Append-only results file (resumable jobs)
- **What it is:** Writing each finished result as one line to a file, flushed right away, and skipping already-finished keys on a rerun. A crash loses at most the call in flight.
- **Where we use it:** `append_record` and `load_done_keys` in `pipelines/foodcom/augment.py`, writing `data/interim/augment_results.jsonl`, keyed by `recipe_key`.
- **Why this over the alternative:** Rewriting one output file at the end would lose every paid result if the run stopped halfway. The key must be stable between runs (a list index is not), or a rerun could skip or repeat the wrong recipes. The tradeoff is that the file is the only copy of paid output, so it needs a backup off the laptop (DECISIONS #24).
- **Common question:** How do you make a long, paid job safe to rerun? Save results as you go under a stable key, and skip keys already saved.

### Environment file and .env.example
- **What it is:** `.env` holds real secrets (API key, database URL) and is git-ignored. `.env.example` lists the same variable names with empty values and is committed, so a new clone knows what to fill in.
- **Where we use it:** `.env.example` at the repo root; `uv run --env-file .env ...` loads `.env` for a run.
- **Why this over the alternative:** Putting keys in code or committing `.env` leaks them into git history, which is permanent. Having no template means the next person finds the missing variables by crashing. The tradeoff is keeping the template in step with the variables the code reads.
- **Common question:** How do you manage secrets in a repo? Keep them out of git, document the names in a template, and inject real values at run time.

### LLM cost: input, output, thinking and batching
- **What it is:** LLM calls are billed per token, with output priced higher than input (5 times for Claude Haiku 5.5: $0.10 vs $0.50 per million tokens, from the model price table cached 2026-10-06). Models that "think" before answering also bill those thinking tokens as output. The Message Batches API runs requests asynchronously (usually within an hour) at half price.
- **Where we use it:** `estimate_cost` and `print_report` in `pipelines/foodcom/augment.py` project the cost of the full run from measured tokens per recipe. The Batches API is planned for the full run, not built yet.
- **Why this over the alternative:** Estimating cost from the text length alone was off by about 2 times in our 3-recipe test (about 1,570 input and 700 output tokens per recipe, against our guess of 800 and 350). The cause was thinking tokens: a raw response reported 589 thinking tokens out of 910 output tokens, and across the 200-recipe pilot about 80% of output was not the answer. Measuring on a pilot before a large run avoids a surprise bill.
- **Common question:** How do you estimate and control the cost of an LLM pipeline? Measure real tokens per item on a small sample, project to the full size, and use batching for work that is not interactive.
