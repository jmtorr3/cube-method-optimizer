"""
run.py — Entry point for running a single solve from the command line.

Usage:
    python -m solver.run <dsl_file> [workspace]

    workspace defaults to workspace/stable
"""

import sys
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


def main():
    dsl_file  = sys.argv[1] if len(sys.argv) > 1 else os.path.join("workspace", "stable", "dsl", "zz_method.dsl")
    workspace = sys.argv[2] if len(sys.argv) > 2 else os.path.join("workspace", "stable")
    scramble = sys.argv[3] if len(sys.argv) > 3 else " ".join(Scramble.Cube3x3x3())

    method = method_from_file(dsl_file)
    runner = MethodRunner(
        solver_path=_solver_path(),
        workspace_root=workspace,
        timeout=TIMEOUT,
    )
    scramble = " ".join(Scramble.Cube3x3x3())
    result = runner.run(method, scramble)
    print(format_solve_result(result))


if __name__ == "__main__":
    main()
