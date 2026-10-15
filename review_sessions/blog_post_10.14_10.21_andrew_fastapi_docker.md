# Week of 10.14 to 10.21: FastAPI and Docker (Andrew)

## Summary
Finished the Docker side of the hello endpoint by adding a `.dockerignore` to PR #10, and measured what it actually changes. Next up is CI (lint + pytest).

## PRs this week
| PR | What it did | State |
|---|---|---|
| [#10](https://github.com/andrewtclim/meal-prep-app/pull/10) | `/health` endpoint, Dockerfile, test, `.dockerignore` | Open |
| [#11](https://github.com/andrewtclim/meal-prep-app/pull/11) | Author name in weekly post filenames | Merged |

## Session: 2026-10-15
### What we worked on and why
Added `.dockerignore` to PR #10 instead of a separate PR (I changed my mind from the 10-14 plan: it is a small change to the same Docker setup, and reviewers see it in one place). Then checked whether it does anything today.

### Key code
`.dockerignore`
```
.git
.env
.env.*
tests/
docs/
infra/
recipe_db_audit/
```
Everything listed is invisible to `docker build`. The main reason is safety: a future `COPY . .` would otherwise copy `.env` and the full repo into the image.

Measurement: `docker build --progress=plain` reported a context transfer of about 800 bytes with and without the file, even though the folder is 1.1 GB. BuildKit only sends files a `COPY` asks for, and our Dockerfile copies just `requirements.txt` and `app/`. So the file is insurance, not a speedup. We then ran the image and `curl localhost:8000/health` returned `{"status":"ok"}`.

### Decisions and concepts
- No new DECISIONS entry.
- CONCEPTS: [Docker build context and .dockerignore](../docs/CONCEPTS.md#docker-build-context-and-dockerignore)
- Next: GitHub Actions CI (lint + pytest), then CD.

## What we'd explain differently next time
Why I first assumed the ignore file would speed up builds. Measure before claiming a benefit.
