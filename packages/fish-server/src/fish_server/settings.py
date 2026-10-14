"""Server settings read from the environment (T2.1 subtasks 9 and 13).

Nothing secret is ever written in the repository. Locally the values come from ``.env``
(copied from ``.env.example``); on Render, from the database link in ``render.yaml``.
"""

import os

DATABASE_URL_VAR = "FISH_DATABASE_URL"

_DRIVER_PREFIX = "postgresql+psycopg://"
_PLAIN_PREFIXES = ("postgresql://", "postgres://")


def normalize_database_url(url: str) -> str:
    """Make a PostgreSQL URL use the psycopg 3 driver.

    Hosting platforms (Render included) hand out plain ``postgresql://`` URLs. SQLAlchemy
    would read those as "use the psycopg2 driver", which is not installed, so the scheme is
    rewritten. URLs that already name a driver are returned unchanged.
    """
    url = url.strip()
    for prefix in _PLAIN_PREFIXES:
        if url.startswith(prefix):
            return _DRIVER_PREFIX + url.removeprefix(prefix)
    return url


def database_url() -> str:
    """Return the SQLAlchemy URL of the server's database.

    Raises RuntimeError with instructions if it is not set, rather than falling back to a
    default that could point somewhere unexpected.
    """
    url = os.environ.get(DATABASE_URL_VAR, "").strip()
    if not url:
        raise RuntimeError(
            f"{DATABASE_URL_VAR} is not set. Copy .env.example to .env and run commands "
            "with `uv run --env-file .env ...`."
        )
    return normalize_database_url(url)
