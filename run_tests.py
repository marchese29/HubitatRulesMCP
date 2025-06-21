#!/usr/bin/env python3
"""
Test runner script for HubitatRulesMCP using uv.

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py --unit            # Run only unit tests
    python run_tests.py --integration     # Run only integration tests
    python run_tests.py --verbose         # Run with verbose output
"""

import argparse
import subprocess
import sys


def run_tests(test_type=None, verbose=False):
    """Run tests using uv with pytest."""
    cmd = ["uv", "run", "--group", "test", "pytest", "tests/"]

    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    if test_type == "unit":
        cmd.extend(["-m", "unit"])
    elif test_type == "integration":
        cmd.extend(["-m", "integration"])

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\nTest run interrupted by user")
        return 1
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Run HubitatRulesMCP tests")
    parser.add_argument("--unit", action="store_true", help="Run only unit tests")
    parser.add_argument(
        "--integration", action="store_true", help="Run only integration tests"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Run with verbose output"
    )

    args = parser.parse_args()

    if args.unit and args.integration:
        print("Error: Cannot specify both --unit and --integration")
        return 1

    test_type = None
    if args.unit:
        test_type = "unit"
        print("Running unit tests...")
    elif args.integration:
        test_type = "integration"
        print("Running integration tests...")
    else:
        print("Running all tests...")

    return run_tests(test_type, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
