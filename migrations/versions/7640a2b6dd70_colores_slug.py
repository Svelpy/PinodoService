"""colores slug

Revision ID: 7640a2b6dd70
Revises: 05f6954f477c
Create Date: 2026-10-30 00:46:58.157249

"""
import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7640a2b6dd70'
down_revision: Union[str, Sequence[str], None] = '05f6954f477c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slug(text: str) -> str:
    """Copia congelada de app.shared.services.slug.generate_slug para el relleno inicial."""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('colores', sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=80), nullable=True))

    connection = op.get_bind()
    colores = connection.execute(sa.text('SELECT id, nombre FROM colores')).all()
    for color_id, nombre in colores:
        connection.execute(
            sa.text('UPDATE colores SET slug = :slug WHERE id = :id'),
            {'slug': _slug(nombre), 'id': color_id},
        )

    op.alter_column('colores', 'slug', nullable=False)
    op.drop_index(op.f('uq_colores_nombre'), table_name='colores', postgresql_where='(is_deleted = false)')
    op.create_index('uq_colores_slug', 'colores', ['slug'], unique=True, postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_colores_slug', table_name='colores', postgresql_where=sa.text('is_deleted = false'))
    op.create_index(op.f('uq_colores_nombre'), 'colores', ['nombre'], unique=True, postgresql_where=sa.text('is_deleted = false'))
    op.drop_column('colores', 'slug')
