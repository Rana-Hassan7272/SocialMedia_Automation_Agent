from src.database import DatabaseManager
from src.utils.logging_config import setup_logging


def main():
    setup_logging()
    db = DatabaseManager()
    db.initialize_database()
    print("Database ready.")
    print(f"URL: {db.database_url}")
    print("Production: set DATABASE_URL to your Neon connection string")
    print("Migrate:    python main.py migrate")
    print("Verify:     python main.py verify")
    print("Run app:    python main.py")


if __name__ == "__main__":
    main()
