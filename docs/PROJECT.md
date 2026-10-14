# Meal Prep Planning Agent (name TBD)

> What this project is and why. Decisions live in `docs/DECISIONS.md`, weekly status in `docs/ROADMAP.md`, and the data model in `docs/DATA_MODEL.md`. If anything in chat conflicts with these docs, the docs win.

## Audience

Working people who meal prep weekly and are tired of eating the same meal every day.[^1]

Pain points with traditional meal prep:
1. Reheated meals don't taste fresh and lose their texture
2. There's no variety across the week
3. Portion sizes are locked in once everything's packed
4. You don't get to cook or be creative during the week

## Problem Statement

Weekly meal planning means juggling three things: what you already have, what you want to make, and what's realistically available nearby. Most tools handle one of these in isolation, and none of them help when an ingredient is missing or not sold locally.

Instead of cooking full meals on Sunday and reheating them all week, users prep **components** once (diced aromatics, marinated proteins, washed greens) and cook fresh each night in a fraction of the time. The agent figures out which prep work is shared across the week's recipes so it only gets done once.

The user gives us the dishes they want (or general preferences), their current inventory, and their location. The agent returns a grocery task list, a prep task list, and a day-by-day cooking schedule, with smart substitutions and nearby stores for anything they need to buy.

## User Workflow

1. **Profile:** the user sets preferences once (cuisines, dietary needs, location).
2. **Start of week:** the user picks ~3 recipes, or asks the agent to suggest some based on their profile.
3. **Pantry:** the user marks what they already have.
4. **Gap analysis:** the agent checks each recipe against the pantry. For each missing ingredient, it decides between a substitution (ranked by our substitution model) and buying it.
5. **Plan:** the agent proposes three things:
   - **Grocery task:** what to buy and which nearby stores likely carry it, including specialty stores (e.g. H Mart for kimchi)
   - **Prep task:** shared prep consolidated across recipes, e.g. "two recipes use diced onion, dice it all today" or "Mon and Wed both use soy-garlic chicken, marinate it today"
   - **Daily schedule:** what to cook each night, sequenced by shelf life of both raw and prepped ingredients. If prepped food won't last until it's used, the agent moves that prep step later or suggests freezing a portion.
6. **Review:** the user pushes back or edits ("swap Wednesday's dish," "I don't want to go to two stores"), and the agent revises until the user approves.
7. **During the week:** each night's cook is short because the prep is already done.

## Data Sources

| Source | What we use it for | Notes |
|---|---|---|
| Open recipe dataset (Food.com on Kaggle is the first candidate) | Recipe store for search and planning, batch loaded into Postgres and Neo4j | Final choice is an open decision (DECISIONS #8). Confirm the license before loading |
| User-saved recipes | User's own recipes, same schema as the open dataset | |
| USDA FoodData Central | Nutrient profiles per ingredient, used as features for the substitution model | Public domain |
| openFDA food enforcement API | Food recalls, loaded on a schedule to flag recalled ingredients in a pantry or plan | Core build, tagged `should` |
| Google Places API | Nearby stores and store types, looked up at query time | Check Google's caching terms before storing anything beyond place IDs |
| User data | Profile, preferences, pantry, saved recipes, plans, conversations | Our own schema in Postgres |

We don't use Spoonacular: its terms ban storing anything beyond recipe ids, titles, and image URLs (DECISIONS #20).

## Tech Stack

| Tool | Role |
|---|---|
| LangGraph | Orchestrates the agent: intent parsing, pantry vs recipe checks, substitute vs buy, sequencing the week, multi-turn edits as stateful conversation (checkpointer on Postgres) |
| LangChain | Components used inside graph nodes: model wrappers, retrievers, Neo4j and pgvector integrations, tool definitions |
| Neo4j | Graph of ingredients, recipes, prep tasks, and store categories. Powers substitution walks, "what can I make with what's left," and prep consolidation |
| Supabase (Postgres + pgvector) | System of record for users, pantry, recipes, plans, and conversations, plus semantic recipe search |
| Google Places API | Nearby store matching |
| dbt | SQL transforms from raw to clean tables in Postgres, with data quality tests run in CI |
| Cloud Scheduler + Cloud Run Jobs (or AWS equivalent) | Runs scheduled pipelines |
| FastAPI | Wraps the agent as an API |
| Docker + GCP/AWS + Terraform | Containerized deployment, infra as code |
| GitHub Actions | CI (tests on pantry matching and substitution logic) and CD on merge to main |
| LangSmith / Langfuse | Tracing agent reasoning, especially substitution decisions |
| Streamlit | Demo frontend |

**Design rule:** deterministic steps (pantry checks, ranking subs by edge weight, shelf-life sorting) are plain Python nodes, not LLM calls. The LLM handles intent parsing, pushback, and writing the plan.

## ML Modeling

**Primary: ingredient substitution scoring.** Build ingredient embeddings from flavor profile, nutritional similarity, and culinary role, and score substitution quality by similarity (possibly a small learned ranking model later). Scores become weighted `SUBSTITUTES_FOR` edges in Neo4j, so the model generates the weights and the graph serves the queries. Evaluated against a hand-labeled set of substitution pairs, and later against real accept/reject feedback logged from users.

**Secondary: expiry-based prioritization.** Rank pantry items by typical shelf life (napa cabbage before dried spices) to drive day-by-day sequencing. Covers prepped components too (diced onion, marinated chicken), so the scheduler knows when a prep step has to move later in the week. Shelf-life values for prepped and marinated foods come from published food safety guidance, not guesses.

**Supporting step: prep task extraction.** At ingestion, an LLM parses recipe instructions into structured prep actions (ingredient, technique, form), e.g. (onion, dice, 1/2 inch) or (chicken thigh, marinate, soy-garlic). These become `PrepTask` nodes and are what make consolidation possible.

## Data Pipelines

We use **ELT**: raw data lands untouched in a `raw` schema in Postgres, then dbt (SQL) and Python (LLM extraction, embeddings) transform it into clean tables. When ingredient normalization improves, we rerun the transform instead of re-downloading sources.

| Pipeline | Schedule | What it does |
|---|---|---|
| Recipe ingestion | Batch, rerun as needed | Open dataset to `raw`, then normalization, prep task extraction, recipe embeddings |
| USDA nutrients | Batch, on new USDA releases | Nutrient features for the substitution model |
| FDA recalls | Scheduled, incremental | Loads only recalls since the last run, flags matching pantry and plan ingredients |
| Graph sync | After recipe or scoring changes | Rebuilds Neo4j from Postgres |
| Substitution scoring | On model change | Writes embeddings to pgvector and scores to Neo4j edges |

Every pipeline is idempotent (reruns don't duplicate rows), tracks a watermark for incremental loads where it applies, and writes a row to a run log. Details in `docs/DATA_MODEL.md`.

## Future Phases

| Feature | Purpose | Likely source |
|---|---|---|
| Grocery trip routing | Routes to nearby stores by car and transit | Google Routes API, regional GTFS transit feeds |
| Grocery prices | Budget management | No public API has per-store Bay Area prices. Options: Kroger API as a reference price, BLS regional averages, user receipt scanning |

## Out of Scope (for now)

- Real-time per-store inventory (no public data exists)
- Budget optimization and live pricing in the core build
- Full nutrition and macro optimization

---

[^1]: Inspired by https://www.youtube.com/watch?v=ZJe3yL7NHdA and https://www.youtube.com/watch?v=AVO0ifle-OU
