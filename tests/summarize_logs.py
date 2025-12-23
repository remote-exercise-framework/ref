#!/usr/bin/env python3
"""
Summarize test failure logs by scanning for common error patterns.

Usage:
    cd tests && python summarize_logs.py

Output is written to tests/failure_logs/SUMMARY.txt
"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Error patterns to detect. Each key is a label, value is a regex pattern.
# Maintain this dict:
#   - Add patterns for error types that appear in logs but are missing from summaries
#   - Remove patterns that trigger false positives (matching non-error text)
ERROR_PATTERNS: dict[str, str] = {
    # Python built-in exceptions
    "TypeError": r"TypeError:",
    "ValueError": r"ValueError:",
    "KeyError": r"KeyError:",
    "IndexError": r"IndexError:",
    "AttributeError": r"AttributeError:",
    "NameError": r"NameError:",
    "ImportError": r"ImportError:",
    "ModuleNotFoundError": r"ModuleNotFoundError:",
    "RuntimeError": r"RuntimeError:",
    "AssertionError": r"AssertionError:",
    "TimeoutError": r"TimeoutError:",
    "OSError": r"OSError:",
    "FileNotFoundError": r"FileNotFoundError:",
    "PermissionError": r"PermissionError:",
    "ConnectionError": r"ConnectionError:",
    "ConnectionRefusedError": r"ConnectionRefusedError:",
    "BrokenPipeError": r"BrokenPipeError:",
    "TimeoutExpired": r"TimeoutExpired:",
    "CalledProcessError": r"CalledProcessError:",
    # Custom exceptions from REF codebase
    "InconsistentStateError": r"InconsistentStateError:",
    "RemoteExecutionError": r"RemoteExecutionError:",
    "ApiRequestError": r"ApiRequestError:",
    "SSHException": r"SSHException:",
    # Rust/SSH-Proxy patterns
    "[SSH-PROXY] error": r"\[SSH-PROXY\].*(?:[Ee]rror|[Ff]ailed)",
    "Rust panic": r"thread '.*' panicked",
    # Generic patterns
    "Traceback": r"Traceback \(most recent call last\)",
    "Connection refused": r"Connection refused",
    "HTTP 4xx": r"HTTP[/ ]4\d{2}|status[_ ]code[=: ]+4\d{2}",
    "HTTP 5xx": r"HTTP[/ ]5\d{2}|status[_ ]code[=: ]+5\d{2}",
}

# Log files to scan within each failure directory
LOG_FILES = ["error.txt", "container_logs.txt", "app.log", "build.log"]


def scan_file(file_path: Path) -> list[tuple[str, int, str]]:
    """
    Scan a file for error patterns.

    Returns list of (error_label, line_number, matched_line) tuples.
    """
    matches: list[tuple[str, int, str]] = []

    if not file_path.exists():
        return matches

    try:
        content = file_path.read_text(errors="replace")
    except Exception:
        return matches

    lines = content.splitlines()
    compiled_patterns = {
        label: re.compile(pattern) for label, pattern in ERROR_PATTERNS.items()
    }

    for line_num, line in enumerate(lines, start=1):
        for label, regex in compiled_patterns.items():
            if regex.search(line):
                matches.append((label, line_num, line.strip()[:100]))

    return matches


def scan_failure_dir(failure_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """
    Scan all log files in a failure directory.

    Returns dict mapping error label to list of (log_file, line_num) tuples.
    """
    results: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for log_file in LOG_FILES:
        file_path = failure_dir / log_file
        matches = scan_file(file_path)
        for label, line_num, _ in matches:
            results[label].append((log_file, line_num))

    return dict(results)


def generate_summary(failure_logs_dir: Path) -> str:
    """Generate the full summary text."""
    # Collect all failure directories
    failure_dirs = sorted(
        [d for d in failure_logs_dir.iterdir() if d.is_dir()],
        key=lambda x: x.name,
    )

    if not failure_dirs:
        return "No failure directories found.\n"

    # Data structures for both sections
    # by_error_type[label] = [(dir_name, file, line), ...]
    by_error_type: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    # by_test[dir_name] = [(label, file, line), ...]
    by_test: dict[str, list[tuple[str, str, int]]] = defaultdict(list)

    for failure_dir in failure_dirs:
        dir_name = failure_dir.name
        results = scan_failure_dir(failure_dir)

        for label, file_line_pairs in results.items():
            for log_file, line_num in file_line_pairs:
                by_error_type[label].append((dir_name, log_file, line_num))
                by_test[dir_name].append((label, log_file, line_num))

    # Build summary text
    lines: list[str] = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append("=== Test Failure Log Summary ===")
    lines.append(f"Generated: {timestamp}")
    lines.append(f"Scanned: {len(failure_dirs)} failure directories")
    lines.append("")

    # Section 1: By Error Type
    lines.append("=" * 80)
    lines.append("SECTION 1: BY ERROR TYPE")
    lines.append("=" * 80)
    lines.append("")

    if by_error_type:
        for label in sorted(by_error_type.keys()):
            occurrences = by_error_type[label]
            lines.append(f"{label} ({len(occurrences)} occurrences):")
            for dir_name, log_file, line_num in occurrences[
                :20
            ]:  # Limit to 20 per type
                lines.append(f"  {dir_name}/{log_file}:{line_num}")
            if len(occurrences) > 20:
                lines.append(f"  ... and {len(occurrences) - 20} more")
            lines.append("")
    else:
        lines.append("No error patterns detected.")
        lines.append("")

    # Section 2: By Test
    lines.append("=" * 80)
    lines.append("SECTION 2: BY TEST")
    lines.append("=" * 80)
    lines.append("")

    if by_test:
        for dir_name in sorted(by_test.keys()):
            errors = by_test[dir_name]
            lines.append(f"{dir_name}/:")
            # Deduplicate and show unique error types per file
            seen: set[tuple[str, str, int]] = set()
            for label, log_file, line_num in errors:
                key = (label, log_file, line_num)
                if key not in seen:
                    seen.add(key)
                    lines.append(f"  {label} @ {log_file}:{line_num}")
            lines.append("")
    else:
        lines.append("No test failures with detected errors.")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    script_dir = Path(__file__).parent
    failure_logs_dir = script_dir / "failure_logs"

    if not failure_logs_dir.exists():
        print(f"Failure logs directory not found: {failure_logs_dir}")
        return

    summary = generate_summary(failure_logs_dir)

    # Write to SUMMARY.txt
    output_path = failure_logs_dir / "SUMMARY.txt"
    output_path.write_text(summary)
    print(f"Summary written to: {output_path}")

    # Also print to stdout
    print()
    print(summary)


if __name__ == "__main__":
    main()
