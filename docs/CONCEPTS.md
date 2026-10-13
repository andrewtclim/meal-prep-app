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

### Data profiling
- **What it is:** Checking a dataset against what the app needs before building on it: which fields exist, how much is missing or malformed, how many duplicates, and how big it is. The output is a short report, not a pipeline.
- **Where we use it:** a local audit script, not in the repo, for the Food.com datasets (DECISIONS #8). Its findings are summarized there.
- **Why this over the alternative:** Loading the data first and finding gaps later costs a schema and a pipeline built on the wrong source. Profiling found that neither dataset has ingredient units before we wrote any migration.
- **Common question:** How did you know the data was fit for purpose before building on it? You list the fields the app needs, then measure each one's coverage and quality, and include checks that can surprise you (e.g. whether two parallel arrays line up).
