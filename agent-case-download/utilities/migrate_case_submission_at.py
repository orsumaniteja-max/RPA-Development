"""Add the nullable SQL submission timestamp without changing existing records."""
import os

from dotenv import load_dotenv
from utilities.config_reader import ConfigReader


def main():
    import pymssql
    load_dotenv(ConfigReader.PROJECT_ROOT / ".env")
    settings = {"server": os.getenv("AZURE_SQL_SERVER"),
                "database": os.getenv("AZURE_SQL_DATABASE"),
                "user": os.getenv("AZURE_SQL_USERNAME"),
                "password": os.getenv("AZURE_SQL_PASSWORD")}
    if not all(settings.values()):
        raise RuntimeError("Missing Azure SQL settings for migration")
    connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
    try:
        cursor = connection.cursor()
        cursor.execute((ConfigReader.PROJECT_ROOT / "docs/sql/add_case_submission_at.sql").read_text())
        connection.commit()
        cursor.execute(
            "SELECT TYPE_NAME(user_type_id), scale, is_nullable FROM sys.columns "
            "WHERE object_id = OBJECT_ID('dbo.RpaDownloadedCase') AND name = 'CaseSubmisisonAt'"
        )
        if tuple(cursor.fetchone() or ()) != ("datetime2", 3, True):
            raise RuntimeError("Unexpected CaseSubmisisonAt column definition")
        print("Verified CaseSubmisisonAt datetime2(3) NULL; CreatedAt unchanged.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
