"""
Remote Execution Helper for REF E2E Tests

Allows tests to execute Python code inside the webapp container
with Flask app context, enabling direct database access and
system settings manipulation.
"""

from __future__ import annotations

import base64
import inspect
import json
import textwrap
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from helpers.ref_instance import REFInstance


class RemoteExecutionError(Exception):
    """Raised when remote execution fails."""

    def __init__(self, message: str, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def remote_exec(
    instance: "REFInstance",
    func: Callable[[], Any],
    timeout: float = 30.0,
) -> Any:
    """
    Execute a Python function inside the webapp container with Flask app context.

    The function's source code is extracted, sent to the container, and executed.
    The result must be JSON-serializable.

    Args:
        instance: The REFInstance to execute code in
        func: A callable (function) to execute. Must not require arguments.
        timeout: Maximum execution time in seconds

    Returns:
        The return value of the function (must be JSON-serializable)

    Raises:
        RemoteExecutionError: If execution fails

    Example:
        def enable_forwarding():
            from ref.model.settings import SystemSettingsManager
            from flask import current_app
            SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value = True
            current_app.db.session.commit()
            return True

        remote_exec(ref_instance, enable_forwarding)
    """
    # Get the source code and name of the function
    try:
        source = inspect.getsource(func)
        # Dedent in case it's an inner function
        source = textwrap.dedent(source)
        func_name = func.__name__

    except Exception as e:
        raise RemoteExecutionError(f"Failed to get function source: {e}") from e

    # Create the payload with the function source and name
    payload = {"source": source, "func_name": func_name}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode("ascii")

    # Execute in container via docker exec
    result = instance._run_compose(
        "exec",
        "-T",
        "web",
        "python3",
        "/app/remote_exec_runner.py",
        capture_output=True,
        check=False,
        input=encoded,
        timeout=timeout,
    )

    # Check for errors
    if result.returncode != 0:
        msg = f"Remote execution failed with code {result.returncode}"
        if result.stdout:
            msg += f"\nSTDOUT: {result.stdout}"
        if result.stderr:
            msg += f"\nSTDERR: {result.stderr}"
        raise RemoteExecutionError(
            msg,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    # The result is base64-encoded JSON data on stdout
    try:
        output = result.stdout.strip()
        # Find the result marker (to handle any spurious output)
        marker = "REMOTE_EXEC_RESULT:"
        if marker not in output:
            raise RemoteExecutionError(
                "Result marker not found in output",
                stdout=result.stdout,
                stderr=result.stderr,
            )

        output = output.split(marker, 1)[1].strip()

        result_data = base64.b64decode(output)
        return_value = json.loads(result_data)
    except RemoteExecutionError:
        raise
    except Exception as e:
        raise RemoteExecutionError(
            f"Failed to deserialize result: {e}",
            stdout=result.stdout,
            stderr=result.stderr,
        ) from e

    # Check if the result is an exception wrapper
    if isinstance(return_value, dict) and return_value.get("__remote_exec_error__"):
        raise RemoteExecutionError(
            f"Remote execution raised: {return_value['error_type']}: "
            f"{return_value['error_message']}\n{return_value.get('traceback', '')}",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    return return_value
