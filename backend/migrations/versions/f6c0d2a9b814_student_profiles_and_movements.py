"""Expand student profiles and preserve dated learner movements."""
from alembic import op
import sqlalchemy as sa

revision = 'f6c0d2a9b814'
down_revision = 'e42b81c0fa63'
branch_labels = None
depends_on = None

COLUMNS = {
    'middle_name': sa.String(80), 'suffix': sa.String(20),
    'date_of_birth': sa.Date(), 'enrollment_date': sa.Date(),
    'guardian_name': sa.String(160), 'guardian_phone': sa.String(40), 'address': sa.String(500),
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column['name'] for column in inspector.get_columns('students')}
    for name, datatype in COLUMNS.items():
        if name not in existing:
            op.add_column('students', sa.Column(name, datatype, nullable=True))
    if 'enrollment_type' not in existing:
        op.add_column('students', sa.Column('enrollment_type', sa.String(20), nullable=False, server_default='regular'))
    if 'student_movements' not in inspector.get_table_names():
        op.create_table('student_movements',
            sa.Column('id', sa.Uuid(), primary_key=True),
            sa.Column('student_id', sa.Uuid(), sa.ForeignKey('students.id'), nullable=False),
            sa.Column('school_year', sa.String(20), nullable=False),
            sa.Column('section', sa.String(120), nullable=False),
            sa.Column('kind', sa.String(30), nullable=False),
            sa.Column('effective_on', sa.Date(), nullable=False),
            sa.Column('reason', sa.String(500), nullable=True),
            sa.Column('source', sa.String(20), nullable=False),
            sa.Column('created_by', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_student_movements_student_id', 'student_movements', ['student_id'])
        op.create_index('ix_student_movements_school_year', 'student_movements', ['school_year'])


def downgrade():
    op.drop_table('student_movements')
    for name in ['enrollment_type', *reversed(COLUMNS)]:
        op.drop_column('students', name)
