"""Browser acceptance server: isolated SQLite and disabled paid AI calls."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--token', required=True, help='Run identity checked by the acceptance script')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_relative_to(ROOT / 'codex/.runtime') or not database.name.startswith('acceptance-'):
        parser.error('Test database must be a new acceptance-*.db under codex/.runtime')
    if database.exists():
        parser.error('Refusing to reuse an existing test database; choose a new filename')
    from sqlalchemy.orm import Session
    import uvicorn
    from app.database import create_sqlite_engine, get_db
    from app.main import app
    from app.services import claude_client

    # Do not read local .env or process keys while running acceptance tests.
    def unavailable():
        raise claude_client.AIServiceError('AI_NOT_CONFIGURED')
    claude_client.get_claude_config = unavailable
    # Routers/services imported the function by name; replace those references too.
    from app.routers import constraints
    from app.services import plan_explanation
    constraints.get_claude_config = unavailable
    plan_explanation.get_claude_config = unavailable

    args.database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(f'sqlite:///{args.database.resolve().as_posix()}')
    def test_db():
        with Session(engine, autoflush=False) as session:
            yield session
    app.state.db_engine = engine
    app.dependency_overrides[get_db] = test_db

    @app.get('/__acceptance__/identity')
    def identity():
        return {'mode': 'isolated-product-acceptance', 'token': args.token, 'database': database.name}
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port)
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
