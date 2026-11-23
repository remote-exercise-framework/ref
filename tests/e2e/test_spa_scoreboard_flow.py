"""
E2E Test: the whole student journey, browser to container and back.

This is the one test that crosses every layer in a single flow:

    register in a real browser
      -> download the generated private key from the SPA
      -> SSH into the exercise container with that key
      -> write a solution and run `task submit`
      -> see the score appear on the SPA's scoreboard

Nothing else in the suite connects those ends. The Python e2e tests reach
the API and SSH but never the rendered page; the vitest suite renders the
page but mocks the API. A break anywhere along the chain — a renamed JSON
field, a key the SSH proxy will not accept, a scoring policy that zeroes
everything out — shows up here and only here.

The exercise is `create_multi_task_exercise`, whose two tasks return
numeric scores. That matters: a bool-returning task stores `score=None`,
which contributes 0, and the SPA's `getRanking` drops any team totalling
0 — so a single-task exercise can never reach the scoreboard at all.

Ordering is deliberate. Scores are asserted in Python before any browser
assertion, so a zero score fails as "the submission did not score" rather
than as a missing table row. Steps that mutate shared state come last.

Per the collection guard in tests/conftest.py, run the file whole — a
`::` selector aborts the run by design.
"""

from __future__ import annotations

import os
import re
import stat
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest
from playwright.sync_api import Page, expect

from helpers.exercise_factory import (
    MULTI_TASK_CORRECTNESS_MAX,
    MULTI_TASK_DATA,
    MULTI_TASK_PARTIAL_CORRECTNESS,
    MULTI_TASK_PARTIAL_SOLUTION,
    MULTI_TASK_SOLUTION,
    MULTI_TASK_TASK_NAMES,
    create_multi_task_exercise,
    unique_short_name,
)
from helpers.method_exec import enable_exercise, set_system_setting
from helpers.web_client import REFWebClient

PASSWORD = "ScoreboardFlow123!"
CATEGORY = "Assignment 1"
# The config form refuses a deadline without grading points, so the same
# value the exercise was created with has to be resent on every POST.
GRADING_POINTS = 10
SOLUTION_PATH = "/home/user/solution.py"
DATA_PATH = "/home/user/data.txt"

# `correctness` maps straight through, so the scoreboard shows the raw
# score; `performance` only pays out once every row is handled. Together
# they prove both that a policy is applied and that a partial solution can
# be improved on.
PERFORMANCE_THRESHOLD_POINTS = 20.0
POLICIES: Dict[str, Dict[str, Any]] = {
    "correctness": {
        "mode": "linear",
        "max_points": MULTI_TASK_CORRECTNESS_MAX,
        "min_raw": 0,
        "max_raw": MULTI_TASK_CORRECTNESS_MAX,
    },
    "performance": {
        "mode": "threshold",
        "threshold": 40,
        "points": PERFORMANCE_THRESHOLD_POINTS,
    },
}

# The SPA polls every POLL_INTERVAL_MS (5s) in Scoreboard.vue. Waiting a
# generous multiple of that keeps the assertion about the poll happening
# rather than about how fast this box is.
POLL_WAIT_MS = 20_000

STATE: Dict[str, Any] = {}


@pytest.fixture(scope="module")
def multi_task_exercise(
    admin_client: REFWebClient,
    ref_instance: Any,
    exercises_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Dict[str, Any], None, None]:
    """
    Build the scoring exercise and configure it for the scoreboard.

    Order is forced by the webapp: scoring policies are only validated
    against tasks discovered from the built exercise, so the config POST
    has to come after the build and after the exercise is the default.
    """
    short_name = unique_short_name("scoreboard_flow")
    exercise_dir = exercises_path / short_name
    create_multi_task_exercise(
        exercise_dir, short_name, category=CATEGORY, grading_points=GRADING_POINTS
    )

    assert admin_client.import_exercise(short_name), f"import failed: {short_name}"
    exercise = admin_client.get_exercise_by_name(short_name)
    assert exercise is not None, f"not found after import: {short_name}"
    exercise_id = exercise["id"]

    assert admin_client.build_exercise(exercise_id), "build request rejected"
    assert admin_client.wait_for_build(exercise_id, timeout=600.0), "build timed out"
    # enable_exercise(), not toggle_exercise_default(): a successful import
    # already makes the first version the default, so toggling turns it
    # back off and every SSH login then fails with "Requested task not
    # found". The helper sets the flag rather than flipping it.
    assert enable_exercise(ref_instance, exercise_id), "could not make default"

    # Deadlines in the config form are rendered and parsed in the
    # configured timezone, so pin it before posting rather than
    # compensating for an offset afterwards.
    set_system_setting(ref_instance, "TIMEZONE", "UTC")

    # The scoreboard needs a category and both deadline bounds, and the
    # window has to already be open or /submissions drops the submission.
    #
    # The deadlines have to be resent even though the import already set
    # them: the config form writes every field it owns, so posting without
    # them clears the columns and the challenge then vanishes from
    # /api/scoreboard/config. Grading points come along because the form
    # rejects a deadline that has none.
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    ok, errors = admin_client.set_exercise_config(
        short_name,
        category=CATEGORY,
        deadline_start=now - timedelta(days=1),
        deadline_end=now + timedelta(days=30),
        max_grading_points=GRADING_POINTS,
        per_task_scoring_policies=POLICIES,
    )
    assert ok, f"config rejected: {errors}"

    yield {"short_name": short_name, "exercise_id": exercise_id}


@pytest.fixture(scope="module", autouse=True)
def flow_state(multi_task_exercise: Dict[str, Any]) -> Generator[None, None, None]:
    STATE.clear()
    STATE["short_name"] = multi_task_exercise["short_name"]
    STATE["exercise_id"] = multi_task_exercise["exercise_id"]
    STATE["mat_num"] = str(uuid.uuid4().int)[:8]
    yield
    STATE.clear()


def _field(page: Page, test_id: str) -> Any:
    """A Vuetify text field's inner <input>."""
    return page.locator(f'[data-test="{test_id}"] input')


def _overall_row(page: Page, team: str) -> Any:
    """
    A team's row in the overall ranking table.

    Scoped, because the page renders three RankingTable instances — one
    overall, one per assignment, one per challenge — and they all carry the
    same `data-test` markers.
    """
    return (
        page.locator('[data-test="overall-section"]')
        .locator('[data-test="ranking-row"]')
        .filter(has_text=team)
    )


def _api_json(page: Page, path: str) -> Any:
    """
    Fetch a JSON endpoint from inside the page.

    In-browser rather than with `requests` so the call carries the same
    cookies and origin the SPA itself uses — a 403 that only an anonymous
    client sees would otherwise go unnoticed.
    """
    return page.evaluate(
        "async (p) => { const r = await fetch(p); "
        "return { status: r.status, body: r.ok ? await r.json() : null }; }",
        path,
    )


class Test00RegisterInBrowser:
    """Get an account and a usable private key out of the SPA."""

    def test_00_register(self, spa_page: Page) -> None:
        spa_page.goto("/spa/register", wait_until="networkidle")

        _field(spa_page, "register-mat-num").fill(STATE["mat_num"])
        _field(spa_page, "register-firstname").fill("Score")
        _field(spa_page, "register-surname").fill("Board")
        _field(spa_page, "register-password").fill(PASSWORD)
        _field(spa_page, "register-password-rep").fill(PASSWORD)
        spa_page.click('[data-test="register-submit"]')

        expect(spa_page.locator('[data-test="privkey-block"]')).to_be_visible()
        STATE["team"] = "Score Board"

    def test_01_download_the_private_key(
        self, spa_page: Page, download_dir: Path
    ) -> None:
        with spa_page.expect_download() as info:
            spa_page.click('[data-test="privkey-download"]')
        download = info.value

        key_path = download_dir / "student_key"
        download.save_as(key_path)
        # OpenSSH refuses a world-readable private key.
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

        content = key_path.read_text()
        assert "PRIVATE KEY" in content
        STATE["privkey"] = content
        STATE["privkey_path"] = key_path


@pytest.fixture(scope="module")
def student_ssh(ssh_host: str, ssh_port: int) -> Generator[Any, None, None]:
    """
    One SSH session for the whole module.

    Not `ssh_client_factory`: that fixture is function-scoped and closes
    every client it handed out when the test ends, so a connection stashed
    in STATE is already dead by the next step. The session has to outlive a
    single test here, because writing a solution, checking it and
    submitting it are separate steps against the same container.

    Connects lazily, since the key only exists once the browser has
    registered and downloaded it.
    """
    from helpers.ssh_client import REFSSHClient

    client = REFSSHClient(ssh_host, ssh_port)
    client.connect(STATE["privkey"], STATE["short_name"])
    yield client
    client.close()


class Test10SubmitOverSsh:
    """
    The key the browser downloaded has to actually open an SSH session —
    that is the join between the web layer and the container layer.
    """

    def test_00_connect_with_the_downloaded_key(self, student_ssh: Any) -> None:
        assert student_ssh.is_connected()

    def test_01_task_check_reports_both_tasks(self, student_ssh: Any) -> None:
        client = student_ssh
        client.write_file(SOLUTION_PATH, MULTI_TASK_PARTIAL_SOLUTION, mode=0o755)
        client.write_file(DATA_PATH, MULTI_TASK_DATA)

        _, output = client.check(timeout=120.0)

        # Not asserted to succeed: the partial solution is meant to miss
        # `performance` entirely, so an overall pass here would mean the
        # tasks are not being scored independently. What has to hold is
        # that both ran and were reported separately.
        for task in MULTI_TASK_TASK_NAMES:
            assert task in output, f"{task!r} missing from check output:\n{output}"
        assert "Task failed" in output, f"performance should have failed:\n{output}"
        STATE["check_output"] = output

    def test_01b_check_does_less_work_than_submit(self) -> None:
        # The template calls rf.test_result_will_be_submitted() to run a
        # short prefix of the cases under `task check`. Nothing else in the
        # suite covers that distinction.
        output = STATE["check_output"]

        assert "Quick check" in output, f"no quick-check path taken:\n{output}"

    def test_02_a_missing_data_file_fails_only_its_own_task(
        self, student_ssh: Any
    ) -> None:
        # `performance`'s environment test requires data.txt; `correctness`
        # does not. Removing it has to break one task and leave the other
        # alone, or the tasks are not really independent.
        client = student_ssh
        client.execute(f"rm -f {DATA_PATH}")

        _, output = client.check(timeout=120.0)

        assert "performance" in output
        client.write_file(DATA_PATH, MULTI_TASK_DATA)

    def test_03_submit_the_partial_solution(self, student_ssh: Any) -> None:
        client = student_ssh

        ok, output = client.submit(timeout=180.0)

        assert ok, f"task submit failed:\n{output}"


class Test20ScoresExistInPython:
    """
    Confirm the submission scored before touching the browser. If it
    scored 0, `getRanking` filters the team out and every later DOM
    assertion would fail for a reason that has nothing to do with the SPA.
    """

    def test_00_scoreboard_is_404_while_disabled(
        self, admin_client: REFWebClient
    ) -> None:
        for path in (
            "/api/scoreboard/config",
            "/api/scoreboard/submissions",
            "/api/scoreboard/submissions/admin",
        ):
            response = admin_client.client.get(path)
            assert response.status_code == 404, (
                f"{path} answered {response.status_code} with the scoreboard off"
            )

    def test_01_enable_the_scoreboard(self, ref_instance: Any) -> None:
        set_system_setting(ref_instance, "SCOREBOARD_ENABLED", True)

        response = REFWebClient(ref_instance.web_url).client.get(
            "/api/scoreboard/config"
        )
        assert response.status_code == 200
        STATE["config"] = response.json()

    def test_02_config_lists_the_challenge_with_its_policies(self) -> None:
        assignments = STATE["config"]["assignments"]
        assert CATEGORY in assignments, f"categories: {list(assignments)}"

        challenge = assignments[CATEGORY][STATE["short_name"]]
        assert challenge["per_task_scoring_policies"] == POLICIES
        assert challenge["start"] and challenge["end"]
        # max_points is the sum of what the policies can pay out.
        expected_max = MULTI_TASK_CORRECTNESS_MAX + PERFORMANCE_THRESHOLD_POINTS
        assert challenge["max_points"] == pytest.approx(expected_max)

    def test_03_the_partial_submission_scored_above_zero(
        self, ref_instance: Any
    ) -> None:
        response = REFWebClient(ref_instance.web_url).client.get(
            "/api/scoreboard/submissions"
        )
        assert response.status_code == 200
        board = response.json()

        assert STATE["short_name"] in board, f"challenges: {list(board)}"
        teams = board[STATE["short_name"]]
        assert STATE["team"] in teams, f"teams: {list(teams)}"

        entries = teams[STATE["team"]]
        assert len(entries) == 1
        entry = entries[0]

        # Four of five correctness cases pass, mapped 1:1 by the linear
        # policy; performance misses its threshold entirely.
        assert entry["tasks"]["correctness"] == pytest.approx(
            MULTI_TASK_PARTIAL_CORRECTNESS
        )
        assert entry["tasks"]["performance"] == pytest.approx(0.0)
        assert entry["score"] == pytest.approx(MULTI_TASK_PARTIAL_CORRECTNESS)
        assert entry["score"] > 0, "nothing would reach the scoreboard"
        STATE["partial_score"] = entry["score"]


class Test30ScoreboardInBrowser:
    """The board as a student sees it."""

    def test_00_nav_gains_the_scoreboard_tab(self, spa_page: Page) -> None:
        # The nav store refetches on load, so this also proves the tab was
        # hidden purely because the endpoint was 404ing before.
        spa_page.goto("/spa/register", wait_until="networkidle")

        tabs = spa_page.locator(".term-nav-center .term-tab")
        labels = [t.strip() for t in tabs.all_inner_texts()]
        assert "SCOREBOARD" in labels, f"nav shows {labels}"

    def test_01_board_renders_rather_than_the_disabled_notice(
        self, spa_page: Page
    ) -> None:
        spa_page.click('.term-nav-center .term-tab:has-text("SCOREBOARD")')

        expect(spa_page.locator('[data-test="scoreboard-board"]')).to_be_visible()
        expect(spa_page.locator('[data-test="scoreboard-disabled"]')).to_have_count(0)
        expect(spa_page.locator('[data-test="scoreboard-error"]')).to_have_count(0)

    def test_02_assignment_and_challenge_tabs_name_the_exercise(
        self, spa_page: Page
    ) -> None:
        assignment_tab = spa_page.locator(f'[data-test="assignment-tab-{CATEGORY}"]')
        expect(assignment_tab).to_be_visible()
        expect(assignment_tab).not_to_have_class(re.compile("is-disabled"))

        challenge_tab = spa_page.locator(
            f'[data-test="challenge-tab-{STATE["short_name"]}"]'
        )
        expect(challenge_tab).to_be_visible()

    def test_03_the_team_row_shows_the_score_from_the_api(self, spa_page: Page) -> None:
        # The team label comes from team_identity() server-side, so it is
        # read back from the API rather than guessed here.
        result = _api_json(spa_page, "/api/scoreboard/submissions")
        assert result["status"] == 200
        teams = result["body"][STATE["short_name"]]
        team_label = next(iter(teams))

        # Three ranking tables render — overall, per-assignment and
        # per-challenge — so every row assertion is scoped to one of them.
        overall = spa_page.locator('[data-test="overall-section"]')
        expect(overall.locator('[data-test="ranking-table"]')).to_be_visible()
        expect(overall.locator('[data-test="ranking-empty"]')).to_have_count(0)

        row = _overall_row(spa_page, team_label)
        expect(row).to_have_count(1)
        # RankingTable renders points with two decimals.
        expect(row).to_contain_text(f"{STATE['partial_score']:.2f}")

        # With one challenge, the per-challenge table has to agree.
        challenge_row = (
            spa_page.locator('[data-test="challenge-section"]')
            .locator('[data-test="ranking-row"]')
            .filter(has_text=team_label)
        )
        expect(challenge_row).to_contain_text(f"{STATE['partial_score']:.2f}")

    def test_04_the_charts_render_a_real_canvas(self, spa_page: Page) -> None:
        # ECharts in a real browser, which jsdom cannot do at all: the
        # vitest suite mocks the chart modules away entirely.
        canvases = spa_page.locator("canvas")
        expect(canvases.first).to_be_visible()

        box = canvases.first.bounding_box()
        assert box is not None
        assert box["width"] > 0 and box["height"] > 0, f"empty canvas: {box}"

    def test_05_an_anonymous_visitor_has_no_admin_toggle(self, spa_page: Page) -> None:
        expect(spa_page.locator('[data-test="admin-toggle"]')).to_have_count(0)

        # And the admin endpoint it would drive is closed to them.
        result = _api_json(spa_page, "/api/scoreboard/submissions/admin")
        assert result["status"] == 403


class Test40ImprovedSubmissionUpdatesLive:
    """
    A better solution has to raise the row without a page reload — that is
    the 5-second poll in Scoreboard.vue, which no unit test can prove
    against a real server.
    """

    def test_00_submit_the_full_solution(self, student_ssh: Any) -> None:
        client = student_ssh
        client.write_file(SOLUTION_PATH, MULTI_TASK_SOLUTION, mode=0o755)

        ok, output = client.submit(timeout=180.0)

        assert ok, f"task submit failed:\n{output}"

    def test_01_the_full_solution_scores_higher(self, ref_instance: Any) -> None:
        response = REFWebClient(ref_instance.web_url).client.get(
            "/api/scoreboard/submissions"
        )
        entries = response.json()[STATE["short_name"]][STATE["team"]]

        assert len(entries) == 2, f"expected two submissions, got {len(entries)}"
        best = max(e["score"] for e in entries)

        # Full correctness, and performance now clears its threshold.
        expected = MULTI_TASK_CORRECTNESS_MAX + PERFORMANCE_THRESHOLD_POINTS
        assert best == pytest.approx(expected)
        assert best > STATE["partial_score"]
        STATE["best_score"] = best

    def test_02_the_open_page_updates_without_a_reload(self, spa_page: Page) -> None:
        # No goto and no reload: the page has been sitting on the
        # scoreboard since Test30, so only the poll can change it.
        row = _overall_row(spa_page, STATE["team"])

        expect(row).to_contain_text(f"{STATE['best_score']:.2f}", timeout=POLL_WAIT_MS)


class Test50AdminView:
    """
    The admin toggle, and the fact that an admin's own submissions are
    hidden from the public board.
    """

    def test_00_admin_submissions_are_separated(
        self, admin_client: REFWebClient
    ) -> None:
        public = admin_client.client.get("/api/scoreboard/submissions").json()
        admin = admin_client.client.get("/api/scoreboard/submissions/admin").json()

        # The student's work is in both; the admin endpoint is a superset.
        assert STATE["team"] in public[STATE["short_name"]]
        assert STATE["team"] in admin[STATE["short_name"]]
        for challenge, teams in public.items():
            for team in teams:
                assert team in admin.get(challenge, {}), (
                    f"{team!r} on the public board but not the admin one"
                )

    def test_01_a_logged_in_admin_sees_the_toggle(
        self, spa_page: Page, admin_password: str
    ) -> None:
        # Logging in happens through the browser's own context, so the
        # Python client fixtures — which are one shared object — keep
        # their session either way.
        spa_page.goto("/login", wait_until="networkidle")
        spa_page.fill('input[name="username"]', "0")
        spa_page.fill('input[name="password"]', admin_password)
        spa_page.click('form input[type="submit"], form button[type="submit"]')
        spa_page.wait_for_load_state("networkidle")
        assert "/login" not in spa_page.url, "admin login was rejected"

        spa_page.goto("/spa/scoreboard", wait_until="networkidle")

        expect(spa_page.locator('[data-test="admin-toggle"]')).to_be_visible()

    def test_02_the_toggle_switches_the_data_source(self, spa_page: Page) -> None:
        requested: List[str] = []
        spa_page.on(
            "request",
            lambda r: requested.append(r.url) if "/api/scoreboard/" in r.url else None,
        )

        toggle = spa_page.locator('[data-test="admin-toggle"]')
        # A plain anchor whose text is the current state, not a checkbox.
        expect(toggle).to_have_text("[ user view ]")
        toggle.click()
        expect(toggle).to_have_text("[ admin view ]")

        # The admin endpoint only gets hit once the toggle is on.
        expect(
            spa_page.locator('[data-test="overall-section"]').locator(
                '[data-test="ranking-table"]'
            )
        ).to_be_visible()
        deadline = time.time() + POLL_WAIT_MS / 1000
        while time.time() < deadline:
            if any("/submissions/admin" in url for url in requested):
                break
            spa_page.wait_for_timeout(500)
        else:
            pytest.fail(f"admin endpoint never requested; saw {requested}")

    def test_03_the_student_row_survives_the_switch(self, spa_page: Page) -> None:
        row = _overall_row(spa_page, STATE["team"])

        expect(row).to_have_count(1)
        expect(row).to_contain_text(f"{STATE['best_score']:.2f}")


class Test90DisableAgain:
    """
    Last, because it closes the endpoints every test above depends on.
    """

    def test_00_disabling_hides_the_board(
        self, spa_page: Page, ref_instance: Any
    ) -> None:
        set_system_setting(ref_instance, "SCOREBOARD_ENABLED", False)

        spa_page.goto("/spa/scoreboard", wait_until="networkidle")

        expect(spa_page.locator('[data-test="scoreboard-disabled"]')).to_be_visible()
        expect(spa_page.locator('[data-test="scoreboard-board"]')).to_have_count(0)

    def test_01_and_drops_the_nav_tab(self, spa_page: Page) -> None:
        tabs = spa_page.locator(".term-nav-center .term-tab")
        labels = [t.strip() for t in tabs.all_inner_texts()]

        assert "SCOREBOARD" not in labels, f"nav still shows {labels}"


class Test99BrowserHealth:
    def test_99_no_console_errors_or_failed_requests(self, spa_errors: Any) -> None:
        messages = spa_errors.all_messages()

        assert not messages, "Browser reported problems:\n  " + "\n  ".join(messages)
