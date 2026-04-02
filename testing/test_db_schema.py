import os
import sys
import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.db.database import Base, sync_existing_schema
from backend.app.sessions.models import Session as SessionModel


class DatabaseSchemaSyncTests(unittest.TestCase):
    def test_sync_existing_schema_adds_missing_session_columns(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE verification_sessions (
                        id VARCHAR PRIMARY KEY,
                        status VARCHAR NOT NULL,
                        user_id VARCHAR NOT NULL,
                        filename VARCHAR,
                        file_path VARCHAR,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """
                )
            )

        Base.metadata.create_all(bind=engine)
        sync_existing_schema(engine)

        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("verification_sessions")}

        self.assertIn("lease_id", columns)
        self.assertIn("lease_holder_id", columns)
        self.assertIn("lease_acquired_at", columns)
        self.assertIn("heartbeat_at", columns)
        self.assertIn("version", columns)
        self.assertIn("reason_codes", columns)
        self.assertIn("connector_ids", columns)

        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        db = SessionLocal()
        try:
            session = SessionModel(user_id="user-1")
            db.add(session)
            db.commit()
            db.refresh(session)
            self.assertEqual(session.user_id, "user-1")
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
