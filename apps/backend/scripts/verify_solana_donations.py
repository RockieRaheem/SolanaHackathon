from sqlalchemy import create_engine, text

from harambeeone_api.config import get_settings


def main() -> None:
    engine = create_engine(get_settings().migration_database_url)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("""
            SELECT c.relrowsecurity,
                   has_table_privilege(
                     'anon', 'public.solana_donation_intents', 'SELECT'
                   ) AS anon_select,
                   has_table_privilege(
                     'authenticated', 'public.solana_donation_intents', 'SELECT'
                   ) AS auth_select,
                   EXISTS (
                     SELECT 1 FROM pg_trigger t
                     WHERE t.tgrelid = c.oid
                       AND t.tgname = 'solana_intents_immutable'
                   ) AS immutable_trigger,
                   EXISTS (
                     SELECT 1 FROM pg_constraint p
                     WHERE p.conrelid = c.oid
                       AND p.conname = 'uq_solana_intents_transaction_signature'
                   ) AS signature_unique
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = 'solana_donation_intents'
            """)
            )
            .mappings()
            .one()
        )
        assert row["relrowsecurity"]
        assert not row["anon_select"] and not row["auth_select"]
        assert row["immutable_trigger"] and row["signature_unique"]
    print("Verified Solana intent RLS, grants, replay constraint, and immutability trigger.")


if __name__ == "__main__":
    main()
