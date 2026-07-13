"""add_ilink_match_anchors

新增 iLink 引用回复匹配锚点列（ilink_sent_at_ms / ilink_msg_id），
并将 short_id 列长度从 8 扩到 12，以降低 short_id 碰撞概率。

Revision ID: c1a2b3d4e5f6
Revises: 3d42e162108d
Create Date: 2026-07-13 10:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '3d42e162108d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('hil_sessions', schema=None) as batch_op:
        # iLink 引用回复匹配锚点
        batch_op.add_column(
            sa.Column('ilink_sent_at_ms', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('ilink_msg_id', sa.String(length=64), nullable=False, server_default='')
        )
        # short_id 扩长到 12（兼容历史 8 位数据）
        batch_op.alter_column('short_id', sa.String(length=12), existing_type=sa.String(length=8))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('hil_sessions', schema=None) as batch_op:
        batch_op.alter_column('short_id', sa.String(length=8), existing_type=sa.String(length=12))
        batch_op.drop_column('ilink_msg_id')
        batch_op.drop_column('ilink_sent_at_ms')
