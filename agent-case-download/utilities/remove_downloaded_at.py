"""Remove the redundant SQL DownloadedAt column from the configured database."""
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
        raise RuntimeError("Missing Azure SQL settings")
    connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('dbo.RpaDownloadedCase')")
        before = {row[0] for row in cursor.fetchall()}
        if not {"CreatedAt", "CaseSubmisisonAt"}.issubset(before):
            raise RuntimeError("Expected tracking columns missing; no changes made")
        cursor.execute((ConfigReader.PROJECT_ROOT / "docs/sql/remove_downloaded_at.sql").read_text())
        cursor.execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('dbo.RpaDownloadedCase')")
        after = {row[0] for row in cursor.fetchall()}
        if after != before - {"DownloadedAt"}:
            raise RuntimeError("Unexpected schema after removal")
        connection.commit()
        print("Verified: DownloadedAt removed; all other columns preserved, including CreatedAt and CaseSubmisisonAt.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
