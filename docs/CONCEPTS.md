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
- **Where we use it:** `infra/` (provider, variables, GCS remote state backend). `main.tf` is still empty; resources come in a follow-up PR.
- **Why this over the alternative:** Clicking in the GCP console is faster once, but it is not reviewable in a PR and drifts between teammates. Terraform keeps one shared definition.
- **Common question:** Where does state live? In the GCS bucket configured in `infra/providers.tf`, not in git.

### Reproducible environments (spec file vs lock file)
- **What it is:** A spec file lists the packages we need with allowed version ranges; a lock file records the exact versions one install resolved to. Everyone builds their env from the same spec, so "works on my machine" bugs from mismatched versions go away. Conda manages the Python interpreter; pip installs the packages.
- **Where we use it:** `environment.yml` (Python version, pulls in the pip list), `requirements.txt` (package ranges, also used by the Dockerfile later).
- **Why this over the alternative:** Listing every package in `environment.yml` alone would leave Docker (pip only) with a second list that drifts. A plain `pip freeze` dump pins everything but mixes our real dependencies with their sub-dependencies, so nobody can tell what we chose. We have no lock file yet; add one (e.g. `pip-compile` or `uv`) if a sub-dependency update ever breaks CI.
- **Common question:** Why ranges like `>=1.0,<2` instead of exact pins? Minor and patch releases bring fixes and shouldn't break us; major versions can. Exact pins belong in a lock file, not the spec.
