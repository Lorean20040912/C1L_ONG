"""Worker-ul pentru sarcinile lungi (OCR, import bancar, rapoarte mari...).

Pornire: `python -m app.worker`. Sarcinile se pun în coadă cu `enqueue(...)`.
"""

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings

QUEUE_NAME = "default"


def connection() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def enqueue(func, *args, **kwargs):
    return Queue(QUEUE_NAME, connection=connection()).enqueue(func, *args, **kwargs)


def ping() -> str:
    """Sarcină de verificare: worker-ul primește și execută lucrări."""
    return "pong"


def main() -> None:
    Worker([QUEUE_NAME], connection=connection()).work(with_scheduler=True)


if __name__ == "__main__":
    main()
