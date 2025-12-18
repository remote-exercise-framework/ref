"""
sitecustomize.py - Enables automatic coverage collection for all Python processes.

This file is automatically imported by Python at startup when placed in site-packages
or when PYTHONPATH includes its directory.

Coverage.py looks for COVERAGE_PROCESS_START environment variable and uses it
to locate the coverage configuration file.
"""

import atexit
import os


def _start_coverage():
    """Start coverage collection if COVERAGE_PROCESS_START is set."""
    coverage_rc = os.environ.get("COVERAGE_PROCESS_START")
    if not coverage_rc:
        return

    if not os.path.exists(coverage_rc):
        # Config file not found, skip coverage
        return

    try:
        import coverage

        # Create a unique data file suffix based on container name and PID
        container_name = os.environ.get("COVERAGE_CONTAINER_NAME", "unknown")

        # Start coverage with unique suffix
        cov = coverage.Coverage(
            config_file=coverage_rc, data_suffix=f".{container_name}.{os.getpid()}"
        )
        cov.start()

        # Register cleanup to save coverage on exit
        def _save_coverage():
            try:
                cov.stop()
                cov.save()
            except Exception:
                pass  # Don't crash on coverage save failure

        atexit.register(_save_coverage)

    except ImportError:
        # coverage not installed, skip
        pass
    except Exception:
        # Don't crash the application if coverage setup fails
        pass


_start_coverage()
