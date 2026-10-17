from alembic import context
from app.database import Base, engine
from app import models

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()

connection = context.config.attributes.get('connection')
if connection is not None:
    run(connection)
else:
    with engine.connect() as connection:
        run(connection)
