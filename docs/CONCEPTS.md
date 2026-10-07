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
