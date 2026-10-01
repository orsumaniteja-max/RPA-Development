"""Persist downloaded cases in the portal's Azure SQL tables."""

import os

class RpaSqlTrackingService:
    def record_submission(self, application_name, prescription_id, submitted_at, connection=None):
        """Record confirmed submission UTC time without changing download CreatedAt."""
        from datetime import datetime, timezone
        import pymssql
        timestamp = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Submission timestamp must include a UTC offset")
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        settings = {"server": os.getenv("AZURE_SQL_SERVER"),
                    "database": os.getenv("AZURE_SQL_DATABASE"),
                    "user": os.getenv("AZURE_SQL_USERNAME"),
                    "password": os.getenv("AZURE_SQL_PASSWORD")}
        if not all(settings.values()):
            raise RuntimeError("Missing Azure SQL settings for submission tracking")
        owns_connection = connection is None
        connection = connection or pymssql.connect(**settings, login_timeout=15, timeout=30)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE c SET CaseSubmisisonAt = CASE WHEN c.CaseSubmisisonAt IS NULL "
                "OR c.CaseSubmisisonAt < %s THEN %s ELSE c.CaseSubmisisonAt END "
                "FROM dbo.RpaDownloadedCase c JOIN dbo.RpaApplication a ON a.ID = c.ApplicationId "
                "WHERE a.ApplicationName = %s AND c.PrescriptionId = %s",
                (timestamp, timestamp, application_name, prescription_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Expected one downloaded-case row for submission tracking")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if owns_connection:
                connection.close()

    def sync(self, application_name, prescription_ids):
        import pymssql

        settings = {
            "server": os.getenv("AZURE_SQL_SERVER"),
            "database": os.getenv("AZURE_SQL_DATABASE"),
            "user": os.getenv("AZURE_SQL_USERNAME"),
            "password": os.getenv("AZURE_SQL_PASSWORD"),
        }
        missing = [key for key, value in settings.items() if not value]
        if missing:
            raise RuntimeError("Missing Azure SQL settings for RPA tracking: " + ", ".join(missing))
        connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
        try:
            cursor = connection.cursor()
            # Hold range locks until commit so concurrent workers cannot create
            # duplicate masters or duplicate application/prescription pairs.
            cursor.execute(
                "SELECT ID FROM dbo.RpaApplication WITH (UPDLOCK, HOLDLOCK) "
                "WHERE ApplicationName = %s", (application_name,),
            )
            row = cursor.fetchone()
            if row:
                application_id = row[0]
            else:
                cursor.execute(
                    "INSERT INTO dbo.RpaApplication (ApplicationName) "
                    "OUTPUT INSERTED.ID VALUES (%s)", (application_name,),
                )
                application_id = cursor.fetchone()[0]
            cursor.execute(
                "SELECT PrescriptionId FROM dbo.RpaDownloadedCase WITH (UPDLOCK, HOLDLOCK) "
                "WHERE ApplicationId = %s", (application_id,),
            )
            existing = {row[0] for row in cursor.fetchall()}
            for prescription_id in dict.fromkeys(prescription_ids):
                if prescription_id in existing:
                    continue
                cursor.execute(
                    "INSERT INTO dbo.RpaDownloadedCase (ApplicationId, PrescriptionId) "
                    "SELECT %s, %s WHERE NOT EXISTS ("
                    "SELECT 1 FROM dbo.RpaDownloadedCase WITH (UPDLOCK, HOLDLOCK) "
                    "WHERE ApplicationId = %s AND PrescriptionId = %s)",
                    (application_id, prescription_id, application_id, prescription_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
