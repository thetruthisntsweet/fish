"""Server settings read from the environment (T2.1 subtask 9).

Nothing secret is ever written in the repository. Locally the values come from ``.env``
(copied from ``.env.example``); on staging and production, from the hosting platform's
secret store (T2.1 §10).
"""

import os

DATABASE_URL_VAR = "FISH_DATABASE_URL"


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
    return url
