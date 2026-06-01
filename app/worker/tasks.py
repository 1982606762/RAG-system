"""Background tasks run by the Celery worker (a separate process/container).

The worker shares the app image and code, so it calls the EXACT same ingest
pipeline the synchronous endpoint uses — no logic is duplicated.
"""

from worker.celery_app import celery_app
from rag.service import ingest_file


@celery_app.task(name="ingest_file")
def ingest_task(path: str, user_id: str, model: str | None = None) -> dict:
    """Run the full ingest pipeline for one file (owned by user_id); return
    its summary dict.

    Whatever this returns becomes the task `result` the API polls. If
    ingest_file raises, Celery marks the task FAILURE and stores the error
    so /tasks/{id} can report it.
    """
    return ingest_file(path, user_id, model=model)
