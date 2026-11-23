"""
E2E Test: the Vue SPA's student-facing forms, in a real browser.

Covers what the vitest component tests cannot: that the baked production
bundle is actually served, that Caddy's routing and deep-link fallback
work, that the real Flask endpoints answer the shapes the SPA expects, and
that the browser's own clipboard and download machinery do what the
components assume.

The SPA is reached through `ref_instance.web_url`, which is the published
port of the Caddy `frontend-proxy`. That serves the bundle built by
`./ctrl.sh build` — the real artifact — not a dev server.

This module needs no exercise and no SSH, so it is the cheap one: one
stack, no image build.

Ordered `test_NN_` classes share `spa_page`, which is module-scoped so the
session cookie and the `localStorage` theme preference survive between
steps. Per the collection guard in tests/conftest.py, run the file whole —
a `::` selector aborts the run by design.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
from pathlib import Path
from typing import Any, Dict, Generator

import pytest
from playwright.sync_api import Page, expect

from helpers.method_exec import set_system_setting
from helpers.ssh_keys import generate_ed25519_keypair

PASSWORD = "SpaFormsTest123!"

# Generated once per module so a rerun against a fresh instance cannot
# collide with a leftover account.
STATE: Dict[str, Any] = {}


def _mat_num() -> str:
    """A matriculation number no other test will use."""
    return str(uuid.uuid4().int)[:8]


@pytest.fixture(scope="module", autouse=True)
def spa_module_state() -> Generator[None, None, None]:
    STATE.clear()
    STATE["mat_num"] = _mat_num()
    STATE["own_key_mat_num"] = _mat_num()
    STATE["own_keypair"] = generate_ed25519_keypair("own-key-student")
    yield
    STATE.clear()


def _goto(page: Page, path: str) -> None:
    """Navigate and wait for the SPA to have rendered something."""
    page.goto(path, wait_until="networkidle")


def _field(page: Page, test_id: str) -> Any:
    """
    A Vuetify text field's inner <input>.

    The `data-test` attribute lands on the field wrapper, not the input, so
    every value assertion has to descend one level.
    """
    return page.locator(f'[data-test="{test_id}"] input')


class Test00AppBoot:
    """The bundle loads, routes, and is reachable where Caddy says."""

    def test_00_root_redirects_to_register(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/")

        expect(spa_page).to_have_url(re.compile(r"/spa/register$"))
        expect(spa_page.locator('[data-test="register-form"]')).to_be_visible()

    def test_01_admin_shortcut_leaves_the_spa(self, spa_page: Page) -> None:
        # /admin is server-rendered Jinja; the button is a plain anchor
        # precisely so the click leaves the SPA. An anonymous visitor is
        # then bounced to the Flask login page, with `next` carrying the
        # admin target — so the landing URL is /login, not /admin.
        _goto(spa_page, "/spa/register")

        spa_page.click('a[href="/admin"]')
        spa_page.wait_for_load_state("networkidle")

        assert "/spa/" not in spa_page.url, "the click did not leave the SPA"
        parsed = urlsplit(spa_page.url)
        assert parsed.path == "/login"
        assert "/admin" in unquote(parse_qs(parsed.query).get("next", [""])[0])
        # A server-rendered form, not the SPA's Vuetify one.
        expect(spa_page.locator('form input[name="password"]')).to_be_visible()

    def test_02_nav_offers_the_enabled_pages_only(self, spa_page: Page) -> None:
        # The scoreboard is disabled by default, and the nav store hides
        # the tab on any error from /api/scoreboard/config.
        _goto(spa_page, "/spa/register")

        tabs = spa_page.locator(".term-nav-center .term-tab")
        labels = [t.strip() for t in tabs.all_inner_texts()]

        assert "REGISTER" in labels
        assert "RESTORE KEY" in labels
        assert "SCOREBOARD" not in labels

    def test_03_restore_key_tab_navigates_client_side(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        spa_page.click('.term-nav-center .term-tab:has-text("RESTORE KEY")')

        expect(spa_page).to_have_url(re.compile(r"/spa/restore-key$"))
        expect(spa_page.locator('[data-test="restore-form"]')).to_be_visible()

    def test_04_deep_link_is_served_by_caddy(self, spa_page: Page) -> None:
        # Caddy falls /spa/* back to index.html, so a deep link works on a
        # cold load rather than only via client-side navigation.
        response = spa_page.goto("/spa/restore-key", wait_until="networkidle")

        assert response is not None
        assert response.status == 200
        expect(spa_page.locator('[data-test="restore-form"]')).to_be_visible()

    def test_05_unknown_spa_path_renders_the_shell_and_no_page(
        self, spa_page: Page
    ) -> None:
        # There is no catch-all route, so Caddy serves index.html and
        # <router-view> matches nothing. The chrome is still there, which
        # is what tells a 404-in-the-SPA apart from a 404 from the server.
        response = spa_page.goto("/spa/no-such-page", wait_until="networkidle")

        assert response is not None
        assert response.status == 200
        expect(spa_page.locator(".term-nav-center")).to_be_visible()
        expect(spa_page.locator('[data-test="register-form"]')).to_have_count(0)
        expect(spa_page.locator('[data-test="restore-form"]')).to_have_count(0)

    def test_06_course_name_reaches_the_header(
        self, spa_page: Page, ref_instance: Any
    ) -> None:
        course = f"SPA-Forms-{uuid.uuid4().hex[:4]}"
        set_system_setting(ref_instance, "COURSE_NAME", course)

        _goto(spa_page, "/spa/register")

        expect(spa_page.locator(".term-appbar-title")).to_contain_text(course)
        # The nav store feeds the same value into the document title.
        assert course in spa_page.title()

    def test_07_dev_banner_is_absent_from_the_production_bundle(
        self, spa_page: Page
    ) -> None:
        # The banner warns that `vite dev` is serving the app. A
        # `vite build` tree-shakes it out, so seeing it here would mean the
        # image was built in hot-reloading mode.
        _goto(spa_page, "/spa/register")

        expect(spa_page.locator(".dev-banner")).to_have_count(0)


class Test10Theme:
    """The theme cycle and its persistence across a reload."""

    THEME_BUTTON = 'button[aria-label^="Theme:"]'

    def test_00_starts_on_auto(self, spa_page: Page) -> None:
        spa_page.context.clear_cookies()
        _goto(spa_page, "/spa/register")
        spa_page.evaluate("() => localStorage.removeItem('refTheme')")
        spa_page.reload(wait_until="networkidle")

        expect(spa_page.locator(self.THEME_BUTTON)).to_have_attribute(
            "aria-label", re.compile("auto")
        )

    def test_01_cycles_auto_light_dark(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        spa_page.click(self.THEME_BUTTON)
        expect(spa_page.locator(self.THEME_BUTTON)).to_have_attribute(
            "aria-label", re.compile("light")
        )
        expect(spa_page.locator("body")).to_have_class(re.compile("theme-light"))

        spa_page.click(self.THEME_BUTTON)
        expect(spa_page.locator(self.THEME_BUTTON)).to_have_attribute(
            "aria-label", re.compile("dark")
        )
        expect(spa_page.locator("body")).to_have_class(re.compile("theme-dark"))

    def test_02_survives_a_reload(self, spa_page: Page) -> None:
        # Persisted in localStorage under refTheme, so a returning student
        # is not flashed the other palette.
        assert spa_page.evaluate("() => localStorage.getItem('refTheme')") == "dark"

        spa_page.reload(wait_until="networkidle")

        expect(spa_page.locator("body")).to_have_class(re.compile("theme-dark"))

    def test_03_cycles_back_to_auto(self, spa_page: Page) -> None:
        spa_page.click(self.THEME_BUTTON)

        expect(spa_page.locator(self.THEME_BUTTON)).to_have_attribute(
            "aria-label", re.compile("auto")
        )
        assert spa_page.evaluate("() => localStorage.getItem('refTheme')") == "auto"


class Test20Registration:
    """Registering through the browser, and the key the server hands back."""

    def test_00_form_offers_the_expected_fields(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        for test_id in (
            "register-mat-num",
            "register-firstname",
            "register-surname",
            "register-password",
            "register-password-rep",
        ):
            expect(_field(spa_page, test_id)).to_be_visible()
        expect(
            spa_page.locator('[data-test="register-pubkey"] textarea')
        ).to_be_visible()

    def test_01_server_side_field_errors_land_on_the_right_inputs(
        self, spa_page: Page
    ) -> None:
        # The SPA does no client-side validation at all; every message
        # comes from the API's error.fields map. The form-level banner is
        # suppressed when field errors are present, so the student is not
        # told the same thing twice.
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(_mat_num())
        _field(spa_page, "register-firstname").fill("Mismatch")
        _field(spa_page, "register-surname").fill("Student")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD + "different")
        spa_page.click('[data-test="register-submit"]')

        password_field = spa_page.locator('[data-test="register-password-rep"]')
        expect(password_field.locator(".v-messages__message").first).to_be_visible()
        expect(spa_page.locator('[data-test="form-error"]')).to_have_count(0)

    def test_02_weak_password_is_rejected_by_the_server(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(_mat_num())
        _field(spa_page, "register-firstname").fill("Weak")
        _field(spa_page, "register-surname").fill("Password")
        _field(spa_page, "register-password").fill("short")
        _field(spa_page, "register-password-rep").fill("short")
        spa_page.click('[data-test="register-submit"]')

        messages = spa_page.locator(
            '[data-test="register-password"] .v-messages__message'
        )
        expect(messages.first).to_be_visible()
        # Still on the form, no key card.
        expect(spa_page.locator('[data-test="pubkey-text"]')).to_have_count(0)

    def test_03_registration_generates_a_keypair(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "register-firstname").fill("Spa")
        _field(spa_page, "register-surname").fill("Student")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD)
        spa_page.click('[data-test="register-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"] textarea')).to_be_visible()
        # Server-side keypair, so the private key block is present.
        expect(spa_page.locator('[data-test="privkey-block"]')).to_be_visible()
        expect(spa_page.locator('[data-test="variant-alert"]')).to_have_count(1)
        expect(spa_page.locator('[data-test="variant-alert"]')).to_contain_text(
            "Restore Key"
        )

        pubkey = spa_page.locator('[data-test="pubkey-text"] textarea').input_value()
        privkey = spa_page.locator('[data-test="privkey-text"] textarea').input_value()
        assert pubkey.startswith("ssh-"), f"Not an SSH public key: {pubkey[:40]!r}"
        assert "PRIVATE KEY" in privkey
        STATE["pubkey"] = pubkey
        STATE["privkey"] = privkey

    def test_04_download_filename_matches_the_generated_algorithm(
        self, spa_page: Page, download_dir: Path
    ) -> None:
        # The component derives the filename from the key's own algorithm
        # prefix, so this checks the server and the SPA agree about what
        # was generated rather than hardcoding a key type.
        algo = STATE["pubkey"].split()[0]
        expected_stem = {
            "ssh-ed25519": "id_ed25519",
            "ssh-dss": "id_dsa",
        }.get(algo, "id_ecdsa" if algo.startswith("ecdsa-sha2-") else "id_rsa")

        with spa_page.expect_download() as info:
            spa_page.click('[data-test="pubkey-download"]')
        download = info.value

        assert download.suggested_filename == f"{expected_stem}.pub"
        target = download_dir / download.suggested_filename
        download.save_as(target)
        # Byte-for-byte what the textarea showed.
        assert target.read_text().strip() == STATE["pubkey"].strip()

    def test_05_private_key_downloads_under_the_matching_name(
        self, spa_page: Page, download_dir: Path
    ) -> None:
        with spa_page.expect_download() as info:
            spa_page.click('[data-test="privkey-download"]')
        download = info.value

        assert not download.suggested_filename.endswith(".pub")
        target = download_dir / "downloaded_privkey"
        download.save_as(target)
        assert "PRIVATE KEY" in target.read_text()
        STATE["downloaded_privkey"] = target.read_text()

    def test_06_copy_puts_the_key_on_the_real_clipboard(self, spa_page: Page) -> None:
        # navigator.clipboard needs a permission grant even on localhost.
        spa_page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=spa_page.url
        )

        spa_page.click('[data-test="pubkey-copy"]')

        expect(spa_page.locator('[data-test="pubkey-copy"]')).to_contain_text("Copied")
        clipboard = spa_page.evaluate("() => navigator.clipboard.readText()")
        assert clipboard.strip() == STATE["pubkey"].strip()

    def test_07_duplicate_mat_num_is_refused(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "register-firstname").fill("Duplicate")
        _field(spa_page, "register-surname").fill("Student")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD)
        spa_page.click('[data-test="register-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"]')).to_have_count(0)
        # Either a field message or the form banner, depending on how the
        # API attributes it; one of them has to appear.
        shown = spa_page.locator(
            '[data-test="form-error"], [data-test="register-mat-num"] .v-messages__message'
        )
        expect(shown.first).to_be_visible()

    def test_08_reusing_an_existing_key_is_refused(self, spa_page: Page) -> None:
        # A public key identifies one account, so offering one that is
        # already registered has to be rejected rather than silently
        # giving two students the same credential.
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(_mat_num())
        _field(spa_page, "register-firstname").fill("Reused")
        _field(spa_page, "register-surname").fill("Key")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD)
        spa_page.locator('[data-test="register-pubkey"] textarea').fill(STATE["pubkey"])
        spa_page.click('[data-test="register-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"]')).to_have_count(0)
        # The field always carries a hint about supported key formats, so
        # the error has to be picked out rather than matched as the only
        # message under it.
        expect(
            spa_page.locator('[data-test="register-pubkey"]').get_by_text(
                "Already registered"
            )
        ).to_be_visible()

    def test_09_supplying_your_own_key_stores_no_private_key(
        self, spa_page: Page
    ) -> None:
        _goto(spa_page, "/spa/register")

        _field(spa_page, "register-mat-num").fill(STATE["own_key_mat_num"])
        _field(spa_page, "register-firstname").fill("Own")
        _field(spa_page, "register-surname").fill("Key")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD)
        spa_page.locator('[data-test="register-pubkey"] textarea').fill(
            STATE["own_keypair"].public
        )
        spa_page.click('[data-test="register-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"] textarea')).to_be_visible()
        expect(spa_page.locator('[data-test="privkey-block"]')).to_have_count(0)
        expect(spa_page.locator('[data-test="variant-alert"]')).to_contain_text(
            "your own public key"
        )


class Test30RestoreKey:
    """Getting a stored keypair back."""

    def test_00_wrong_password_is_refused(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/restore-key")

        _field(spa_page, "restore-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "restore-password").fill("WrongPassword123!")
        spa_page.click('[data-test="restore-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"]')).to_have_count(0)
        shown = spa_page.locator(
            '[data-test="form-error"], [data-test="restore-password"] .v-messages__message'
        )
        expect(shown.first).to_be_visible()

    def test_01_unknown_mat_num_is_refused(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/restore-key")

        _field(spa_page, "restore-mat-num").fill(_mat_num())
        _field(spa_page, "restore-password").fill(PASSWORD)
        spa_page.click('[data-test="restore-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"]')).to_have_count(0)

    def test_02_returns_the_very_same_keypair(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/restore-key")

        _field(spa_page, "restore-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "restore-password").fill(PASSWORD)
        spa_page.click('[data-test="restore-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"] textarea')).to_be_visible()
        restored_pub = spa_page.locator(
            '[data-test="pubkey-text"] textarea'
        ).input_value()
        restored_priv = spa_page.locator(
            '[data-test="privkey-text"] textarea'
        ).input_value()

        assert restored_pub.strip() == STATE["pubkey"].strip()
        # Byte-for-byte the file the browser downloaded at registration.
        assert restored_priv.strip() == STATE["downloaded_privkey"].strip()

    def test_03_uses_the_restore_wording(self, spa_page: Page) -> None:
        # The same card serves both pages; only `variant` differs, and
        # getting it wrong would tell a student a key was just generated.
        expect(spa_page.locator('[data-test="variant-alert"]')).to_have_count(1)
        expect(spa_page.locator('[data-test="variant-alert"]')).to_contain_text(
            "stored keypair"
        )

    def test_04_own_key_account_gets_only_a_public_key(self, spa_page: Page) -> None:
        _goto(spa_page, "/spa/restore-key")

        _field(spa_page, "restore-mat-num").fill(STATE["own_key_mat_num"])
        _field(spa_page, "restore-password").fill(PASSWORD)
        spa_page.click('[data-test="restore-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"] textarea')).to_be_visible()
        expect(spa_page.locator('[data-test="privkey-block"]')).to_have_count(0)
        expect(spa_page.locator('[data-test="variant-alert"]')).to_contain_text(
            "Only your public key"
        )
        restored = spa_page.locator('[data-test="pubkey-text"] textarea').input_value()
        assert restored.split()[1] == STATE["own_keypair"].public.split()[1]


class Test40RegistrationDisabled:
    """
    Last, because it mutates a system setting that every earlier
    registration step depends on.
    """

    def test_00_disabled_registration_warns_and_locks_the_form(
        self, spa_page: Page, ref_instance: Any
    ) -> None:
        set_system_setting(ref_instance, "REGESTRATION_ENABLED", False)

        _goto(spa_page, "/spa/register")

        expect(spa_page.locator('[data-test="registration-disabled"]')).to_be_visible()
        # The card still renders — the warning and the card are separate
        # v-if chains — so every control has to be disabled individually.
        expect(spa_page.locator('[data-test="register-card"]')).to_be_visible()
        expect(_field(spa_page, "register-mat-num")).to_be_disabled()
        expect(spa_page.locator('[data-test="register-submit"]')).to_be_disabled()

    def test_01_nav_drops_the_register_tab(self, spa_page: Page) -> None:
        tabs = spa_page.locator(".term-nav-center .term-tab")
        labels = [t.strip() for t in tabs.all_inner_texts()]

        assert "REGISTER" not in labels
        assert "RESTORE KEY" in labels

    def test_02_restore_key_still_works(self, spa_page: Page) -> None:
        # Disabling registration must not lock out students who already
        # have an account and lost their key.
        _goto(spa_page, "/spa/restore-key")

        _field(spa_page, "restore-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "restore-password").fill(PASSWORD)
        spa_page.click('[data-test="restore-submit"]')

        expect(spa_page.locator('[data-test="pubkey-text"] textarea')).to_be_visible()

    def test_03_re_enabling_brings_the_form_back(
        self, spa_page: Page, ref_instance: Any
    ) -> None:
        set_system_setting(ref_instance, "REGESTRATION_ENABLED", True)

        _goto(spa_page, "/spa/register")

        expect(spa_page.locator('[data-test="registration-disabled"]')).to_have_count(0)
        expect(_field(spa_page, "register-mat-num")).to_be_enabled()


class Test99BrowserHealth:
    """
    One test for everything the DOM assertions above would not notice:
    Vue warnings, unhandled rejections, and failed requests for the app's
    own assets or API.
    """

    def test_99_no_console_errors_or_failed_requests(self, spa_errors: Any) -> None:
        messages = spa_errors.all_messages()

        assert not messages, "Browser reported problems:\n  " + "\n  ".join(messages)
