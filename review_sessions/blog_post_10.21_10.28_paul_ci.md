# Week of 10.21 to 10.28: CI lint and pytest (Paul)

## Summary
Started the Week 1 GitHub Actions task: a workflow that runs a linter and pytest on every pull request. This does not deploy anything and does not need GCP.

## PRs this week
| PR | What it did | State |
|---|---|---|
| [#13](https://github.com/andrewtclim/meal-prep-app/pull/13) | Alembic migrations for the ER diagram tables | Open |

## Session: 2026-10-21
### What we worked on and why
Branched `feat/ci-lint-pytest` from `main`. CI is the remaining Week 1 task that does not depend on the recipe dataset or on PR #13. The workflow will run on GitHub's machines when a PR opens. Added Ruff with `uv add --dev ruff`. It is in the `dev` group in `pyproject.toml` next to pytest (`ruff>=0.17.1`). `uv run ruff check .` from the repo root reported all checks passed. `ruff check` only reports issues; it does not edit files. `uv run pytest` passed the one health test. Starlette prints a deprecation warning that `TestClient` prefers `httpx2`; the test still exits 0. PR #12 noted the same warning and left it alone.

### Key idea: `uv add --dev` and Docker
`uv add --dev ruff` adds Ruff to the `dev` list in `pyproject.toml`, records Ruff and its dependencies in `uv.lock`, and installs it into `.venv`. `--dev` means the package is for working on the repo, not for running the API.

The image skips that list because the Dockerfile asks it to:

`Dockerfile`

```dockerfile
RUN uv sync --locked --no-dev
```

`--no-dev` installs only the main dependencies (FastAPI, uvicorn). Pytest and Ruff stay off the image. CI calls `uv sync --locked --dev` so it can lint and test.

### Key code
`.github/workflows/ci.yml` is the workflow. GitHub runs it on a fresh Ubuntu machine, not on a laptop.

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
```

`name` is the label in the GitHub checks list. `on` is the trigger: every pull request, and every push to `main`.

```yaml
jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
```

One job, named `lint-and-test`, on GitHub's current Ubuntu image. `checkout` copies this repo onto that machine. Without it, the later commands would have no files.

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
```

`uses` runs someone else's published action instead of a shell command. This one installs uv and Python 3.12, matching `requires-python` in `pyproject.toml`.

```yaml
      - name: Install dependencies
        run: uv sync --locked --dev

      - name: Lint
        run: uv run ruff check .

      - name: Test
        run: uv run pytest
```

`run` is a shell command. `--locked` fails the job if `uv.lock` does not match `pyproject.toml`. `--dev` installs pytest and Ruff, which the Docker image skips with `--no-dev`. The last two lines are the same commands that passed locally. If either exits with an error, the check on the PR goes red.

### Decisions and concepts
- DECISIONS #22: uv, with a dev group and `uv sync --locked --no-dev` in Docker
- CONCEPTS: [uv](../docs/CONCEPTS.md#uv), [GitHub Actions CI](../docs/CONCEPTS.md#github-actions-ci)

## What we'd explain differently next time
Optional: fill in after the workflow runs on a PR.
