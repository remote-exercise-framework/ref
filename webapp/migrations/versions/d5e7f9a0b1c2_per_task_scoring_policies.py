"""Replace scoring_policy with per_task_scoring_policies on exercise_config

The single-policy-per-exercise model is replaced by a dict of per-task
policies keyed by task_name. The old `scoring_policy` column was WIP and
had no deployed data, so it is dropped outright without preservation.

Revision ID: d5e7f9a0b1c2
Revises: c3f5a7d9e1b4
Create Date: 2026-04-14

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5e7f9a0b1c2"
down_revision = "c3f5a7d9e1b4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("exercise_config", schema=None) as batch_op:
        batch_op.drop_column("scoring_policy")
        batch_op.add_column(
            sa.Column("per_task_scoring_policies", sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("exercise_config", schema=None) as batch_op:
        batch_op.drop_column("per_task_scoring_policies")
        batch_op.add_column(sa.Column("scoring_policy", sa.JSON(), nullable=True))
