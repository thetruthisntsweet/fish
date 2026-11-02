"""The Render Blueprint (render.yaml; T4.1, docs/runbooks/domains.md): every web service has
one address of its own, its `onrender.com` address switched off, and sign-in links pointing
at that address over HTTPS, so a session never belongs to an address people do not use."""

from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import pytest
import yaml

BLUEPRINT: Final = Path(__file__).resolve().parents[3] / "render.yaml"


def web_services() -> list[dict[str, Any]]:
    blueprint: dict[str, Any] = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    return [s for s in blueprint["services"] if s["type"] == "web"]


@pytest.mark.parametrize("service", web_services(), ids=lambda s: s["name"])
def test_sign_in_links_point_at_the_services_own_address(service: dict[str, Any]) -> None:
    env = {v["key"]: v.get("value") for v in service["envVars"]}
    link = urlsplit(env["FISH_PUBLIC_URL"])
    assert link.scheme == "https"
    assert (link.path, link.query) == ("", "")
    assert service["domains"] == [link.hostname]
    assert service["renderSubdomainPolicy"] == "disabled"
