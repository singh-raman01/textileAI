"""Initial schema — all tables (synced to current models)

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── watched_folders ────────────────────────────────────────────────────────
    op.create_table(
        'watched_folders',
        sa.Column('id',           sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('folder_path',  sa.String(1024), nullable=False, unique=True),
        sa.Column('display_name', sa.String(256), nullable=False, server_default=''),
        sa.Column('is_available', sa.Boolean(), nullable=False, default=True),
        sa.Column('added_at',     sa.DateTime(), server_default=sa.func.now()),
    )

    # ── images ─────────────────────────────────────────────────────────────────
    op.create_table(
        'images',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_path',       sa.String(1024), nullable=False, unique=True),
        sa.Column('filename',        sa.String(512), nullable=False),
        sa.Column('root_folder_id',  sa.Integer(), sa.ForeignKey('watched_folders.id'), index=True),
        sa.Column('relative_path',   sa.String(1024)),
        sa.Column('file_hash',       sa.String(64), index=True),
        sa.Column('thumbnail_path',  sa.String(1024)),
        sa.Column('faiss_id',        sa.Integer(), unique=True, index=True),
        sa.Column('model_version',   sa.String(128)),
        sa.Column('file_size_bytes', sa.Integer()),
        sa.Column('image_width_px',  sa.Integer()),
        sa.Column('image_height_px', sa.Integer()),
        sa.Column('is_orphaned',     sa.Boolean(), nullable=False, default=False, index=True),
        sa.Column('import_status',   sa.String(32), nullable=False, server_default='queued', index=True),
        sa.Column('import_error',    sa.Text()),
        sa.Column('date_added',      sa.DateTime(), server_default=sa.func.now(), index=True),
        sa.Column('last_indexed_at', sa.DateTime()),
    )

    # ── suppliers ──────────────────────────────────────────────────────────────
    op.create_table(
        'suppliers',
        sa.Column('id',        sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('canonical', sa.String(256), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # ── supplier_aliases ───────────────────────────────────────────────────────
    op.create_table(
        'supplier_aliases',
        sa.Column('id',           sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('supplier_id',  sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=False),
        sa.Column('alias',        sa.String(256), nullable=False, unique=True),
    )

    # ── textile_metadata ───────────────────────────────────────────────────────
    op.create_table(
        'textile_metadata',
        sa.Column('id',                 sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('image_id',           sa.Integer(), sa.ForeignKey('images.id'), unique=True, nullable=False),
        sa.Column('raw_ocr_text',       sa.Text()),
        sa.Column('supplier',           sa.String(256), index=True),
        sa.Column('supplier_confidence', sa.Float()),
        sa.Column('item_no',            sa.String(128)),
        sa.Column('order_no',           sa.String(128)),
        sa.Column('fabric_type',        sa.String(128), index=True),
        sa.Column('construction',       sa.String(256)),
        sa.Column('width_min',          sa.Float()),
        sa.Column('width_max',          sa.Float()),
        sa.Column('width_unit',         sa.String(8)),
        sa.Column('weight_gsm',         sa.Float()),
        sa.Column('weight_gyd',         sa.Float()),
        sa.Column('tolerance_pct',      sa.Float()),
        sa.Column('needs_review',       sa.Boolean(), nullable=False, default=False),
        sa.Column('no_label_detected',  sa.Boolean(), nullable=False, default=False),
        sa.Column('extracted_at',       sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_textile_metadata_needs_review', 'textile_metadata', ['needs_review'])
    op.create_index('ix_textile_metadata_item_no',      'textile_metadata', ['item_no'])
    op.create_index('ix_textile_metadata_fabric_type',  'textile_metadata', ['fabric_type'])
    op.create_index('ix_textile_metadata_weight_gsm',    'textile_metadata', ['weight_gsm'])
    op.create_index('ix_textile_metadata_width_min',    'textile_metadata', ['width_min'])

    # ── fabric_compositions ────────────────────────────────────────────────────
    op.create_table(
        'fabric_compositions',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('metadata_id',     sa.Integer(), sa.ForeignKey('textile_metadata.id'), nullable=False, index=True),
        sa.Column('material',        sa.String(128), nullable=False),
        sa.Column('material_raw',    sa.String(128), nullable=False),
        sa.Column('percentage',      sa.Float(), nullable=False),
        sa.Column('confidence_tier', sa.Integer(), nullable=False),
    )
    op.create_index('ix_fabric_compositions_material', 'fabric_compositions', ['material'])

    # ── material_aliases ───────────────────────────────────────────────────────
    op.create_table(
        'material_aliases',
        sa.Column('id',        sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('alias',     sa.String(128), nullable=False, unique=True),
        sa.Column('canonical', sa.String(128), nullable=False),
    )

    # ── fabric_types ───────────────────────────────────────────────────────────
    op.create_table(
        'fabric_types',
        sa.Column('id',   sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(128), nullable=False, unique=True),
    )

    # ── tags ───────────────────────────────────────────────────────────────────
    op.create_table(
        'tags',
        sa.Column('id',      sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name',    sa.String(256), nullable=False, unique=True),
        sa.Column('is_auto', sa.Boolean(), nullable=False, default=False),
    )

    # ── image_tags ─────────────────────────────────────────────────────────────
    op.create_table(
        'image_tags',
        sa.Column('id',       sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('image_id', sa.Integer(), sa.ForeignKey('images.id'), nullable=False),
        sa.Column('tag_id',   sa.Integer(), sa.ForeignKey('tags.id'), nullable=False),
        sa.UniqueConstraint('image_id', 'tag_id'),
    )

    # ── duplicates ─────────────────────────────────────────────────────────────
    op.create_table(
        'duplicates',
        sa.Column('id',           sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('image_id_a',   sa.Integer(), sa.ForeignKey('images.id'), nullable=False),
        sa.Column('image_id_b',   sa.Integer(), sa.ForeignKey('images.id'), nullable=False),
        sa.Column('is_exact_md5', sa.Boolean(), nullable=False, default=False),
        sa.Column('similarity',   sa.Float()),
        sa.Column('match_type',   sa.String(16), nullable=False, server_default='exact'),
        sa.Column('resolved',     sa.Boolean(), nullable=False, default=False),
        sa.Column('detected_at',  sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('image_id_a', 'image_id_b'),
    )

    # ── search_history ─────────────────────────────────────────────────────────
    op.create_table(
        'search_history',
        sa.Column('id',               sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('query_image_path', sa.String(1024)),
        sa.Column('k',                sa.Integer()),
        sa.Column('result_count',     sa.Integer()),
        sa.Column('top_result_ids',   sa.Text()),
        sa.Column('searched_at',      sa.DateTime(), server_default=sa.func.now(), index=True),
    )
    op.create_index('ix_search_history_searched_at', 'search_history', ['searched_at'])

    # ── app_settings ───────────────────────────────────────────────────────────
    op.create_table(
        'app_settings',
        sa.Column('key',   sa.String(128), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
    )

    # ── schema_version ─────────────────────────────────────────────────────────
    op.create_table(
        'schema_version',
        sa.Column('id',          sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('version',     sa.String(32), nullable=False),
        sa.Column('applied_at',  sa.DateTime(), server_default=sa.func.now()),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
    )

    # ── Seed data ──────────────────────────────────────────────────────────────
    _seed_material_aliases()
    _seed_fabric_types()
    _seed_default_settings()

    # Record this migration
    op.execute(
        "INSERT INTO schema_version (version, description) "
        "VALUES ('0001', 'Initial schema — synced to current models')"
    )


def downgrade() -> None:
    tables = [
        'schema_version', 'app_settings', 'search_history', 'duplicates',
        'image_tags', 'tags', 'fabric_types', 'material_aliases',
        'fabric_compositions', 'textile_metadata', 'supplier_aliases',
        'suppliers', 'images', 'watched_folders',
    ]
    for table in tables:
        op.drop_table(table)


# ── Seed helpers ───────────────────────────────────────────────────────────────

def _seed_material_aliases() -> None:
    aliases = [
        ('POLYSTEER',    'POLYESTER'), ('POLYSTER',     'POLYESTER'),
        ('POIYESTER',    'POLYESTER'), ('POLY',         'POLYESTER'),
        ('PES',          'POLYESTER'), ('PET',          'POLYESTER'),
        ('SPUNPOLYSTER', 'SPUNPOLYESTER'), ('SPUNPOLY', 'SPUNPOLYESTER'),
        ('RYON',         'RAYON'),     ('RY',           'RAYON'),
        ('VISCOSE',      'RAYON'),
        ('SP',           'SPANDEX'),   ('EA',           'SPANDEX'),
        ('ELASTANE',     'SPANDEX'),   ('LYCRA',        'SPANDEX'),
        ('WL',           'WOOL'),      ('WO',           'WOOL'),
        ('CT',           'COTTON'),    ('CTN',          'COTTON'),
        ('CO',           'COTTON'),
        ('NY',           'NYLON'),     ('PA',           'NYLON'),
        ('ACRY',         'ACRYLIC'),   ('AC',           'ACRYLIC'),
        ('PAN',          'ACRYLIC'),
        ('LI',           'LINEN'),     ('FLAX',         'LINEN'),
        ('LX',           'LUREX'),     ('METALLIC',     'LUREX'),
    ]
    for alias, canonical in aliases:
        op.execute(
            f"INSERT OR IGNORE INTO material_aliases (alias, canonical) "
            f"VALUES ('{alias}', '{canonical}')"
        )


def _seed_fabric_types() -> None:
    types = [
        'TWEED', 'JERSEY', 'DENIM', 'CHIFFON', 'SATIN', 'VELVET',
        'LACE', 'KNIT', 'WOVEN', 'FLEECE', 'BROCADE', 'CREPE',
        'ORGANZA', 'TAFFETA', 'GEORGETTE', 'POPLIN', 'CANVAS',
        'CORDUROY', 'MUSLIN', 'VOILE', 'LAWN', 'FLANNEL', 'MESH',
        'INTERLOCK', 'PIQUE', 'PONTE', 'SCUBA', 'TERRY', 'VELOUR',
    ]
    for t in types:
        op.execute(f"INSERT OR IGNORE INTO fabric_types (name) VALUES ('{t}')")


def _seed_default_settings() -> None:
    defaults = [
        ('default_k',                    '20'),
        ('duplicate_threshold',          '0.97'),
        ('history_retention_days',       '365'),
        ('disk_space_warning_mb',        '500'),
        ('thumbnail_cache_max_mb',       '2048'),
        ('include_unverified_in_filters','true'),
        ('language',                     'en'),
        ('theme',                        'system'),
        ('debug_logging',                'false'),
    ]
    for key, value in defaults:
        op.execute(
            f"INSERT OR IGNORE INTO app_settings (key, value) "
            f"VALUES ('{key}', '{value}')"
        )
