"""add raw schema, recipe source columns, recipe_cuisine

Revision ID: bd4767ab853b
Revises: fe3310413886
Create Date: 2026-10-30 09:51:44.182757

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd4767ab853b"
down_revision: str | Sequence[str] | None = "fe3310413886"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Copied from pipelines/foodcom/augment.py on purpose. A migration is a snapshot of
# what was done on one day, so it must not import code that can change later.
# Cuisines are not seeded here: the list is still changing (DECISIONS #26), so a
# later revision seeds them once it is final. Units are stable.
UNITS = [
    "g", "kg", "ml", "l",
    "tsp", "tbsp", "cup", "fl_oz", "oz", "lb",
    "piece", "clove", "slice", "can", "package", "bunch", "pinch", "dash",
    "to_taste",
]  # fmt: skip


def upgrade() -> None:
    """Get the database ready for the Food.com load (DECISIONS #24).

    1. Create the raw schema, where load.py writes prepared data and dbt reads it.
    2. Add Food.com columns to recipes. They are nullable because user-saved
       recipes use the same table and have no source id, steps, or times.
       source_ref is unique so the later upsert (ON CONFLICT) can tell a
       recipe it has already loaded from a new one.
    3. Create the recipe_cuisine junction table (recipes have 1 or 2 cuisines).
    4. Add recipe_ingredient.is_extra: true for ingredients the LLM found in the
       steps that the source list lacks (DECISIONS #26). Existing and user-saved
       rows are listed ingredients, so the default is false.
    5. Seed the units lookup rows, the closed list the LLM may answer with, so
       every answer maps to an id.
    """
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")

    op.add_column("recipes", sa.Column("source_ref", sa.BigInteger))
    op.add_column("recipes", sa.Column("instructions", sa.Text))
    op.add_column("recipes", sa.Column("total_minutes", sa.Integer))
    op.add_column("recipes", sa.Column("servings", sa.Integer))
    op.create_unique_constraint("uq_recipes_source_ref", "recipes", ["source_ref"])

    op.add_column(
        "recipe_ingredient",
        sa.Column("is_extra", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "recipe_cuisine",
        sa.Column("recipe_id", sa.BigInteger, sa.ForeignKey("recipes.recipe_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cuisine_id", sa.BigInteger, sa.ForeignKey("cuisines.cuisine_id", ondelete="CASCADE"), primary_key=True),
    )

    # No ids are passed: the id columns are identity columns, so Postgres numbers
    # the rows itself. Hand-picked ids would leave its counter behind and the next
    # insert would collide.
    units = sa.table("units", sa.column("unit_name", sa.Text))
    op.bulk_insert(units, [{"unit_name": name} for name in UNITS])


def downgrade() -> None:
    """Undo upgrade() in reverse order.

    Drops raw and everything in it. Safe because raw only holds data rebuilt by
    load.py from local files, so no paid LLM output is lost.
    """
    # Only the seeded names are deleted, so rows added later by hand are kept.
    # If a recipe_ingredient row still points at a unit, this fails on purpose.
    units = sa.table("units", sa.column("unit_name", sa.Text))
    op.execute(sa.delete(units).where(units.c.unit_name.in_(UNITS)))

    op.drop_table("recipe_cuisine")
    op.drop_column("recipe_ingredient", "is_extra")

    op.drop_constraint("uq_recipes_source_ref", "recipes", type_="unique")
    op.drop_column("recipes", "servings")
    op.drop_column("recipes", "total_minutes")
    op.drop_column("recipes", "instructions")
    op.drop_column("recipes", "source_ref")

    op.execute("DROP SCHEMA IF EXISTS raw CASCADE")
