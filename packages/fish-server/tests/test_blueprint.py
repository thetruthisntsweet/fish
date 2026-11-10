"""The Render Blueprint (render.yaml; T4.1, T4.3, docs/runbooks/domains.md): two
sites, each with one address of its own and its `onrender.com` address switched off, sign-in
links pointing at that address over HTTPS, its own database, and settings the server accepts.
Staging, the pilot site, deploys main; production, the study's, only the production branch that
the Deploy workflow moves."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import pytest
import yaml

from fish_server.opening import EASTERN
from fish_server.settings import (
    bot_delays,
    consent_version,
    daily_link_limit,
    tables_closed,
    terms_version,
)
from fish_server.stats import DISK_GB
from fish_server.study import BOT_DELAYS, LAUNCH, PILOT_ENDED

BLUEPRINT: Final = Path(__file__).resolve().parents[3] / "render.yaml"
SITES: Final = {"fish-staging": "fish-pilot", "fish-production": "fish"}
"""Each web service, and the first label of its address."""
SETTINGS: Final = (
    "FISH_CONSENT_VERSION",
    "FISH_TERMS_VERSION",
    "FISH_SIGNIN_DAILY_LIMIT",
    "FISH_BOT_DELAYS",
    "FISH_OPENS",
    "FISH_PILOT_ENDED",
    "FISH_TABLES_OPEN",
)
"""Settings a test clears first, so only the Blueprint's values count."""
ADDRESS_PENDING: Final[set[str]] = {"fish-production"}
"""Services whose own address is not yet verified, so whose `onrender.com` address is still on:
Render switches it off only once the custom one works. Emptied by docs/runbooks/launch.md §1
step 7, in the same change that adds `renderSubdomainPolicy: disabled`."""


def blueprint() -> dict[str, Any]:
    return yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))


def web_services() -> list[dict[str, Any]]:
    return [s for s in blueprint()["services"] if s["type"] == "web"]


def service(name: str) -> dict[str, Any]:
    return next(s for s in web_services() if s["name"] == name)


def env(svc: dict[str, Any]) -> dict[str, Any]:
    return {v["key"]: v for v in svc["envVars"]}


def values(svc: dict[str, Any]) -> dict[str, str]:
    return {k: str(v["value"]) for k, v in env(svc).items() if "value" in v}


def test_there_are_two_sites() -> None:
    assert {s["name"] for s in web_services()} == set(SITES)
    assert {d["name"] for d in blueprint()["databases"]} == {f"{n}-db" for n in SITES}


@pytest.mark.parametrize("svc", web_services(), ids=lambda s: s["name"])
def test_sign_in_links_point_at_the_services_own_address(svc: dict[str, Any]) -> None:
    link = urlsplit(values(svc)["FISH_PUBLIC_URL"])
    assert link.scheme == "https"
    assert (link.path, link.query) == ("", "")
    assert svc["domains"] == [link.hostname]
    assert link.hostname == f"{SITES[svc['name']]}.thedefinitivesanjeevexperience.com"
    if svc["name"] in ADDRESS_PENDING:
        assert "renderSubdomainPolicy" not in svc
    else:
        assert svc["renderSubdomainPolicy"] == "disabled"


@pytest.mark.parametrize("svc", web_services(), ids=lambda s: s["name"])
def test_each_site_has_its_own_database_and_secrets(svc: dict[str, Any]) -> None:
    variables = env(svc)
    database = variables["FISH_ADMIN_DATABASE_URL"]["fromDatabase"]
    assert database == {"name": f"{svc['name']}-db", "property": "connectionString"}
    assert variables["FISH_APP_DB_PASSWORD"] == {
        "key": "FISH_APP_DB_PASSWORD",
        "generateValue": True,
    }
    for secret in ("FISH_RESEND_API_KEY", "FISH_COHORT_SEED"):  # set by hand, never in the file
        assert variables[secret] == {"key": secret, "sync": False}
    assert svc["preDeployCommand"] == "python -m fish_server.deploy"
    assert svc["autoDeployTrigger"] == "checksPass"


def test_staging_deploys_main_and_production_only_its_branch() -> None:
    assert service("fish-staging")["branch"] == "main"
    assert service("fish-production")["branch"] == "production"


@pytest.mark.parametrize(
    ("name", "consent", "terms", "limit", "delays"),
    [
        ("fish-staging", "v1.0-pilot", "v1.0-pilot", 90, "uniform-1.5-4s-v1"),
        ("fish-production", "v1.0", "v1.0", 1_500, BOT_DELAYS),
    ],
)
def test_the_server_reads_each_sites_settings_as_meant(
    monkeypatch: pytest.MonkeyPatch, name: str, consent: str, terms: str, limit: int, delays: str
) -> None:
    for key in SETTINGS:
        monkeypatch.delenv(key, raising=False)
    for key, value in values(service(name)).items():
        monkeypatch.setenv(key, value)
    assert (consent_version(), terms_version(), daily_link_limit()) == (consent, terms, limit)
    assert bot_delays().version == delays


def test_the_databases_are_alike_but_the_studys_has_room() -> None:
    staging, production = (
        next(d for d in blueprint()["databases"] if d["name"] == f"{n}-db") for n in SITES
    )
    for key in ("region", "postgresMajorVersion", "databaseName", "user", "ipAllowList"):
        assert staging[key] == production[key]
    assert production["diskSizeGB"] >= 2  # about 0.6 GB for 1,000 games
    assert (staging["diskSizeGB"], production["diskSizeGB"]) == (
        DISK_GB["pilot"],
        DISK_GB["study"],
    )  # what fish_server.stats measures against


def test_only_production_may_wait_for_its_address() -> None:
    assert set(SITES) >= ADDRESS_PENDING
    assert "fish-staging" not in ADDRESS_PENDING


@pytest.mark.parametrize(
    ("name", "first_open", "last_open"),
    [
        ("fish-staging", None, datetime(2026, 12, 6, 4, 59, 59, tzinfo=UTC)),  # Sat 5 Dec, Eastern
        ("fish-production", datetime(2026, 12, 8, 5, tzinfo=UTC), None),  # Tue 8 Dec, Eastern
    ],
)
def test_each_site_takes_tables_only_on_its_days(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    first_open: datetime | None,
    last_open: datetime | None,
) -> None:
    """The pilot site until its last night, the study's from the day it opens (T4.3): the day
    the server reads from the Blueprint is the study's own launch day."""
    for key in SETTINGS:
        monkeypatch.delenv(key, raising=False)
    for key, value in values(service(name)).items():
        monkeypatch.setenv(key, value)
    assert "FISH_TABLES_OPEN" not in values(service(name))  # only ever set by hand, briefly
    days = {
        "fish-staging": ("FISH_PILOT_ENDED", PILOT_ENDED),
        "fish-production": ("FISH_OPENS", LAUNCH),
    }
    key, day = days[name]
    assert values(service(name))[key] == day.isoformat()  # what try_server checks against
    second = timedelta(seconds=1)
    if first_open is not None:
        assert first_open.astimezone(EASTERN).date() == LAUNCH
        assert tables_closed(first_open - second) is not None
        assert tables_closed(first_open) is None
    if last_open is not None:
        assert tables_closed(last_open) is None
        assert tables_closed(last_open + second) is not None
