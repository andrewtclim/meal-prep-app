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
