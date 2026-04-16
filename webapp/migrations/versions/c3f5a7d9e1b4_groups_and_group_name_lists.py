"""Add group_name_list and UserGroup.source_list_id, seed predefined lists

Introduces the GroupNameList model used by the System -> Group Names admin page
and the student registration group selector. Adds an optional source_list_id
FK on user_group referencing the predefined list a group was created from.
Seeds two predefined lists (Raid, Fuzzing) that admins can enable for
registration.

Revision ID: c3f5a7d9e1b4
Revises: b2e4f6a8c0d2
Create Date: 2026-04-13

"""

import sqlalchemy as sa
from alembic import op


revision = "c3f5a7d9e1b4"
down_revision = "b2e4f6a8c0d2"
branch_labels = None
depends_on = None


RAID_NAMES = [
    "Backprop Bandits (BAB)",
    "Botnet Busters (BOB)",
    "Debug Dingos (DED)",
    "Hackintosh Heros (HAH)",
    "Neural Ninjas (NEN)",
    "Sigmoid Sniffers (SIS)",
    "Adversarial Apes (ADA)",
    "Binary Beavers (BIB)",
    "Crypto Crows (CRC)",
    "Dropout Dragons (DRD)",
    "Entropy Eagles (ENE)",
    "Firewall Foxes (FIF)",
    "Gradient Gorillas (GRG)",
    "Hashing Hornets (HAS)",
    "Inference Iguanas (INI)",
    "Jailbreak Jackals (JAJ)",
    "Kernel Koalas (KEK)",
    "Logits Lemurs (LOL)",
    "Malware Mongoose (MAM)",
    "Nonce Nightjars (NON)",
    "Overflow Owls (OVO)",
    "Payload Pandas (PAP)",
    "Quantum Quolls (QUQ)",
    "Recurrent Ravens (RER)",
    "Softmax Sharks (SOS)",
    "Tensor Tigers (TET)",
    "Unicode Unicorns (UNU)",
    "Vector Vipers (VEV)",
    "Weights Wolves (WEW)",
    "XOR Xerus (XOX)",
    "Yottabyte Yaks (YOY)",
    "ZeroDay Zebras (ZEZ)",
]


FUZZING_NAMES = [
    "AFL Assassins",
    "Angora Antelopes",
    "Bitflip Badgers",
    "Boofuzz Bears",
    "CmpLog Cheetahs",
    "Corpus Crusaders",
    "Dharma Dragons",
    "Driller Dolphins",
    "Eclipser Eagles",
    "Entropy Elephants",
    "FairFuzz Ferrets",
    "Fuzzer Falcons",
    "Grammar Griffins",
    "Grimoire Gazelles",
    "Harness Hawks",
    "Honggfuzz Hyenas",
    "Instrumentation Impalas",
    "Jazzer Jaguars",
    "KLEE Koalas",
    "LibFuzzer Lions",
    "Mutation Mantis",
    "NAUTILUS Narwhals",
    "Oracle Owls",
    "PeachPit Pythons",
    "Queue Quokkas",
    "Radamsa Ravens",
    "Sanitizer Sharks",
    "Syzkaller Sparrows",
    "Taint Tigers",
    "Unicorn Ocelots",
    "Weizz Wolves",
    "Zzuf Zebras",
]


def upgrade():
    op.create_table(
        "group_name_list",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "enabled_for_registration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("names", sa.PickleType(), nullable=False),
    )

    op.add_column(
        "user_group",
        sa.Column("source_list_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_group_source_list_id",
        "user_group",
        "group_name_list",
        ["source_list_id"],
        ["id"],
    )

    group_name_list = sa.table(
        "group_name_list",
        sa.column("name", sa.Text),
        sa.column("enabled_for_registration", sa.Boolean),
        sa.column("names", sa.PickleType),
    )

    op.bulk_insert(
        group_name_list,
        [
            {
                "name": "Raid",
                "enabled_for_registration": False,
                "names": RAID_NAMES,
            },
            {
                "name": "Fuzzing",
                "enabled_for_registration": False,
                "names": FUZZING_NAMES,
            },
        ],
    )


def downgrade():
    op.drop_constraint("fk_user_group_source_list_id", "user_group", type_="foreignkey")
    op.drop_column("user_group", "source_list_id")
    op.drop_table("group_name_list")
