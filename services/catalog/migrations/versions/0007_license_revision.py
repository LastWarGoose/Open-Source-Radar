from alembic import op

revision = "catalog_0007"
down_revision = "catalog_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE catalog_license_state (
            singleton boolean PRIMARY KEY CHECK (singleton),
            revision uuid NOT NULL DEFAULT gen_random_uuid()
        )
    """)
    op.execute("INSERT INTO catalog_license_state (singleton) VALUES (true)")
    op.execute("""
        CREATE FUNCTION revise_catalog_licenses() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE old_key text; new_key text;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.source = 'PYPI' THEN
                old_key := OLD.license_key;
            END IF;
            IF TG_OP IN ('UPDATE', 'INSERT') AND NEW.source = 'PYPI' THEN
                new_key := NEW.license_key;
            END IF;
            IF TG_OP = 'TRUNCATE' OR old_key IS DISTINCT FROM new_key THEN
                UPDATE catalog_license_state SET revision = gen_random_uuid();
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER revise_licenses AFTER INSERT OR UPDATE OF source, license_key OR DELETE
        ON packages FOR EACH ROW EXECUTE FUNCTION revise_catalog_licenses()
    """)
    op.execute("""
        CREATE TRIGGER reset_licenses AFTER TRUNCATE ON packages
        FOR EACH STATEMENT EXECUTE FUNCTION revise_catalog_licenses()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER reset_licenses ON packages")
    op.execute("DROP TRIGGER revise_licenses ON packages")
    op.execute("DROP FUNCTION revise_catalog_licenses()")
    op.drop_table("catalog_license_state")
