// Graph schema: the source of truth for Neo4j (DECISIONS #2).
// Applied by graphdb/schema.py. Every statement uses IF NOT EXISTS, so running
// this file twice changes nothing. Statements end with a semicolon.
//
// Nodes (key is the same id as the Postgres row, DATA_MODEL.md):
//   (:Ingredient {ingredient_id, name})              mirrors ingredients
//   (:Recipe     {recipe_id, name, source_ref})      mirrors recipes
//   (:PrepTask   {prep_task_id, technique, form})    mirrors prep_tasks (planned)
//
// Relationships (no constraint needed; they are created with MERGE):
//   (Ingredient)-[:USED_IN {quantity, unit, is_extra}]->(Recipe)
//   (Ingredient)-[:SUBSTITUTES_FOR {weight, model_version}]->(Ingredient)
//       a -> b means "a can replace b" (directional, one edge per direction)
//   (Recipe)-[:REQUIRES]->(PrepTask)
//   (PrepTask)-[:APPLIES_TO]->(Ingredient)
//
// Neo4j Community supports uniqueness constraints but not "must exist"
// constraints, so required properties are checked in the loader and its tests.

// A uniqueness constraint also builds an index on the key, so MERGE on
// ingredient_id is a lookup, not a scan of every Ingredient node.
CREATE CONSTRAINT ingredient_id_unique IF NOT EXISTS
FOR (i:Ingredient) REQUIRE i.ingredient_id IS UNIQUE;

CREATE CONSTRAINT recipe_id_unique IF NOT EXISTS
FOR (r:Recipe) REQUIRE r.recipe_id IS UNIQUE;

CREATE CONSTRAINT prep_task_id_unique IF NOT EXISTS
FOR (p:PrepTask) REQUIRE p.prep_task_id IS UNIQUE;

// The agent looks ingredients up by name ("do I have shallot?"). Not unique
// here: Postgres already enforces unique names, and the graph is a copy of it.
CREATE INDEX ingredient_name IF NOT EXISTS
FOR (i:Ingredient) ON (i.name);
