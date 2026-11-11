"""Print the answers to the three graph questions on the toy data.

Run: uv run --group agent --env-file .env python -m graphdb.demo
(seed first with: python -m graphdb.seed_toy). Ids are from graphdb/toy/*.csv.
"""

from graphdb.client import close_driver
from graphdb.queries import find_substitutes, recipes_makeable_from, shared_prep_tasks

ONION, SHALLOT = 1, 2
PANTRY = {"garlic": 5, "spaghetti": 15, "olive oil": 27, "chili flake": 32}
WEEK = {1: "Soy-Garlic Chicken Stir-Fry", 3: "Beef Chili", 4: "Red Lentil Soup"}


def main() -> None:
    """Ask the three questions from DATA_MODEL.md and print readable answers."""
    print("Out of onion, what can I use?")
    for s in find_substitutes(ONION):
        print(f"  {s.name} (weight {s.weight})")

    print("\nOut of shallot? (the edge goes the other way, so the weight differs)")
    for s in find_substitutes(SHALLOT):
        print(f"  {s.name} (weight {s.weight})")

    print(f"\nPantry: {', '.join(PANTRY)}. What can I make, up to 1 item short?")
    for r in recipes_makeable_from(PANTRY.values(), max_missing=1):
        print(f"  {r.name}: missing {', '.join(r.missing_names) or 'nothing'}")

    print(f"\nThis week: {', '.join(WEEK.values())}. What prep is shared?")
    for t in shared_prep_tasks(WEEK):
        recipes = ", ".join(WEEK[i] for i in t.recipe_ids)
        print(f"  {t.technique} {t.ingredient_name} ({t.form}) once, for: {recipes}")
    close_driver()


if __name__ == "__main__":
    main()
