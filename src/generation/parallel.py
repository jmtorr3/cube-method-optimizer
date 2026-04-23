"""
parallel.py — Memory-aware parallel solve execution for data generation.

Not intended to be run directly; imported by data_generation.py.

Worker granularity: one worker = one full scramble solve for one method.
All CSV writes are handled by the caller (main process only).
"""

import time
import platform
import psutil
from concurrent.futures import ProcessPoolExecutor, Future, as_completed

from core.config import CONFIG
from core.models import Method, SolveResult
from solver.solver import MethodRunner, TIMEOUT


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_PARALLEL_CFG = CONFIG["parallel"]

_MEMORY_FRACTION    = _PARALLEL_CFG["memory_fraction"]       # e.g. 0.35
_MEMORY_PER_WORKER  = _PARALLEL_CFG["memory_per_worker_gb"]  # e.g. 6
_SAFETY_BUFFER_GB   = _PARALLEL_CFG["safety_buffer_gb"]      # e.g. 8
_MAX_WORKERS_CFG    = _PARALLEL_CFG.get("max_workers")        # null → auto

_SPAWN_POLL_INTERVAL = 0.5  # seconds to wait when worker cap is hit


# ---------------------------------------------------------------------------
# Worker function (must be top-level for pickling)
# ---------------------------------------------------------------------------

def _solve_worker(method: Method, scramble: str, solver_path: str, workspace_root: str) -> SolveResult:
    """
    Run a single solve in a worker process. Each worker creates its own
    MethodRunner. Cache reads and appends are safe — entries are deterministic
    so concurrent duplicate writes are harmless.
    """
    runner = MethodRunner(
        solver_path=solver_path,
        workspace_root=workspace_root,
        timeout=TIMEOUT,
    )
    return runner.run(method, scramble)


# ---------------------------------------------------------------------------
# Worker cap calculation
# ---------------------------------------------------------------------------

def _compute_max_workers() -> int:
    """
    Derive the worker cap from config and total system memory.
    If max_workers is set explicitly in config, that value is used directly.
    Otherwise, calculate from memory_fraction, memory_per_worker_gb, and
    safety_buffer_gb.
    """
    if _MAX_WORKERS_CFG is not None:
        return int(_MAX_WORKERS_CFG)

    total_gb     = psutil.virtual_memory().total / (1024 ** 3)
    usable_gb    = total_gb * _MEMORY_FRACTION
    available_gb = usable_gb - _SAFETY_BUFFER_GB
    calculated   = int(available_gb / _MEMORY_PER_WORKER)

    return max(1, calculated)


# ---------------------------------------------------------------------------
# Solver path helper (mirrors data_generation.py)
# ---------------------------------------------------------------------------

def _solver_path() -> str:
    import os
    system = platform.system().lower()
    base = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
    if system == "windows":
        return os.path.join(base, "windows", "kube_solver.exe")
    elif system == "darwin":
        return os.path.join(base, "mac", "kube_solver")
    else:
        return os.path.join(base, "linux", "kube_solver")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_parallel_solves(
    tasks: list[tuple[Method, str]],
    workspace_root: str,
):
    """
    Run a flat list of (method, scramble) solve tasks in parallel and
    YIELD (method, SolveResult) as each future completes.

    This is a generator — callers iterate over it incrementally. Results
    are NOT in input order; callers must group by method.name.

    Args:
        tasks:          Flat list of (method, scramble) pairs.
        workspace_root: Passed through to each worker's MethodRunner.

    Yields:
        (method, SolveResult) as futures complete.
    """
    max_workers = _compute_max_workers()
    solver      = _solver_path()

    print(f"[parallel] max_workers={max_workers} "
          f"(memory_fraction={_MEMORY_FRACTION}, "
          f"per_worker={_MEMORY_PER_WORKER}GB, "
          f"buffer={_SAFETY_BUFFER_GB}GB)",
          flush=True)

    pending: dict[Future, Method] = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        task_iter = iter(tasks)
        exhausted = False

        while not exhausted or pending:

            # Fill worker slots up to max_workers
            while not exhausted and len(pending) < max_workers:
                try:
                    method, scramble = next(task_iter)
                except StopIteration:
                    exhausted = True
                    break

                future = executor.submit(
                    _solve_worker, method, scramble, solver, workspace_root
                )
                pending[future] = method

            if not pending:
                break

            # Wait for at least one future to finish, then yield all that are done
            # as_completed blocks until one is ready — no busy-polling
            done_iter = as_completed(list(pending.keys()))
            future = next(done_iter)  # blocks until one completes

            method = pending.pop(future)
            try:
                result = future.result()
                yield method, result
            except Exception as e:
                print(f"[WARN] Worker failed for '{method.name}': {e}", flush=True)

            # Drain any others that also finished in the meantime
            still_done = [f for f in list(pending.keys()) if f.done()]
            for f in still_done:
                m = pending.pop(f)
                try:
                    yield m, f.result()
                except Exception as e:
                    print(f"[WARN] Worker failed for '{m.name}': {e}", flush=True)
