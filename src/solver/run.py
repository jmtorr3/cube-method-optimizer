"""
run.py — Entry point for running a single solve from the command line.

Usage:
    python -m solver.run <dsl_file> [workspace] [--scramble SCRAMBLE]

    workspace defaults to workspace/stable
    scramble defaults to a random 3x3 scramble
"""

import argparse
import os
import platform

from PyRubik import Scramble

from core.dsl import method_from_file
from core.models import format_solve_result
from solver.solver import MethodRunner, TIMEOUT


def _solver_path() -> str:
    system = platform.system().lower()
    base = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
    if system == "windows":
        return os.path.join(base, "windows", "kube_solver.exe")
    elif system == "darwin":
        return os.path.join(base, "mac", "kube_solver")
    else:
        return os.path.join(base, "linux", "kube_solver")


def _random_scramble() -> str:
    return " ".join(Scramble.Cube3x3x3())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one DSL method solve against a random or provided scramble."
    )
    parser.add_argument(
        "dsl_file",
        nargs="?",
        default=os.path.join("workspace", "stable", "dsl", "zz_method.dsl"),
        help="Path to the DSL method file.",
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=os.path.join("workspace", "stable"),
        help="Workspace root containing alg caches and generated data.",
    )
    parser.add_argument(
        "-s",
        "--scramble",
        help="Custom scramble to solve, e.g. \"R U R' U'\".",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    scramble = args.scramble or _random_scramble()

    method = method_from_file(args.dsl_file)
    runner = MethodRunner(
        solver_path=_solver_path(),
        workspace_root=args.workspace,
        timeout=TIMEOUT,
    )
    result = runner.run(method, scramble)
    print(format_solve_result(result))


if __name__ == "__main__":
    main()
