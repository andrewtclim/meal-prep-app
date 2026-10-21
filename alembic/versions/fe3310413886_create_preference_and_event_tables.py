"""create preference and event tables

Revision ID: fe3310413886
Revises: 2beee51a1f35
Create Date: 2026-10-20 22:33:52.774766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "fe3310413886"
down_revision: Union[str, Sequence[str], None] = "2beee51a1f35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the rest of the ER diagram.

    Junction tables (user_cuisine, user_allergen, ingredient_allergen,
    user_recipe) store pairs. Their primary key is both ids together, so the
    same pair cannot be inserted twice. Deleting either side deletes the pair.
    """
    op.create_table(
        "cuisines",
        sa.Column("cuisine_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("cuisine_name", sa.Text, nullable=False),
        sa.UniqueConstraint("cuisine_name", name="uq_cuisines_cuisine_name"),
    )
    op.create_table(
        "allergens",
        sa.Column("allergen_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("allergen_name", sa.Text, nullable=False),
        sa.UniqueConstraint("allergen_name", name="uq_allergens_allergen_name"),
    )
    op.create_table(
        "user_cuisine",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cuisine_id", sa.BigInteger, sa.ForeignKey("cuisines.cuisine_id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "user_allergen",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("allergen_id", sa.BigInteger, sa.ForeignKey("allergens.allergen_id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "ingredient_allergen",
        sa.Column("ingredient_id", sa.BigInteger, sa.ForeignKey("ingredients.ingredient_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("allergen_id", sa.BigInteger, sa.ForeignKey("allergens.allergen_id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "user_recipe",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("recipe_id", sa.BigInteger, sa.ForeignKey("recipes.recipe_id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "user_recipe_rating",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("recipe_id", sa.BigInteger, sa.ForeignKey("recipes.recipe_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("liked", sa.Boolean, nullable=False),
    )
    op.create_table(
        "user_events",
        sa.Column("event_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_name", sa.Text, nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_properties", postgresql.JSONB),
    )


def downgrade() -> None:
    """Drop the preference and event tables. Children go first."""
    op.drop_table("user_events")
    op.drop_table("user_recipe_rating")
    op.drop_table("user_recipe")
    op.drop_table("ingredient_allergen")
    op.drop_table("user_allergen")
    op.drop_table("user_cuisine")
    op.drop_table("allergens")
    op.drop_table("cuisines")
