"""empty message

Revision ID: 6145fb21e678
Revises: 
Create Date: 2019-10-27 19:15:29.321685

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6145fb21e678'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('exercise',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('template_import_path', sa.Text(), nullable=False),
    sa.Column('template_path', sa.Text(), nullable=False),
    sa.Column('persistence_path', sa.Text(), nullable=False),
    sa.Column('short_name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('allow_internet', sa.Boolean(), nullable=True),
    sa.Column('build_job_result', sa.Text(), nullable=True),
    sa.Column('build_job_status', sa.Enum('NOT_BUILD', 'BUILDING', 'FINISHED', 'FAILED', name='exercisebuildstatus'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('persistence_path'),
    sa.UniqueConstraint('template_path')
    )
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('first_name', sa.Text(), nullable=False),
    sa.Column('surname', sa.Text(), nullable=False),
    sa.Column('password', sa.Binary(), nullable=False),
    sa.Column('mat_num', sa.Integer(), nullable=False),
    sa.Column('registered_date', sa.DateTime(), nullable=False),
    sa.Column('pub_key', sa.Text(), nullable=False),
    sa.Column('pub_key_ssh', sa.Text(), nullable=False),
    sa.Column('priv_key', sa.Text(), nullable=False),
    sa.Column('course_of_studies', sa.Enum('MASTER_ITS_NS', 'MASTER_ITS_IS', 'MASTER_AI', 'OTHER', name='courseofstudies'), nullable=True),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('login_name', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mat_num')
    )
    op.create_table('exercise_entry_service',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exercise_id', sa.Integer(), nullable=False),
    sa.Column('persistance_container_path', sa.Text(), nullable=True),
    sa.Column('files', sa.PickleType(), nullable=True),
    sa.Column('build_cmd', sa.PickleType(), nullable=True),
    sa.Column('disable_aslr', sa.Boolean(), nullable=False),
    sa.Column('cmd', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['exercise_id'], ['exercise.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exercise_instance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('network_id', sa.Text(), nullable=True),
    sa.Column('exercise_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['exercise_id'], ['exercise.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('network_id')
    )
    op.create_table('exercise_service',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exercise_id', sa.Integer(), nullable=False),
    sa.Column('files', sa.PickleType(), nullable=True),
    sa.Column('build_cmd', sa.PickleType(), nullable=True),
    sa.Column('disable_aslr', sa.Boolean(), nullable=False),
    sa.Column('bind_executable', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['exercise_id'], ['exercise.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exercise_instance_entry_service',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sa.Integer(), nullable=True),
    sa.Column('container_id', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['exercise_instance.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('container_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('exercise_instance_entry_service')
    op.drop_table('exercise_service')
    op.drop_table('exercise_instance')
    op.drop_table('exercise_entry_service')
    op.drop_table('user')
    op.drop_table('exercise')
    # ### end Alembic commands ###
