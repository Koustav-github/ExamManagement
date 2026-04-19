"""role column added

Revision ID: c6fde2db1fca
Revises: 26bee25b609f
Create Date: 2026-04-19 21:17:48.560010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6fde2db1fca'
down_revision: Union[str, Sequence[str], None] = '26bee25b609f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


role_enum = sa.Enum('STUDENT', 'TEACHER', 'ADMIN', name='role')


def upgrade() -> None:
    role_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'students',
        sa.Column('role', role_enum, nullable=False, server_default='STUDENT'),
    )
    op.add_column(
        'teachers',
        sa.Column('role', role_enum, nullable=False, server_default='TEACHER'),
    )
    op.add_column(
        'admins',
        sa.Column('role', role_enum, nullable=False, server_default='ADMIN'),
    )


def downgrade() -> None:
    op.drop_column('admins', 'role')
    op.drop_column('teachers', 'role')
    op.drop_column('students', 'role')
    role_enum.drop(op.get_bind(), checkfirst=True)
