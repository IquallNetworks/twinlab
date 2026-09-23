"""A headless walk of the OIDC browser flow against the test provider, Dex.

A deliberate deviation from client-only, in the spirit of the SSH-jump slices:
the flow's contract IS a browser navigation through the provider's own login
form, which the headless `twinlab-client` has no method for (by design — see
`docs/oidc.md`). So this plays the browser: it follows redirects with a cookie
jar, fills Dex's local-password form, and stops at Twinlab's callback answer.
"""

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2

# The test provider's name at Twinlab: Dex's static client registers the
# callback for exactly this name (oidc-test/compose.yaml).
PROVIDER = "dex"
DEX_CLIENT_ID = "twinlab"
DEX_CLIENT_SECRET = "twinlab-test-secret"
# Dex's example hash, shared by every static user (oidc-test/compose.yaml).
DEX_PASSWORD = "password"

_FORM_ACTION = re.compile(r'<form[^>]*action="([^"]+)"')
_MAX_HOPS = 12


@dataclass(frozen=True, slots=True)
class Outcome:
    """Where Twinlab's callback sent the browser, and the jar it holds."""

    location: str
    browser: httpx2.AsyncClient

    @property
    def error(self) -> str | None:
        return parse_qs(urlsplit(self.location).query).get("oidc_error", [None])[0]

    @property
    def signed_in(self) -> bool:
        return self.error is None


def _absolute(response: httpx2.Response) -> str:
    return str(response.url.join(response.headers["location"]))


async def sign_in(base_url: str, email: str, *, next_path: str = "/labs") -> Outcome:
    """Run the whole flow as a browser for the Dex user `email`. The caller
    owns (and closes) `Outcome.browser`, whose jar carries the session cookie
    after a successful sign-in."""
    browser = httpx2.AsyncClient(follow_redirects=False)
    response = await browser.get(
        f"{base_url}/api/v1/auth/oidc/{PROVIDER}/login", params={"next": next_path}
    )
    login_form: httpx2.Response | None = None
    for _ in range(_MAX_HOPS):
        if response.status_code not in (302, 303):
            login_form = response
            break
        url = _absolute(response)
        if url.startswith(base_url) and "/auth/oidc/" not in url:
            # Twinlab sent the browser somewhere of its own without a callback
            # (a refusal at /login, before the provider was ever reached).
            return Outcome(location=response.headers["location"], browser=browser)
        response = await browser.get(url)
        if f"/auth/oidc/{PROVIDER}/callback" in url:
            return Outcome(location=response.headers["location"], browser=browser)
    assert login_form is not None, "never reached Dex's login form"
    action = _FORM_ACTION.search(login_form.text)
    assert action is not None, f"no login form at {login_form.url}"
    response = await browser.post(
        str(login_form.url.join(html.unescape(action.group(1)))),
        data={"login": email, "password": DEX_PASSWORD},
    )
    for _ in range(_MAX_HOPS):
        assert response.status_code in (302, 303), f"Dex answered {response.status_code}"
        url = _absolute(response)
        response = await browser.get(url)
        if f"/auth/oidc/{PROVIDER}/callback" in url:
            return Outcome(location=response.headers["location"], browser=browser)
    raise AssertionError("never reached Twinlab's callback")
