#!/usr/bin/env python3
"""
Remote Execution Runner for REF E2E Tests

This script is executed inside the webapp container by remote_exec().
It:
1. Reads base64-encoded cloudpickle data from stdin
2. Creates Flask app context
3. Deserializes and executes the function
4. Returns the result via stdout

SECURITY NOTE: This script should only be present in testing/development builds.
It provides arbitrary code execution and must never be deployed to production.
"""

import base64
import json
import sys
import traceback

import cloudpickle


def main() -> int:
    # Read the encoded function from stdin
    encoded_input = sys.stdin.read().strip()

    if not encoded_input:
        print("ERROR: No input received", file=sys.stderr)
        return 1

    try:
        # Decode and unpickle the function
        pickled_data = base64.b64decode(encoded_input)
        func = cloudpickle.loads(pickled_data)

    except Exception as e:
        print(f"ERROR: Failed to decode/unpickle function: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    try:
        # Create Flask app with app context
        from ref import create_app

        app = create_app()

        with app.app_context():
            # Call the function and get its return value
            result = func()

    except Exception as e:
        # Return the exception as a JSON error
        error_result = {
            "__remote_exec_error__": True,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }
        print(
            f"REMOTE_EXEC_RESULT:{base64.b64encode(json.dumps(error_result).encode()).decode()}"
        )
        return 0

    try:
        # Serialize and encode the result as JSON
        result_json = json.dumps(result)
        encoded_result = base64.b64encode(result_json.encode()).decode("ascii")

        # Output with marker for reliable parsing
        print(f"REMOTE_EXEC_RESULT:{encoded_result}")

    except Exception as e:
        print(f"ERROR: Failed to serialize result: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
