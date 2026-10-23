from alembic import context
from app.database import Base, engine
from app import models

def run(connection):
    # SQLite table replacement needs FK enforcement disabled outside a transaction.
    # Explicit BEGIN also makes DDL rollback real (sqlite3's legacy mode does not).
    if connection.in_transaction():
        raise RuntimeError('Migrations require a fresh connection, not a caller transaction.')
    connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
    connection.commit()
    try:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
        if connection.exec_driver_sql('PRAGMA foreign_key_check').first():
            raise RuntimeError('Migration produced invalid foreign keys; rolled back.')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.commit()

connection = context.config.attributes.get('connection')
if connection is not None:
    run(connection)
else:
    with engine.connect() as connection:
        run(connection)
