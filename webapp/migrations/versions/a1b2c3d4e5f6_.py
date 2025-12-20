"""Replace pub_key/priv_key unique constraints with SHA256 hash indexes

Fixes GitHub issue #31: pub_key index size limitation.

PostgreSQL B-tree indexes have a max row size of ~2704 bytes. Large SSH keys
exceed this limit. SHA256 hash indexes produce a fixed 64-char hex output,
avoiding the size limit while maintaining uniqueness enforcement.

Revision ID: a1b2c3d4e5f6
Revises: 4c71c9e8bba4
Create Date: 2025-12-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "4c71c9e8bba4"
branch_labels = None
depends_on = None


def upgrade():
    # Drop existing unique constraints
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_constraint("user_pub_key_key", type_="unique")
        batch_op.drop_constraint("user_priv_key_key", type_="unique")

    # Create SHA256 hash-based unique indexes
    op.create_index(
        "ix_user_pub_key_hash",
        "user",
        [sa.text("encode(sha256(pub_key::bytea), 'hex')")],
        unique=True,
    )
    op.create_index(
        "ix_user_priv_key_hash",
        "user",
        [sa.text("encode(sha256(priv_key::bytea), 'hex')")],
        unique=True,
    )


def downgrade():
    # Drop hash indexes
    op.drop_index("ix_user_pub_key_hash", table_name="user")
    op.drop_index("ix_user_priv_key_hash", table_name="user")

    # Restore original unique constraints
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.create_unique_constraint("user_pub_key_key", ["pub_key"])
        batch_op.create_unique_constraint("user_priv_key_key", ["priv_key"])
