# infra

Terraform for our GCP project (`meal-prep-app-510920`, region `us-west1`). See DECISIONS #10 and the Terraform entry in `docs/CONCEPTS.md`.

## Files

| File | Role |
|---|---|
| `versions.tf` | Allowed Terraform and Google provider versions |
| `.terraform.lock.hcl` | Exact provider version and checksums. Commit it, don't hand-edit it |
| `providers.tf` | GCS state backend and Google provider defaults |
| `variables.tf` | Input declarations |
| `terraform.tfvars` | Input values. Never put secrets here |
| `main.tf` | Reserved; resources live in focused files below |
| `apis.tf` | Enable required Google APIs |
| `artifact_registry.tf` | Docker repository `api` |
| `github_wif.tf` | GitHub Actions → GCP Workload Identity Federation + deploy SA |
| `outputs.tf` | Registry path, deploy SA email, WIF provider name for later CI |

## State bucket (one-time bootstrap)

State lives in `gs://meal-prep-app-510920-tfstate` under the `infra/` prefix. The bucket is created outside this config, because Terraform needs it to exist before `init` can run. If it ever needs recreating:

```sh
gcloud storage buckets create gs://meal-prep-app-510920-tfstate \
  --project=meal-prep-app-510920 --location=us-west1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://meal-prep-app-510920-tfstate --versioning
```

Versioning keeps old copies of state, so a corrupted or deleted state file can be restored. Check it's on with:

```sh
gcloud storage buckets describe gs://meal-prep-app-510920-tfstate --format="value(versioning_enabled)"
```

## Access

Each teammate needs a project role that can read and write the state bucket (e.g. `roles/storage.objectAdmin` on the bucket) plus whatever roles the resources need. 

## Running it

```sh
gcloud auth application-default login   # credentials come from your gcloud login, never a key file in the repo
cd infra
terraform init                          # downloads the provider, connects to the state bucket
terraform fmt -check && terraform validate
terraform plan                          # review APIs, Artifact Registry, WIF, IAM
terraform apply                         # only after the plan has been reviewed
```

After apply, `terraform output` prints values a later GitHub Actions workflow will need (no secrets — resource names only). Cloud Run roles and the Actions workflow itself are a later PR.

