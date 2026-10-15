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
- **What it is:** Writing exact versions (`fastapi==0.143.0`) so every build installs the same libraries. Dev-only libraries (pytest, httpx) live in `requirements-dev.txt`, which includes the production file with `-r`.
- **Where we use it:** `requirements.txt` (installed in the image) and `requirements-dev.txt` (local and CI).
- **Why this over the alternative:** Unpinned `fastapi` installs whatever is newest on build day, so a build next month can break with no code change. Pins don't update themselves, so upgrades are a deliberate edit. DECISIONS #21 (proposed) moves to version ranges.
