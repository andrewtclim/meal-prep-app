"""drop the package unit

Revision ID: c3a91e5d7f20
Revises: bd4767ab853b
Create Date: 2026-11-04 21:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a91e5d7f20"
down_revision: str | Sequence[str] | None = "bd4767ab853b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

units = sa.table("units", sa.column("unit_name", sa.Text))


def upgrade() -> None:
    """Remove `package` from the units lookup table (DECISIONS #26, 2026-11-02 amendment).

    Its size varies by product, so "1 package" and "1 lb" of the same food disagreed,
    and augment.py no longer lets the model answer with it. bd4767ab853b already ran
    on Supabase and seeded it, and an applied revision is never edited, so this is a
    new revision. If a recipe_ingredient row still points at it, the delete fails on
    purpose instead of leaving rows with no unit.
    """
    op.execute(sa.delete(units).where(units.c.unit_name == "package"))


def downgrade() -> None:
    """Put `package` back. It gets a new id, which is fine while nothing points at it."""
    op.bulk_insert(units, [{"unit_name": "package"}])
