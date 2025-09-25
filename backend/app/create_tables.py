"""Utility: create database tables using SQLAlchemy metadata.create_all (no Alembic).

Run this script with the project's venv to ensure the database has the tables required by models.
Example: python app\create_tables.py
"""
import sys
from urllib.parse import urlparse, unquote
from core.database import engine, Base
from sqlalchemy import text
from core.logging_config import app_logger
from core.config import settings


def create_tables():
    app_logger.info("create_tables: starting create_all")
    try:
        Base.metadata.create_all(bind=engine)
        app_logger.info("create_tables: create_all completed successfully")
    except Exception as e:
        app_logger.error(f"create_tables: failed to create tables: {e}")
        raise


def ensure_auth_fk_for_chats_owner():
    """Ensure that chats.owner_id FK references auth.users(id).
    If the FK points to another schema.table (for example public.users), replace it.
    This function performs safe checks and runs inside a transaction.
    """
    try:
        with engine.begin() as conn:
            # ensure auth schema exists (no-op if already present)
            try:
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
                app_logger.info("create_tables: ensured schema 'auth' exists")
            except Exception:
                app_logger.debug("create_tables: could not ensure auth schema (may already exist or lack privileges)")

            # Find FK constraint for chats.owner_id (best-effort by name then by columns)
            fk_row = conn.execute(text(
                """
                SELECT con.conname as conname,
                       nsp2.nspname as referenced_schema,
                       cls2.relname as referenced_table
                FROM pg_constraint con
                JOIN pg_class cls ON cls.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
                JOIN pg_class cls2 ON cls2.oid = con.confrelid
                JOIN pg_namespace nsp2 ON nsp2.oid = cls2.relnamespace
                WHERE con.contype = 'f' AND cls.relname = 'chats'
                AND con.conkey IS NOT NULL
                """
            )).fetchall()

            target_fk = None
            for row in fk_row:
                # If this FK references users table, pick it
                if row.referenced_table == 'users':
                    target_fk = row
                    break

            if not target_fk:
                app_logger.info("create_tables: no foreign key on chats referencing users found; nothing to change")
                return

            conname = target_fk.conname
            referenced_schema = target_fk.referenced_schema
            referenced_table = target_fk.referenced_table
            app_logger.info("create_tables: found FK", extra={"constraint": conname, "schema": referenced_schema, "table": referenced_table})

            # If the FK already points to auth.users, nothing to do
            if referenced_schema == 'auth' and referenced_table == 'users':
                app_logger.info("create_tables: chats.owner_id already references auth.users; nothing to do")
                return

            # Otherwise, alter constraint: drop and recreate to point to auth.users
            try:
                app_logger.info("create_tables: altering FK to point to auth.users", extra={"old_schema": referenced_schema, "old_table": referenced_table})
                # Drop constraint
                conn.execute(text(f"ALTER TABLE chats DROP CONSTRAINT IF EXISTS {conname}"))
                # Recreate constraint referencing auth.users
                conn.execute(text("ALTER TABLE chats ADD CONSTRAINT chats_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id)"))
                app_logger.info("create_tables: FK chats.owner_id now references auth.users")
            except Exception as e:
                app_logger.exception("create_tables: failed to alter FK to auth.users")
                raise
    except Exception as e:
        app_logger.exception(f"ensure_auth_fk_for_chats_owner failed: {e}")
        # Do not re-raise; create_tables should continue even if FK fix couldn't be applied
        return


if __name__ == "__main__":
    try:
        # Small safety: require explicit env toggle to run in non-dev environments
        if not settings.create_tables_on_startup:
            app_logger.warning("create_tables: settings.create_tables_on_startup is False — aborting manual create. Set to True to allow." )
            print("create_tables: disabled by settings.create_tables_on_startup (set to True to enable)")
            sys.exit(1)

        # Parse and display DB credentials (mask password)
        try:
            db_url = settings.database_url
            # Prefer SQLAlchemy's URL parser which understands provider-specific DSNs
            try:
                from sqlalchemy.engine import make_url

                url_obj = make_url(db_url)
                scheme = url_obj.drivername
                username = url_obj.username
                password = url_obj.password
                host = url_obj.host
                port = url_obj.port
                dbname = url_obj.database
            except Exception:
                # Fallback to urllib.parse for simple URLs
                parsed = urlparse(db_url)
                scheme = parsed.scheme
                username = unquote(parsed.username) if parsed.username else None
                password = unquote(parsed.password) if parsed.password else None
                host = parsed.hostname
                port = parsed.port
                dbname = parsed.path[1:] if parsed.path and parsed.path.startswith('/') else parsed.path

            masked_pw = None
            if password:
                masked_pw = password[0] + "*" * (len(password) - 2) + password[-1] if len(password) > 2 else "**"

            print("create_tables: database credentials:")
            print(f"  scheme: {scheme}")
            print(f"  host: {host}")
            print(f"  port: {port}")
            print(f"  db: {dbname}")
            print(f"  user: {username}")
            print(f"  password: {masked_pw}")
            app_logger.info(f"create_tables: will connect to db {scheme}://{host}:{port}/{dbname} as user={username}")
        except Exception as e:
            # Print parsing error to stdout for easier debugging
            app_logger.warning(f"create_tables: failed to parse database_url: {e}")
            print(f"create_tables: failed to parse database_url: {e}")

        # Show current schema / search_path and existing user tables (if possible)
        try:
            with engine.connect() as conn:
                try:
                    row = conn.execute(text("SELECT current_database(), current_schema(), current_setting('search_path')")).fetchone()
                    if row:
                        current_db, current_schema, search_path = row
                        print(f"create_tables: connected database={current_db}")
                        print(f"create_tables: current_schema={current_schema}")
                        print(f"create_tables: search_path={search_path}")
                    else:
                        print("create_tables: could not determine current schema/search_path")
                except Exception as e:
                    print(f"create_tables: warning: failed to read current_schema/search_path: {e}")
                    app_logger.debug(f"create_tables: error reading schema info: {e}")

                try:
                    tables = conn.execute(text(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                        "ORDER BY table_schema, table_name"
                    )).fetchall()
                    if tables:
                        print("create_tables: existing user tables:")
                        for schema, tbl in tables:
                            print(f"  {schema}.{tbl}")
                    else:
                        print("create_tables: no user tables found in the database")
                except Exception as e:
                    print(f"create_tables: warning: failed to list existing tables: {e}")
                    app_logger.debug(f"create_tables: error listing tables: {e}")
        except Exception as e:
            print(f"create_tables: warning: could not open DB connection to inspect schema: {e}")
            app_logger.warning(f"create_tables: could not open DB connection for inspection: {e}")
        # Now create tables and attempt FK fix
        create_tables()
        # Attempt to ensure chats.owner_id FK references auth.users
        ensure_auth_fk_for_chats_owner()
        print("create_tables: done")
    except Exception as exc:
        print(f"create_tables: error: {exc}")
        sys.exit(2)
