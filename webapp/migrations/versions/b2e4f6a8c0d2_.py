"""Add exercise_config table and migrate administrative fields

Introduces ExerciseConfig model to hold administrative settings (category,
deadlines, grading points, scoring policy) shared across all versions of
an exercise. Exercise rows now reference ExerciseConfig via config_id FK.

Revision ID: b2e4f6a8c0d2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-13

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2e4f6a8c0d2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create exercise_config table
    op.create_table(
        "exercise_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("short_name", sa.Text(), nullable=False, unique=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("submission_deadline_start", sa.DateTime(), nullable=True),
        sa.Column("submission_deadline_end", sa.DateTime(), nullable=True),
        sa.Column(
            "submission_test_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("max_grading_points", sa.Integer(), nullable=True),
        sa.Column("scoring_policy", sa.JSON(), nullable=True),
    )

    # 2. Populate exercise_config from existing exercise rows.
    #    For each distinct short_name, take the values from the highest version.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("""
            SELECT DISTINCT ON (short_name)
                short_name, category, submission_deadline_start,
                submission_deadline_end, submission_test_enabled,
                max_grading_points
            FROM exercise
            ORDER BY short_name, version DESC
        """)
    ).fetchall()

    exercise_config = sa.table(
        "exercise_config",
        sa.column("short_name", sa.Text),
        sa.column("category", sa.Text),
        sa.column("submission_deadline_start", sa.DateTime),
        sa.column("submission_deadline_end", sa.DateTime),
        sa.column("submission_test_enabled", sa.Boolean),
        sa.column("max_grading_points", sa.Integer),
    )

    for row in rows:
        conn.execute(
            exercise_config.insert().values(
                short_name=row.short_name,
                category=row.category,
                submission_deadline_start=row.submission_deadline_start,
                submission_deadline_end=row.submission_deadline_end,
                submission_test_enabled=row.submission_test_enabled,
                max_grading_points=row.max_grading_points,
            )
        )

    # 3. Add config_id column to exercise (nullable initially)
    op.add_column(
        "exercise",
        sa.Column("config_id", sa.Integer(), nullable=True),
    )

    # 4. Backfill config_id
    conn.execute(
        sa.text("""
            UPDATE exercise
            SET config_id = exercise_config.id
            FROM exercise_config
            WHERE exercise.short_name = exercise_config.short_name
        """)
    )

    # 5. Make config_id NOT NULL and add FK constraint
    op.alter_column("exercise", "config_id", nullable=False)
    op.create_foreign_key(
        "fk_exercise_config_id",
        "exercise",
        "exercise_config",
        ["config_id"],
        ["id"],
    )

    # 6. Drop old columns from exercise
    op.drop_column("exercise", "category")
    op.drop_column("exercise", "submission_deadline_start")
    op.drop_column("exercise", "submission_deadline_end")
    op.drop_column("exercise", "submission_test_enabled")
    op.drop_column("exercise", "max_grading_points")


def downgrade():
    # Re-add columns to exercise
    op.add_column("exercise", sa.Column("category", sa.Text(), nullable=True))
    op.add_column(
        "exercise", sa.Column("submission_deadline_start", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "exercise", sa.Column("submission_deadline_end", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "exercise",
        sa.Column(
            "submission_test_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "exercise", sa.Column("max_grading_points", sa.Integer(), nullable=True)
    )

    # Copy data back from exercise_config
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE exercise
            SET category = exercise_config.category,
                submission_deadline_start = exercise_config.submission_deadline_start,
                submission_deadline_end = exercise_config.submission_deadline_end,
                submission_test_enabled = exercise_config.submission_test_enabled,
                max_grading_points = exercise_config.max_grading_points
            FROM exercise_config
            WHERE exercise.config_id = exercise_config.id
        """)
    )

    # Drop FK and column
    op.drop_constraint("fk_exercise_config_id", "exercise", type_="foreignkey")
    op.drop_column("exercise", "config_id")

    # Drop exercise_config table
    op.drop_table("exercise_config")
