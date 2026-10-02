# Data Model

> Which data lives where, and how the stores connect. Exact tables and columns live in the migration files and the Neo4j Cypher setup file (DECISIONS #2). Update this doc when we add an entity or a store, not on every migration.

## Stores at a glance

| Store | Role | Rebuildable? |
|---|---|---|
| Postgres `raw` schema | Untouched source data from pipelines (DECISIONS #14) | Yes, by re-pulling sources |
| Postgres (Supabase) | System of record for all entities, user data, conversations, and embeddings (pgvector) | No, back it up |
| Neo4j | Relationships: substitutions, recipe ingredients, prep tasks, store categories | Yes, rebuilt from Postgres by the ingestion job |
| External APIs (Spoonacular, Google Places) | Query-time only, never stored beyond what their terms allow | n/a |

**Rule of thumb:** if losing it would hurt, it lives in Postgres. Neo4j is a fast, derived view for graph-shaped questions.

## Postgres (Supabase)

| Group | Entities | Notes |
|---|---|---|
| Users | users, preferences | Profile set once: cuisines, dietary needs, location |
| Pantry | pantry_items | What the user has now, linked to `ingredient_id` |
| Recipes | recipes, ingredients, recipe_ingredients, prep_tasks | From the open dataset plus user-saved recipes. `prep_tasks` comes from LLM extraction at ingestion |
| Embeddings | recipe embeddings, ingredient embeddings (pgvector) | Recipe embeddings power semantic search. Ingredient embeddings are the substitution model's output |
| Plans | meal_plans, plan_items | A week's approved plan and what's cooked each day |
| Conversations | conversations, messages | Our own transcript tables. `conversations.thread_id` matches the LangGraph thread |
| Feedback | substitution_events | Every substitution the agent proposed and whether the user accepted it. Labels for evaluating the model |
| Agent state | LangGraph checkpointer tables | Created and managed by the library. Don't query them for history, use `messages` |
| Stores | saved place IDs only | See DECISIONS #9 |
| Recalls | recalls, recall_ingredient_matches | From the FDA pipeline. Matches link recalls to `ingredient_id` |
| Pipeline ops | pipeline_runs, pipeline_watermarks | Run log (rows loaded, duration, status) and last-loaded marker per source |
| Future | price_history | Only if the prices phase happens |

## Neo4j

**Nodes**

| Label | Key property | Mirrors |
|---|---|---|
| `Ingredient` | `ingredient_id` | `ingredients` |
| `Recipe` | `recipe_id` | `recipes` |
| `PrepTask` | `prep_task_id` | `prep_tasks` (ingredient + technique + form) |
| `StoreCategory` | `name` (e.g. asian_grocery) | Small curated list |

**Relationships**

| Relationship | Meaning | Properties |
|---|---|---|
| `(Ingredient)-[:USED_IN]->(Recipe)` | Recipe calls for this ingredient | quantity, unit |
| `(Ingredient)-[:SUBSTITUTES_FOR]->(Ingredient)` | Substitution candidate | weight, model_version. Direction is DECISIONS #11 |
| `(Recipe)-[:REQUIRES]->(PrepTask)` | Recipe needs this prep step | |
| `(PrepTask)-[:APPLIES_TO]->(Ingredient)` | Which ingredient gets prepped | |
| `(StoreCategory)-[:LIKELY_CARRIES]->(Ingredient)` | Where to look for uncommon items | |

## How the stores connect

- Postgres IDs are the shared keys. Every Neo4j node carries the same `ingredient_id`, `recipe_id`, or `prep_task_id` as its Postgres row.
- Data flows one way: Postgres to Neo4j, via the ingestion job. Nobody writes entities directly to Neo4j.
- The substitution model reads ingredient features from Postgres, writes embeddings to pgvector, and writes scores to `SUBSTITUTES_FOR` edges in Neo4j.
- User accept/reject decisions land in `substitution_events` in Postgres and feed the next model evaluation.

## Pipelines

| Pipeline | Source | Lands in `raw` | Transforms into | Schedule |
|---|---|---|---|---|
| Recipe ingestion | Open recipe dataset | raw recipes | recipes, ingredients, recipe_ingredients, prep_tasks, recipe embeddings | Batch, rerun as needed |
| USDA nutrients | USDA FoodData Central | raw nutrients | ingredient nutrient features | On new USDA releases |
| FDA recalls | openFDA food enforcement API | raw recalls | recalls, recall_ingredient_matches | Scheduled, incremental by watermark |
| Graph sync | Postgres clean tables | n/a | Neo4j nodes and edges | After recipe or scoring changes |
| Substitution scoring | Ingredient features | n/a | ingredient embeddings (pgvector), `SUBSTITUTES_FOR` weights (Neo4j) | On model change |

**Who does what:** dbt handles SQL transforms and data tests. Python handles LLM prep extraction, embeddings, API pulls, and graph sync.

**Every pipeline:** is idempotent, writes a `pipeline_runs` row, and uses `pipeline_watermarks` if it loads incrementally.

## Main queries

| Question | Where it's answered |
|---|---|
| "Something healthy" recipe search | pgvector similarity on recipe embeddings |
| What can sub for X? | Neo4j, 1-hop `SUBSTITUTES_FOR` walk, ranked by weight, filtered by pantry |
| What can I make with what's left? | Neo4j, fan-in on `USED_IN` from pantry ingredients |
| Which prep is shared this week? | Neo4j, `PrepTask` nodes linked to 2+ of the week's recipes |
| Is anything in my pantry or plan recalled? | Postgres join of `recall_ingredient_matches` against pantry and plan items |
| Where do I buy shio koji? | Neo4j `LIKELY_CARRIES` for the category, then Google Places at query time for actual stores |
