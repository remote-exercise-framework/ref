"""
REF Web Client Helper

HTTP client for interacting with the REF web interface during E2E tests.
"""

import json
from urllib.parse import urlsplit
import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class REFWebClient:
    """
    HTTP client for the REF web interface.

    Handles session management, form submissions, and API calls.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        Initialize the web client.

        Args:
            base_url: The base URL of the REF web interface (e.g., http://localhost:8000)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
        )
        self._logged_in = False

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def _get_csrf_token(self, html: str) -> Optional[str]:
        """Extract CSRF token from HTML form if present."""
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if match:
            return match.group(1)
        return None

    def login(self, mat_num: str, password: str) -> bool:
        """
        Login to REF as admin or grading assistant.

        Args:
            mat_num: Matriculation number (use "0" for admin)
            password: User password

        Returns:
            True if login was successful, False otherwise
        """
        # Get login page to establish session
        response = self.client.get("/login")
        if response.status_code != 200:
            return False

        # Submit login form
        data = {
            "username": mat_num,
            "password": password,
            "submit": "Login",
        }

        response = self.client.post("/login", data=data)

        # Check if we're redirected to admin page (successful login)
        self._logged_in = "/admin/exercise/view" in str(
            response.url
        ) or "/admin/grading" in str(response.url)
        return self._logged_in

    def logout(self) -> bool:
        """Logout from REF."""
        response = self.client.get("/logout")
        self._logged_in = False
        return response.status_code == 200

    def is_logged_in(self) -> bool:
        """Check if the client is currently logged in."""
        return self._logged_in

    # -------------------------------------------------------------------------
    # Exercise Management
    # -------------------------------------------------------------------------

    def get_exercises(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get list of exercises.

        Returns:
            Tuple of (imported_exercises, importable_exercises)
        """
        response = self.client.get("/admin/exercise/view")
        if response.status_code != 200:
            return [], []

        imported = []
        importable = []

        soup = BeautifulSoup(response.text, "lxml")

        # Find imported exercises - look for build/set_default links
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            # Build links contain exercise IDs
            if "/admin/exercise/build/" in href:
                match = re.search(r"/admin/exercise/build/(\d+)", href)
                if match:
                    exercise_id = int(match.group(1))
                    # Find the exercise name from surrounding context
                    row = link.find_parent("tr")
                    if row:
                        cells = row.find_all("td")
                        name = (
                            cells[0].get_text(strip=True)
                            if cells
                            else f"exercise_{exercise_id}"
                        )
                        imported.append(
                            {
                                "id": exercise_id,
                                "name": name,
                                "row": row,
                            }
                        )

            # Import links for importable exercises
            if "/admin/exercise/import/" in href:
                match = re.search(r"/admin/exercise/import/(.+)", href)
                if match:
                    path = urllib.parse.unquote_plus(match.group(1))
                    importable.append(
                        {
                            "path": path,
                            "link": href,
                        }
                    )

        return imported, importable

    def get_exercise_by_name(
        self, short_name: str, retries: int = 10, delay: float = 2.0
    ) -> Optional[Dict[str, Any]]:
        """
        Find an exercise by its short name.

        Args:
            short_name: The exercise short name
            retries: Number of retries if exercise not found immediately
            delay: Delay between retries in seconds

        Returns:
            Exercise dict with id, name, etc. or None if not found
        """
        for attempt in range(retries):
            imported, _ = self.get_exercises()
            for exercise in imported:
                if short_name in exercise.get("name", ""):
                    return exercise
            if attempt < retries - 1:
                time.sleep(delay)
        return None

    def get_exercise_id_by_name(self, short_name: str) -> Optional[int]:
        """
        Find an exercise ID by its short name.

        Args:
            short_name: The exercise short name

        Returns:
            Exercise ID or None if not found
        """
        exercise = self.get_exercise_by_name(short_name)
        return exercise.get("id") if exercise else None

    def wait_for_build(
        self, exercise_id: int, timeout: float = 300.0, poll_interval: float = 2.0
    ) -> bool:
        """
        Wait for an exercise build to complete.

        Args:
            exercise_id: The exercise ID
            timeout: Maximum time to wait in seconds
            poll_interval: Time between status checks

        Returns:
            True if build completed successfully, False otherwise
        """
        start_time = time.time()
        last_status = None
        while time.time() - start_time < timeout:
            response = self.client.get("/admin/exercise/view")
            if response.status_code != 200:
                return False

            soup = BeautifulSoup(response.text, "lxml")

            # Find all table rows and look for the exercise
            for row in soup.find_all("tr"):
                # Check if this row contains a link to our exercise
                row_html = str(row)
                if f"/admin/exercise/view/{exercise_id}" in row_html:
                    # Status is typically in one of the cells
                    row_text = row.get_text()
                    # Check for build status (ExerciseBuildStatus enum values)
                    if "FINISHED" in row_text:
                        return True
                    if "FAILED" in row_text:
                        return False
                    if "BUILDING" in row_text:
                        if last_status != "BUILDING":
                            last_status = "BUILDING"
                        # Still building, continue waiting
                    elif "NOT_BUILD" in row_text:
                        # Build hasn't started yet
                        pass
                    break

            time.sleep(poll_interval)

        return False

    def toggle_exercise_default(self, exercise_id: int) -> bool:
        """
        Flip whether an exercise is the default version.

        This is a toggle, not a setter, and the route gives nothing back
        but a rendered page, so the return value says only that the
        request was served. To *enable* an exercise in a test setup use
        `helpers.method_exec.enable_exercise`, which sets the flag, and
        confirm it with `is_exercise_default`: a successful import already
        marks the first version default, so toggling turns it off and the
        failure then surfaces as "Requested task not found" on every SSH
        login.

        Args:
            exercise_id: The exercise ID

        Returns:
            Whether the request was served, which is not the same as the
            exercise ending up default.
        """
        response = self.client.get(f"/admin/exercise/default/toggle/{exercise_id}")
        return response.status_code == 200

    def import_exercise(self, exercise_path: str) -> bool:
        """
        Import an exercise from the given path.

        Args:
            exercise_path: Path to the exercise directory (host path).
                           The exercise name is extracted and mapped to /exercises/{name}
                           inside the container.

        Returns:
            True if import was successful
        """
        # Extract the exercise name from the host path and map to container path
        # Exercises are mounted at /exercises inside the container
        from pathlib import Path

        exercise_name = Path(exercise_path).name
        container_path = f"/exercises/{exercise_name}"
        # Double encoding is required to match webapp's url_for behavior:
        # 1. quote_plus encodes special chars (e.g., / becomes %2F)
        # 2. quote encodes the % for URL path safety (e.g., %2F becomes %252F)
        # Flask will decode once during routing, then the view decodes again with unquote_plus
        encoded_path = urllib.parse.quote_plus(container_path)
        url_safe_path = urllib.parse.quote(encoded_path, safe="")
        url = f"/admin/exercise/import/{url_safe_path}"
        response = self.client.get(url)
        # Check for success: either 200 OK or redirect to admin (after successful import)
        # Also check for flash messages indicating success/failure
        if response.status_code == 200:
            # Parse response to check for error flash messages
            soup = BeautifulSoup(response.text, "lxml")
            # Check for error alerts (Bootstrap alert-danger class)
            error_alerts = soup.select(".alert-danger")
            if error_alerts:
                logger.info(
                    "import_exercise error alerts: %s",
                    [e.get_text() for e in error_alerts],
                )
                return False
            return True
        logger.info(
            "import_exercise request failed: status=%d, url=%s",
            response.status_code,
            url,
        )
        return False

    def build_exercise(self, exercise_id: int) -> bool:
        """
        Start building an exercise.

        Args:
            exercise_id: The ID of the exercise to build

        Returns:
            True if build was started successfully
        """
        response = self.client.get(f"/admin/exercise/build/{exercise_id}")
        return response.status_code == 200

    def get_exercise_build_status(self, exercise_id: int) -> Optional[str]:
        """
        Get the build status of an exercise.

        Args:
            exercise_id: The ID of the exercise

        Returns:
            Build status string or None if not found
        """
        response = self.client.get("/admin/exercise/view")
        if response.status_code != 200:
            return None

        # Parse status from HTML - simplified
        return None

    def _flash_messages(self, html: str, level: str = "error") -> List[str]:
        """
        Pull the flash messages out of a rendered admin page.

        Needed because the admin views signal a rejected form by
        re-rendering with a flash and HTTP 200 — the status code alone
        never says whether anything was saved.

        Args:
            level: "error", "warning", "success" or "all".
        """
        classes = {
            "error": ["alert-danger"],
            "warning": ["alert-warning"],
            "success": ["alert-success"],
        }
        wanted = (
            ["alert-danger", "alert-warning", "alert-success"]
            if level == "all"
            else classes[level]
        )
        soup = BeautifulSoup(html, "lxml")
        messages: List[str] = []
        for cls in wanted:
            for node in soup.select(f"div.{cls}"):
                # The dismiss button's text is part of the div.
                for button in node.select("button"):
                    button.decompose()
                text = node.get_text(strip=True)
                if text:
                    messages.append(text)
        return messages

    def set_exercise_config(
        self,
        short_name: str,
        *,
        category: str,
        deadline_start: Optional[datetime] = None,
        deadline_end: Optional[datetime] = None,
        submission_test_enabled: bool = True,
        max_grading_points: Optional[int] = None,
        per_task_scoring_policies: Optional[Dict[str, Any]] = None,
        new_short_name: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Write the shared administrative configuration for an exercise.

        This is the only way to set per-task scoring policies: the column
        has no YAML representation and no manager of its own, so the view
        *is* the business logic — and going through it exercises the three
        validators that are the most interesting untested code in the
        feature.

        Call it after the build and after the version has been made
        default. Task names are discovered from the default version's
        `submission_tests` file, and before then discovery returns an empty
        list, which makes the unknown-task check skip itself: an invalid
        policy would be accepted in silence.

        Args:
            category: required by the form, and an exercise needs a
                non-null category to appear on the scoreboard at all.
            deadline_start/deadline_end: both or neither. Naive datetimes
                in the instance's local timezone; set `TIMEZONE` to UTC
                first if a test wants to assert the value back.
            max_grading_points: must be set if and only if a deadline is.
            per_task_scoring_policies: task name -> policy dict. `None`
                leaves the field empty, which sets the column to NULL.
            new_short_name: renames the exercise and every version of it.

        Returns:
            `(saved, error_messages)`. A rejected form re-renders with
            HTTP 200, so the flash messages are the verdict.
        """
        if (deadline_start is None) != (deadline_end is None):
            raise ValueError(
                "deadline_start and deadline_end must both be given or both omitted; "
                "the view rejects a half-set deadline"
            )

        data: Dict[str, Any] = {
            "short_name": new_short_name or short_name,
            "category": category,
            "submission_deadline_start": (
                deadline_start.strftime("%Y-%m-%dT%H:%M") if deadline_start else ""
            ),
            "submission_deadline_end": (
                deadline_end.strftime("%Y-%m-%dT%H:%M") if deadline_end else ""
            ),
            "per_task_scoring_policies_json": (
                json.dumps(per_task_scoring_policies)
                if per_task_scoring_policies is not None
                else ""
            ),
            "submit": "Save",
        }
        # BooleanField: present means true, absent means false. Sending
        # "0" or "false" would still read as true.
        if submission_test_enabled:
            data["submission_test_enabled"] = "y"
        if max_grading_points is not None:
            data["max_grading_points"] = str(max_grading_points)

        url = f"/admin/exercise/config/{short_name}/edit"
        csrf = self._get_csrf_token(self.client.get(url).text)
        if csrf:
            data["csrf_token"] = csrf

        response = self.client.post(url, data=data)
        if response.status_code != 200:
            return False, [f"HTTP {response.status_code}"]

        errors = self._flash_messages(response.text, "error")
        return not errors, errors

    def get_exercise_config(self, short_name: str) -> Optional[Dict[str, Any]]:
        """
        Read back the exercise configuration form.

        Scrapes the form because `max_grading_points` and
        `submission_test_enabled` are not exposed as JSON anywhere. Prefer
        `/api/scoreboard/config` for the category, deadlines and scoring
        policies, where the data is already JSON.

        Returns:
            Field name -> value, or None when no config row exists.
        """
        response = self.client.get(f"/admin/exercise/config/{short_name}/edit")
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        form = soup.find("form")
        if form is None:
            return None

        config: Dict[str, Any] = {}
        for field in form.select("input, textarea"):
            name = field.get("name")
            if not name or name in ("csrf_token", "submit"):
                continue
            if field.get("type") == "checkbox":
                config[name] = field.has_attr("checked")
            elif field.name == "textarea":
                config[name] = field.get_text()
            else:
                config[name] = field.get("value", "")

        raw = config.get("per_task_scoring_policies_json") or ""
        try:
            config["per_task_scoring_policies"] = (
                json.loads(raw) if raw.strip() else None
            )
        except json.JSONDecodeError:
            config["per_task_scoring_policies"] = None
        return config

    # -------------------------------------------------------------------------
    # Student Management
    # -------------------------------------------------------------------------

    def register_student(
        self,
        mat_num: str,
        firstname: str,
        surname: str,
        password: str,
        pubkey: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Register a new student account and get SSH keys.

        Posts to the SPA registration endpoint, which is what the student
        registration page uses. The response carries the key material
        directly, so the download routes do not need to be called.

        Args:
            mat_num: Matriculation number
            firstname: First name
            surname: Surname
            password: Password
            pubkey: Optional SSH public key (if not provided, keys are generated)

        Returns:
            Tuple of (success, private_key, public_key)
            If pubkey was provided, private_key will be None.
        """
        payload = {
            "mat_num": mat_num,
            "firstname": firstname,
            "surname": surname,
            "password": password,
            "password_rep": password,
            "pubkey": pubkey or "",
        }

        response = self.client.post("/api/v2/registration", json=payload)
        if response.status_code != 200:
            return False, None, None

        body = response.json()
        return True, body.get("privkey"), body.get("pubkey")

    def create_student(
        self,
        mat_num: str,
        firstname: str,
        surname: str,
        password: str,
        pubkey: Optional[str] = None,
    ) -> bool:
        """
        Create a new student account (convenience wrapper).

        Args:
            mat_num: Matriculation number
            firstname: First name
            surname: Surname
            password: Password
            pubkey: Optional SSH public key

        Returns:
            True if creation was successful
        """
        success, _, _ = self.register_student(
            mat_num, firstname, surname, password, pubkey
        )
        return success

    def restore_student_key(
        self, mat_num: str, password: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Restore a student's SSH keys using their credentials.

        Args:
            mat_num: Matriculation number
            password: Password

        Returns:
            Tuple of (success, private_key, public_key)
        """
        response = self.client.post(
            "/api/v2/restore-key", json={"mat_num": mat_num, "password": password}
        )
        if response.status_code != 200:
            return False, None, None

        body = response.json()
        return True, body.get("privkey"), body.get("pubkey")

    def get_student(self, mat_num: str) -> Optional[Dict[str, Any]]:
        """
        Get student information by matriculation number (requires admin login).

        Args:
            mat_num: Matriculation number

        Returns:
            Student data dict or None if not found
        """
        response = self.client.get("/admin/student/view")
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        # Look for the student in the table
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if cells and len(cells) >= 2:
                # Check if mat_num matches
                row_mat = cells[0].get_text(strip=True) if cells else ""
                if row_mat == mat_num:
                    # Find user ID from any links
                    user_id = None
                    for link in row.find_all("a", href=True):
                        match = re.search(
                            r"/admin/student/view/(\d+)", str(link.get("href", ""))
                        )
                        if match:
                            user_id = int(match.group(1))
                            break
                    return {
                        "mat_num": mat_num,
                        "id": user_id,
                        "name": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    }

        return None

    def get_student_private_key(self, student_id: int) -> Optional[str]:
        """
        Get a student's private SSH key (if stored) - requires admin access.

        Args:
            student_id: The student's database ID

        Returns:
            Private key string or None
        """
        # Admin can view student details which may contain key info
        response = self.client.get(f"/admin/student/view/{student_id}")
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        # Look for private key in the page
        for elem in soup.find_all(["textarea", "pre", "code"]):
            text = elem.get_text(strip=True)
            if (
                "-----BEGIN RSA PRIVATE KEY-----" in text
                or "-----BEGIN PRIVATE KEY-----" in text
            ):
                return text

        return None

    # -------------------------------------------------------------------------
    # Instance Management
    # -------------------------------------------------------------------------

    def instances_page_reachable(self, exercise_id: Optional[int] = None) -> bool:
        """
        Whether the instance overview renders for the current user.

        Deliberately not a list of instances: the page is a Jinja table
        with no stable identifier per row, and `InstanceManager` via
        `remote_exec` is the right way to inspect instances. A method that
        returned an empty list unconditionally was worse than none,
        because tests asserted on it and passed.
        """
        url = "/admin/instances/view"
        if exercise_id:
            url += f"?exercise_id={exercise_id}"

        return self.client.get(url).status_code == 200

    # -------------------------------------------------------------------------
    # Submission and Grading
    # -------------------------------------------------------------------------

    def get_submission_ids(self, exercise_id: int) -> List[int]:
        """
        The gradeable submissions listed for one exercise.

        Scraped from the links to the grading page rather than from table
        columns, because the link target is the only thing on that page
        that carries a submission id.

        Returns:
            Submission ids, in the order the page lists them. Empty when
            the exercise has no submissions or the page is not reachable
            for the current user.
        """
        path = f"/admin/grading/{exercise_id}"
        response = self.client.get(path)
        # A client that may not view the exercise is redirected away with a
        # flash, and the page it lands on also answers 200 with no grading
        # links on it - indistinguishable from "no submissions" unless the
        # final path is checked.
        if response.status_code != 200 or not self._landed_under(response, path):
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        ids: List[int] = []
        for link in soup.find_all("a", href=True):
            match = re.search(r"/admin/grading/grade/(\d+)", link["href"])
            if match:
                submission_id = int(match.group(1))
                if submission_id not in ids:
                    ids.append(submission_id)
        return ids

    def get_grading(self, submission_id: int) -> Optional[Dict[str, Any]]:
        """
        The grade currently stored for a submission.

        Returns:
            `{"points": Optional[int], "notes": str}`, or None when the
            grading page is not reachable. `points` is None when the
            submission has not been graded yet, which the form renders as
            an empty value rather than a zero.
        """
        path = f"/admin/grading/grade/{submission_id}"
        response = self.client.get(path)
        if response.status_code != 200 or not self._landed_under(response, path):
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        points_field = soup.find("input", attrs={"name": "points"})
        raw_points = points_field.get("value", "") if points_field else ""

        # `notes` goes through `render_textarea`, so its content is the
        # element's text and not a value attribute.
        notes_field = soup.find("textarea", attrs={"name": "notes"})
        notes = notes_field.get_text() if notes_field else ""

        return {
            "points": int(raw_points) if str(raw_points).strip() != "" else None,
            "notes": notes,
        }

    def _landed_under(self, response: Any, prefix: str) -> bool:
        """
        Whether a request ended up under the route tree it asked for.

        The admin and grading routes bounce an unauthorized client to the
        login page, which the client follows and which answers 200, so
        without checking where the request landed every "can this role
        reach X" probe reads a login form as success. A prefix rather than
        an exact path because "save and next" redirects to a *different*
        grading page, which is a success.
        """
        return urlsplit(str(response.url)).path.startswith(prefix)

    def grade_submission(
        self,
        submission_id: int,
        points: int,
        notes: str = "",
        action: str = "save",
    ) -> Tuple[bool, List[str]]:
        """
        Grade a submission.

        Args:
            submission_id: The submission to grade.
            points: Points awarded. An IntegerField in `GradingForm`, so a
                float is not accepted.
            notes: Stored as the grading's private note. There is no public
                comment field.
            action: Which submit button to press — "save", "save_and_next"
                or "save_next_user_task". The form also declares "next",
                "next_user_task" and "reset", but those do not save.

        Returns:
            (ok, errors). A rejected grade re-renders the form with HTTP
            200, so the status code alone is not a verdict: the errors list
            carries what the page complained about. Grading is refused
            while the exercise deadline is still open, and refused when
            points exceed the exercise maximum.
        """
        saving_actions = ("save", "save_and_next", "save_next_user_task")
        if action not in saving_actions:
            raise ValueError(f"{action!r} does not save; use one of {saving_actions}")

        data = {
            "points": str(points),
            "notes": notes,
            action: "1",
        }
        path = f"/admin/grading/grade/{submission_id}"
        response = self.client.post(path, data=data)
        if response.status_code != 200:
            return False, [f"HTTP {response.status_code}"]
        if not self._landed_under(response, "/admin/grading/grade/"):
            return False, [f"redirected away from {path} to {response.url}"]

        errors = self._flash_messages(response.text, level="error")
        errors += self._field_errors(response.text)
        if errors:
            return False, errors

        return True, []

    def _field_errors(self, html: str) -> List[str]:
        """
        Per-field validation messages on a re-rendered admin form.

        Separate from `_flash_messages`: a points-over-maximum rejection
        sets `form.points.errors` and never flashes, so a caller looking
        only at flash messages would read it as a success.
        """
        soup = BeautifulSoup(html, "html.parser")
        messages: List[str] = []
        for element in soup.select(".invalid-feedback, .form-error, ul.errors li"):
            text = element.get_text(strip=True)
            if text:
                messages.append(text)
        return messages

    # -------------------------------------------------------------------------
    # System Settings
    # -------------------------------------------------------------------------

    def settings_page_reachable(self) -> bool:
        """
        Whether the system settings form renders for the current user.

        Reading or writing a setting goes through
        `helpers.method_exec.system_setting` instead: the settings POST
        writes every field of a form group at once, so a partial post
        blanks `COURSE_NAME`, `TIMEZONE` and the rest of the group.
        """
        return self.client.get("/admin/system/settings/").status_code == 200

    # -------------------------------------------------------------------------
    # API Endpoints
    # -------------------------------------------------------------------------

    def api_get_header(self) -> Optional[str]:
        """Get the SSH welcome header."""
        response = self.client.post("/api/header")
        if response.status_code == 200:
            data = response.json()
            return data
        return None

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    def health_check(self) -> bool:
        """
        Check if REF is responding.

        Returns:
            True if REF is healthy
        """
        try:
            response = self.client.get("/login")
            return response.status_code == 200
        except httpx.RequestError:
            return False
