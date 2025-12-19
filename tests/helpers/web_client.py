"""
REF Web Client Helper

HTTP client for interacting with the REF web interface during E2E tests.
"""

import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup


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
        self._logged_in = "/admin/exercise/view" in str(response.url) or "/admin/grading" in str(response.url)
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
                        name = cells[0].get_text(strip=True) if cells else f"exercise_{exercise_id}"
                        imported.append({
                            "id": exercise_id,
                            "name": name,
                            "row": row,
                        })

            # Import links for importable exercises
            if "/admin/exercise/import/" in href:
                match = re.search(r"/admin/exercise/import/(.+)", href)
                if match:
                    path = urllib.parse.unquote_plus(match.group(1))
                    importable.append({
                        "path": path,
                        "link": href,
                    })

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
                    # Get all td cells in the row
                    cells = row.find_all("td")
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
        Toggle an exercise as default.

        Args:
            exercise_id: The exercise ID

        Returns:
            True if successful
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
        url_safe_path = urllib.parse.quote(encoded_path, safe='')
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
                return False
            return True
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

    def set_exercise_as_default(self, exercise_id: int) -> bool:
        """
        Set an exercise version as the default.

        Args:
            exercise_id: The ID of the exercise

        Returns:
            True if successful
        """
        response = self.client.get(f"/admin/exercise/set_default/{exercise_id}")
        return response.status_code == 200

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
        data = {
            "mat_num": mat_num,
            "firstname": firstname,
            "surname": surname,
            "password": password,
            "password_rep": password,
            "pubkey": pubkey or "",
            "submit": "Get Key",
        }

        response = self.client.post("/student/getkey", data=data)
        if response.status_code != 200:
            return False, None, None

        soup = BeautifulSoup(response.text, "lxml")

        # Check for error messages
        error_elements = soup.find_all(class_="error") + soup.find_all(class_="alert-danger")
        for error in error_elements:
            error_text = error.get_text().lower()
            if "already registered" in error_text:
                return False, None, None

        # Extract private key from the page (displayed in a textarea or pre element)
        private_key = None
        public_key = None

        # Look for key in various elements
        for elem in soup.find_all(["textarea", "pre", "code"]):
            text = elem.get_text(strip=True)
            if "-----BEGIN RSA PRIVATE KEY-----" in text or "-----BEGIN PRIVATE KEY-----" in text:
                private_key = text
            elif text.startswith("ssh-rsa "):
                public_key = text

        # Also check for download links
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            if "/student/download/privkey/" in href:
                # Fetch the private key
                key_response = self.client.get(href)
                if key_response.status_code == 200:
                    private_key = key_response.text
            elif "/student/download/pubkey/" in href:
                # Fetch the public key
                key_response = self.client.get(href)
                if key_response.status_code == 200:
                    public_key = key_response.text

        # If a pubkey was provided and no error, consider it successful
        if pubkey and not private_key:
            public_key = pubkey
            return True, None, public_key

        # Check if we got at least one key
        success = private_key is not None or public_key is not None
        return success, private_key, public_key

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
        success, _, _ = self.register_student(mat_num, firstname, surname, password, pubkey)
        return success

    def restore_student_key(self, mat_num: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Restore a student's SSH keys using their credentials.

        Args:
            mat_num: Matriculation number
            password: Password

        Returns:
            Tuple of (success, private_key, public_key)
        """
        data = {
            "mat_num": mat_num,
            "password": password,
            "submit": "Restore",
        }

        response = self.client.post("/student/restoreKey", data=data)
        if response.status_code != 200:
            return False, None, None

        soup = BeautifulSoup(response.text, "lxml")

        private_key = None
        public_key = None

        # Look for download links
        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))
            if "/student/download/privkey/" in href:
                key_response = self.client.get(href)
                if key_response.status_code == 200:
                    private_key = key_response.text
            elif "/student/download/pubkey/" in href:
                key_response = self.client.get(href)
                if key_response.status_code == 200:
                    public_key = key_response.text

        success = private_key is not None or public_key is not None
        return success, private_key, public_key

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
                        match = re.search(r"/admin/student/view/(\d+)", str(link.get("href", "")))
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
            if "-----BEGIN RSA PRIVATE KEY-----" in text or "-----BEGIN PRIVATE KEY-----" in text:
                return text

        return None

    # -------------------------------------------------------------------------
    # Instance Management
    # -------------------------------------------------------------------------

    def get_instances(self, exercise_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get list of instances.

        Args:
            exercise_id: Optional filter by exercise ID

        Returns:
            List of instance dicts
        """
        url = "/admin/instances/view"
        if exercise_id:
            url += f"?exercise_id={exercise_id}"

        response = self.client.get(url)
        if response.status_code != 200:
            return []

        return []

    # -------------------------------------------------------------------------
    # Submission and Grading
    # -------------------------------------------------------------------------

    def get_submissions(self, exercise_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get list of submissions.

        Args:
            exercise_id: Optional filter by exercise ID

        Returns:
            List of submission dicts
        """
        url = "/admin/grading/"
        if exercise_id:
            url += f"?exercise_id={exercise_id}"

        response = self.client.get(url)
        if response.status_code != 200:
            return []

        return []

    def grade_submission(
        self,
        submission_id: int,
        points: float,
        comment: str = "",
        private_note: str = "",
    ) -> bool:
        """
        Grade a submission.

        Args:
            submission_id: The submission ID
            points: Points to award
            comment: Public comment
            private_note: Private note (not visible to student)

        Returns:
            True if grading was successful
        """
        data = {
            "points": points,
            "comment": comment,
            "private_note": private_note,
            "submit": "Save",
        }

        response = self.client.post(f"/admin/grading/edit/{submission_id}", data=data)
        return response.status_code == 200

    # -------------------------------------------------------------------------
    # System Settings
    # -------------------------------------------------------------------------

    def get_system_settings(self) -> Dict[str, Any]:
        """Get current system settings."""
        response = self.client.get("/admin/system/settings/")
        if response.status_code != 200:
            return {}
        return {}

    def update_system_setting(self, key: str, value: Any) -> bool:
        """
        Update a system setting.

        Args:
            key: Setting key
            value: New value

        Returns:
            True if update was successful
        """
        # Implementation depends on specific setting endpoints
        return False

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
