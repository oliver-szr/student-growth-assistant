"""Run from project root: .venv/Scripts/python.exe codex/migrate.py"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.database import engine
from app.services.schema_migrations import upgrade_database
upgrade_database(engine)
print('Database schema upgraded to Alembic head; previous data retained.')
