"""Initial schema — all tables

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
        sa.Column('folder_path',  sa.String(),  nullable=False,   unique=True),
        sa.Column('display_name', sa.String()),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('added_at',     sa.DateTime(), server_default=sa.func.now()),
    )

    # ── images ─────────────────────────────────────────────────────────────────
    op.create_table(
        'images',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_path',       sa.String(),  nullable=False,   unique=True),
        sa.Column('filename',        sa.String(),  nullable=False),
        sa.Column('root_folder_id',  sa.Integer(), sa.ForeignKey('watched_folders.id')),
        sa.Column('relative_path',   sa.String()),
        sa.Column('folder_depth',    sa.Integer()),
        sa.Column('thumbnail_path',  sa.String()),
        sa.Column('file_hash',       sa.String()),
        sa.Column('faiss_id',        sa.Integer(),  unique=True),
        sa.Column('model_version',   sa.String()),
        sa.Column('width',           sa.Integer()),
        sa.Column('height',          sa.Integer()),
        sa.Column('file_size_bytes', sa.Integer()),
        sa.Column('image_width_px',  sa.Integer()),
        sa.Column('image_height_px',  sa.Integer()),
        sa.Column('last_indexed_at',   sa.DateTime()),
        sa.Column('date_added',      sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_seen',       sa.DateTime()),
        sa.Column('is_orphaned',     sa.Boolean(),  default=False),
        sa.Column('import_status',   sa.String(),   default='queued'),
        sa.Column('import_error',    sa.Text()),
    )
    op.create_index('ix_images_file_hash',     'images', ['file_hash'])
    op.create_index('ix_images_date_added',    'images', ['date_added'])
    op.create_index('ix_images_is_orphaned',   'images', ['is_orphaned'])
    op.create_index('ix_images_import_status', 'images', ['import_status'])

    # ── suppliers ──────────────────────────────────────────────────────────────
    op.create_table(
        'suppliers',
        sa.Column('id',             sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('canonical_name', sa.String(),  nullable=False,   unique=True),
        sa.Column('created_at',     sa.DateTime(), server_default=sa.func.now()),
    )

    # ── supplier_aliases ───────────────────────────────────────────────────────
    op.create_table(
        'supplier_aliases',
        sa.Column('id',           sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('alias',        sa.String(),  nullable=False,   unique=True),
        sa.Column('canonical_id', sa.Integer(), sa.ForeignKey('suppliers.id'), nullable=False),
    )

    # ── textile_metadata ───────────────────────────────────────────────────────
    op.create_table(
        'textile_metadata',
        sa.Column('id',                sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('image_id',          sa.Integer(), sa.ForeignKey('images.id'), unique=True, nullable=False),
        sa.Column('raw_ocr_text',      sa.Text()),
        sa.Column('supplier_id',       sa.Integer(), sa.ForeignKey('suppliers.id')),
        sa.Column('supplier_raw',      sa.String()),
        sa.Column('item_no',           sa.String()),
        sa.Column('order_no',          sa.String()),
        sa.Column('fabric_type',       sa.String()),
        sa.Column('construction',      sa.String()),
        sa.Column('construction_code', sa.String()),
        sa.Column('width_min',         sa.Float()),
        sa.Column('width_max',         sa.Float()),
        sa.Column('width_unit',        sa.String()),
        sa.Column('weight_gsm',        sa.Float()),
        sa.Column('weight_gyd',        sa.Float()),
        sa.Column('tolerance_pct',     sa.Float()),
        # Confidence scores
        sa.Column('conf_supplier',     sa.Float()),
        sa.Column('conf_item_no',      sa.Float()),
        sa.Column('conf_order_no',     sa.Float()),
        sa.Column('conf_fabric_type',  sa.Float()),
        sa.Column('conf_construction', sa.Float()),
        sa.Column('conf_width',        sa.Float()),
        sa.Column('conf_weight_gsm',   sa.Float()),
        sa.Column('conf_weight_gyd',   sa.Float()),
        sa.Column('conf_composition',  sa.Float()),
        # Tiers
        sa.Column('tier_supplier',     sa.Integer()),
        sa.Column('tier_item_no',      sa.Integer()),
        sa.Column('tier_order_no',     sa.Integer()),
        sa.Column('tier_fabric_type',  sa.Integer()),
        sa.Column('tier_construction', sa.Integer()),
        sa.Column('tier_width',        sa.Integer()),
        sa.Column('tier_weight_gsm',   sa.Integer()),
        sa.Column('tier_weight_gyd',   sa.Integer()),
        sa.Column('tier_composition',  sa.Integer()),
        # Review
        sa.Column('needs_review',      sa.Boolean(), default=False),
        sa.Column('manually_reviewed', sa.Boolean(), default=False),
        sa.Column('no_label_detected', sa.Boolean(), default=False),
        sa.Column('parsed_at',         sa.DateTime()),
        sa.Column('reviewed_at',       sa.DateTime()),
    )
    op.create_index('ix_textile_metadata_needs_review', 'textile_metadata', ['needs_review'])
    op.create_index('ix_textile_metadata_item_no',      'textile_metadata', ['item_no'])
    op.create_index('ix_textile_metadata_fabric_type',  'textile_metadata', ['fabric_type'])
    op.create_index('ix_textile_metadata_weight_gsm',    'textile_metadata', ['weight_gsm'])
    op.create_index('ix_textile_metadata_supplier_id',  'textile_metadata', ['supplier_id'])
    op.create_index('ix_textile_metadata_width_min',    'textile_metadata', ['width_min'])

    # ── fabric_composition ─────────────────────────────────────────────────────
    op.create_table(
        'fabric_composition',
        sa.Column('id',           sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('metadata_id',  sa.Integer(), sa.ForeignKey('textile_metadata.id'), nullable=False),
        sa.Column('material',     sa.String(),  nullable=False),
        sa.Column('material_raw', sa.String()),
        sa.Column('percentage',   sa.Float(),   nullable=False),
        sa.Column('sort_order',   sa.Integer()),
        sa.Column('tier',         sa.Integer()),
    )
    op.create_index('ix_fabric_composition_material', 'fabric_composition', ['material'])

    # ── material_aliases ───────────────────────────────────────────────────────
    op.create_table(
        'material_aliases',
        sa.Column('id',        sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('alias',     sa.String(),  nullable=False,   unique=True),
        sa.Column('canonical', sa.String(),  nullable=False),
    )

    # ── fabric_types ───────────────────────────────────────────────────────────
    op.create_table(
        'fabric_types',
        sa.Column('id',   sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(),  nullable=False,   unique=True),
    )

    # ── tags ───────────────────────────────────────────────────────────────────
    op.create_table(
        'tags',
        sa.Column('id',     sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name',   sa.String(),  nullable=False),
        sa.Column('color',  sa.String(),  default='#6366f1'),
        sa.Column('source', sa.String(),  nullable=False, default='manual'),
        sa.UniqueConstraint('name', 'source'),
    )

    # ── image_tags ─────────────────────────────────────────────────────────────
    op.create_table(
        'image_tags',
        sa.Column('image_id', sa.Integer(), sa.ForeignKey('images.id'), primary_key=True),
        sa.Column('tag_id',   sa.Integer(), sa.ForeignKey('tags.id'),   primary_key=True),
    )

    # ── duplicates ─────────────────────────────────────────────────────────────
    op.create_table(
        'duplicates',
        sa.Column('id',          sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('image_id_a',  sa.Integer(), sa.ForeignKey('images.id'), nullable=False),
        sa.Column('image_id_b',  sa.Integer(), sa.ForeignKey('images.id'), nullable=False),
        sa.Column('similarity',  sa.Float()),
        sa.Column('match_type',  sa.String()),
        sa.Column('detected_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('resolved',    sa.Boolean(),  default=False),
    )

    # ── search_history ─────────────────────────────────────────────────────────
    op.create_table(
        'search_history',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mode',            sa.String()),
        sa.Column('query_path',      sa.String()),
        sa.Column('query_thumbnail', sa.String()),
        sa.Column('filters_json',    sa.Text()),
        sa.Column('top_k',           sa.Integer()),
        sa.Column('result_count',    sa.Integer()),
        sa.Column('results_json',    sa.Text()),
        sa.Column('searched_at',     sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_search_history_searched_at', 'search_history', ['searched_at'])

    # ── app_settings ───────────────────────────────────────────────────────────
    op.create_table(
        'app_settings',
        sa.Column('key',   sa.String(), primary_key=True),
        sa.Column('value', sa.String(), nullable=False),
    )

    # ── schema_version ─────────────────────────────────────────────────────────
    op.create_table(
        'schema_version',
        sa.Column('version',     sa.Integer(), primary_key=True),
        sa.Column('applied_at',  sa.DateTime(), server_default=sa.func.now()),
        sa.Column('description', sa.String()),
    )

    # ── Seed data ──────────────────────────────────────────────────────────────
    _seed_material_aliases()
    _seed_fabric_types()
    _seed_default_settings()

    # Record this migration
    op.execute(
        "INSERT INTO schema_version (version, description) "
        "VALUES (1, 'Initial schema — all tables')"
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    tables = [
        'schema_version', 'app_settings', 'search_history', 'duplicates',
        'image_tags', 'tags', 'fabric_types', 'material_aliases',
        'fabric_composition', 'textile_metadata', 'supplier_aliases',
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
