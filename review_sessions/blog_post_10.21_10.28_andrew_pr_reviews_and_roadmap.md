# Week of 10.21 to 10.28: Reviewing Paul's PRs and a roadmap cleanup (Andrew)

## Summary
Read Paul's first two PRs (Alembic migrations and CI) and learned what each tool does, then fixed the ROADMAP rows that went stale when they merged.

## PRs this week
| PR | What it did | State |
|---|---|---|
| PR link (add once open) | Marks the CI and migrations rows in ROADMAP as done | Open |

PRs reviewed, not opened by me: [#13](https://github.com/andrewtclim/meal-prep-app/pull/13) (Alembic migrations, merged), [#14](https://github.com/andrewtclim/meal-prep-app/pull/14) (Ruff and pytest in CI, merged), [#15](https://github.com/andrewtclim/meal-prep-app/pull/15) (Ruff fixes in the Alembic files, merged).

## Session: 2026-10-22
### What we worked on and why
After merging the uv PR (#12), Paul's two PRs landed on `main` along with a small lint fix. We read through them to understand them before building on them. Then we found that `docs/ROADMAP.md` still showed the CI row as unowned and the migrations row as "not merged", so we fixed both in this docs-only PR. Per DECISIONS #18 the docs are the source of truth, so a stale roadmap misleads whoever reads it next.

### Key code
`docs/ROADMAP.md`
```markdown
| GitHub Actions: lint + pytest on every PR | must | Paul | done (PR #14 merged): ... |
| First Postgres migrations: ... | must | Paul | done (PR #13 merged): Alembic migrations for the 14 ER diagram tables ... |
```
Both rows now name the owner and the PR that finished them. The rule is that finished tasks update ROADMAP in the same PR as the work, which neither of those PRs did.

What we learned from reading the PRs:
- **Alembic** keeps the schema in versioned files in git. Each revision has `upgrade()` and `downgrade()`, `down_revision` chains them in order, and the database stores its current revision in `alembic_version`, so rerunning `uv run alembic upgrade head` does nothing.
- **Ruff** is a linter: it catches real mistakes (unused imports, undefined names), not just style. **pytest** runs our tests. CI runs both on a clean machine for every PR, and it caught the lint problems in the Alembic files, which is why PR #15 exists.
- **`uv sync --locked`** fails when `uv.lock` is stale, while `--frozen` silently installs from the stale lock. CI and Docker use `--locked`.

### Decisions and concepts
- No new DECISIONS entry. #22 (uv) is still Proposed.
- CONCEPTS: [GitHub Actions CI](../docs/CONCEPTS.md#github-actions-ci), [Database migration (Alembic)](../docs/CONCEPTS.md#database-migration-alembic), [Junction table](../docs/CONCEPTS.md#junction-table), [Lockfile](../docs/CONCEPTS.md#lockfile)
- Open questions for Paul: how will loads stay idempotent (DECISIONS #14) when `recipes` has no source id, and should `ruff` get an upper version bound like our other dependencies?

## What we'd explain differently next time
What `down_revision` does and why running the same migration command twice is safe.
