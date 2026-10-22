"""create core recipe tables

Revision ID: 2beee51a1f35
Revises:
Create Date: 2026-10-20 22:05:40.686464

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2beee51a1f35"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tables needed to ask which recipes use an ingredient.

    Cuisines, allergens, ratings, and events are later migrations. Quantity
    and unit are nullable on recipe_ingredient because the open datasets we
    audited often have no amounts (DECISIONS #8).
    """
    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("city", sa.Text),
        sa.Column("weekly_budget", sa.Numeric(10, 2)),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "units",
        sa.Column("unit_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("unit_name", sa.Text, nullable=False),
        sa.UniqueConstraint("unit_name", name="uq_units_unit_name"),
    )
    op.create_table(
        "ingredients",
        sa.Column("ingredient_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("ingredient_name", sa.Text, nullable=False),
        sa.UniqueConstraint("ingredient_name", name="uq_ingredients_ingredient_name"),
    )
    op.create_table(
        "recipes",
        sa.Column("recipe_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("recipe_name", sa.Text, nullable=False),
    )
    op.create_table(
        "recipe_ingredient",
        sa.Column("recipe_ingredient_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("recipe_id", sa.BigInteger, sa.ForeignKey("recipes.recipe_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger, sa.ForeignKey("ingredients.ingredient_id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.unit_id")),
        sa.Column("preparation", sa.Text),
    )
    op.create_index(
        "ix_recipe_ingredient_ingredient_id",
        "recipe_ingredient",
        ["ingredient_id"],
    )
    op.create_table(
        "user_pantry",
        sa.Column("pantry_item_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingredient_id", sa.BigInteger, sa.ForeignKey("ingredients.ingredient_id"), nullable=False),
        sa.Column("unit_id", sa.BigInteger, sa.ForeignKey("units.unit_id")),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("date_acquired", sa.Date),
        sa.Column("expiration_date", sa.Date),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    """Drop the core tables. Children go first so foreign keys do not block the drop."""
    op.drop_table("user_pantry")
    op.drop_index("ix_recipe_ingredient_ingredient_id", table_name="recipe_ingredient")
    op.drop_table("recipe_ingredient")
    op.drop_table("recipes")
    op.drop_table("ingredients")
    op.drop_table("units")
    op.drop_table("users")
