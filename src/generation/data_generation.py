"""
data_generation.py — Data generation pipeline for the cube method solver.

Entry point:
    python -m generation.data_generation [workspace]

    workspace defaults to workspace/stable
"""

import os
import sys
import csv
import platform
from collections import defaultdict
from datetime import datetime

from PyRubik import Scramble

from core.models import Method, SolveResult
from core.dsl import method_from_file
from core.cache import load_cache
from solver.solver import MethodRunner, TIMEOUT
from core.config import CONFIG
from generation.parallel import run_parallel_solves


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NUM_SCRAMBLES  = CONFIG["generation"]["num_scrambles"]
NUM_ALG_SOLVES = CONFIG["generation"]["num_alg_solves"]
PARALLEL       = CONFIG["parallel"]["enabled"]

# Constraint type prefixes — extend as new constraint types are added to the DSL
_CONSTRAINT_PREFIXES = {
    "edge":        ("add_edge ",),
    "corner":      ("add_corner ",),
    "orientation": ("add_edges_orientation", "add_corners_orientation"),
}

METHOD_FIELDNAMES = [
    "method_name",
    "num_steps",
    "num_groups",
    "num_removes",
    "total_constraints",
    "avg_constraints_per_step",
    "max_constraints_per_step",
    "num_cache_alg_steps",
    "num_free_layer_steps",
    "symmetry_depth",
    "num_symmetry_orientations",
    "num_edge_constraints",
    "num_corner_constraints",
    "num_orientation_constraints",
    "constraint_type_diversity",
    "score",  # ML label — populated by evaluate_solves, empty until then
]


# ---------------------------------------------------------------------------
# Workspace path helpers
# ---------------------------------------------------------------------------

def _solves_path(workspace_root: str, method_name: str) -> str:
    return os.path.join(workspace_root, "data", "solves", f"{method_name}.csv")

def _eval_path(workspace_root: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(workspace_root, "data", "evaluation", f"evaluation_{timestamp}.csv")

def _methods_csv_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, "data", "methods", "methods.csv")

def _ensure_dirs(workspace_root: str):
    os.makedirs(os.path.join(workspace_root, "data", "solves"),     exist_ok=True)
    os.makedirs(os.path.join(workspace_root, "data", "evaluation"), exist_ok=True)
    os.makedirs(os.path.join(workspace_root, "data", "methods"),    exist_ok=True)
    os.makedirs(os.path.join(workspace_root, "algs"),               exist_ok=True)

def _solver_path() -> str:
    system = platform.system().lower()
    base = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
    if system == "windows":
        return os.path.join(base, "windows", "kube_solver.exe")
    elif system == "darwin":
        return os.path.join(base, "mac", "kube_solver")
    else:
        return os.path.join(base, "linux", "kube_solver")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _step_names(result: SolveResult) -> list:
    return [s.name for s in result.steps]

def _move_count(solution: str) -> int:
    return len(solution.split()) if solution.strip() else 0

def _num_algs(workspace_root: str, method: Method) -> int:
    """Count total cached algorithms across all steps in this method."""
    from core.models import Step, Group
    total = 0
    for item in method.items:
        if isinstance(item, Step):
            total += len(load_cache(workspace_root, method.name, item.name))
        elif isinstance(item, Group):
            for step in item.steps:
                total += len(load_cache(workspace_root, method.name, step.name))
    return total


# ---------------------------------------------------------------------------
# Method feature extraction
# ---------------------------------------------------------------------------

def _extract_all_steps(method: Method) -> tuple:
    """
    Walk method.items and return (steps, groups, removes).
    Steps nested inside groups are included in the steps list.
    """
    from core.models import Step, Group, Remove
    steps, groups, removes = [], [], []
    for item in method.items:
        if isinstance(item, Step):
            steps.append(item)
        elif isinstance(item, Group):
            groups.append(item)
            steps.extend(item.steps)
        elif isinstance(item, Remove):
            removes.append(item)
    return steps, groups, removes


def _count_constraint_types(steps: list) -> dict:
    """
    Count constraint lines by semantic type across all steps.
    Returns per-type counts plus constraint_type_diversity.
    """
    counts = {k: 0 for k in _CONSTRAINT_PREFIXES}
    for step in steps:
        for line in step.constraints:
            for category, prefixes in _CONSTRAINT_PREFIXES.items():
                if any(line.startswith(p) for p in prefixes):
                    counts[category] += 1
    diversity = sum(1 for v in counts.values() if v > 0)
    return {**counts, "constraint_type_diversity": diversity}


def method_vector(method: Method) -> dict:
    """
    Return the full ML feature vector for a method as a flat dict.

    Drop 'method_name' and 'score' before feeding to a model — they are
    identifier and label respectively, not features.

    To extend: add new fields here, to METHOD_FIELDNAMES, and if adding new
    constraint types, to _CONSTRAINT_PREFIXES.
    """
    steps, groups, removes = _extract_all_steps(method)

    constraint_counts = [len(s.constraints) for s in steps]
    total_constraints = sum(constraint_counts)
    avg_constraints   = round(total_constraints / len(steps), 2) if steps else 0
    max_constraints   = max(constraint_counts) if constraint_counts else 0

    type_counts = _count_constraint_types(steps)

    return {
        "method_name":                 method.name,
        "num_steps":                   len(steps),
        "num_groups":                  len(groups),
        "num_removes":                 len(removes),
        "total_constraints":           total_constraints,
        "avg_constraints_per_step":    avg_constraints,
        "max_constraints_per_step":    max_constraints,
        "num_cache_alg_steps":         sum(1 for s in steps if s.cache_alg),
        "num_free_layer_steps":        sum(1 for s in steps if s.free_layers),
        "symmetry_depth":              method.symmetry_depth,
        "num_symmetry_orientations":   len(method.symmetry_orientations),
        "num_edge_constraints":        type_counts["edge"],
        "num_corner_constraints":      type_counts["corner"],
        "num_orientation_constraints": type_counts["orientation"],
        "constraint_type_diversity":   type_counts["constraint_type_diversity"],
        "score":                       "",  # populated later by evaluate_solves
    }


def serialize_method(workspace_root: str, method: Method):
    """
    Write method_vector(method) to data/methods/methods.csv in workspace_root.
    Replaces the existing row for this method if present, appends if not.
    The 'score' column is preserved if already set; otherwise left empty.
    Called automatically by generate_solves.
    """
    _ensure_dirs(workspace_root)
    methods_csv = _methods_csv_path(workspace_root)
    row = method_vector(method)

    existing_rows = []
    if os.path.exists(methods_csv) and os.path.getsize(methods_csv) > 0:
        with open(methods_csv, newline="") as f:
            existing_rows = list(csv.DictReader(f))

    replaced = False
    for i, r in enumerate(existing_rows):
        if r["method_name"] == method.name:
            row["score"] = r.get("score", "")  # preserve existing score
            existing_rows[i] = row
            replaced = True
            break
    if not replaced:
        existing_rows.append(row)

    with open(methods_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METHOD_FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing_rows)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_method(eval_row: dict) -> float:
    """
    Default scoring function for a method. Higher is better.

    Takes an evaluation row dict (as produced by evaluate_solves) and returns
    a float score. Currently scores purely on solve efficiency: 1 / avg_total_moves.

    To use a custom scorer, pass a function with the same signature to
    evaluate_solves() via the `scorer` parameter. For example:

        def my_scorer(eval_row):
            moves = float(eval_row.get("avg_total_moves", 0))
            steps = int(eval_row.get("num_steps", 1))
            return round(1 / (moves * steps ** 0.5), 6) if moves > 0 else 0.0

        evaluate_solves(methods, workspace, scorer=my_scorer)
    """
    # avg_moves = float(eval_row.get("avg_total_moves", 0))
    # return round(1 / avg_moves, 6) if avg_moves > 0 else 0.0
    avg_moves = float(eval_row.get("avg_total_moves", 0))
    total     = int(eval_row.get("total_solves", 0))
    expected  = NUM_SCRAMBLES

    if avg_moves <= 0 or total == 0:
        return 0.0

    completion = min(total / expected, 1.0)

    # Completion penalty is quadratic — 80% completion = 0.64x score
    return round((1 / avg_moves) * (completion ** 2), 6)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_scrambles(num_scrambles: int) -> list:
    """Generate a list of random scramble strings."""
    return [" ".join(Scramble.Cube3x3x3()) for _ in range(num_scrambles)]


def _write_solves(method: Method, results: list[SolveResult], workspace_root: str):
    """
    Append a batch of SolveResults for one method to its solves CSV.
    Called by the main process only — never from workers.
    """
    if not results:
        return

    path        = _solves_path(workspace_root, method.name)
    file_exists = os.path.exists(path)
    step_cols   = _step_names(results[0])
    fieldnames  = ["scramble", "orientation"] + step_cols + ["total_moves"]

      # Drop failed results entirely — don't let them pollute the dataset
    valid_results = [r for r in results if not r.failed]
    if not valid_results:
        print(f"[WARN] All solves failed for '{method.name}', skipping write.")
        return

    # Optionally warn on partial failure
    if len(valid_results) < len(results):
        n = len(results) - len(valid_results)
        print(f"[WARN] {n}/{len(results)} solves failed for '{method.name}'.", flush=True)

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or os.path.getsize(path) == 0:
            writer.writeheader()
        for result in valid_results:
            row   = {"scramble": result.scramble, "orientation": result.orientation, "total_moves": 0}
            total = 0
            for step in result.steps:
                row[step.name]  = step.solution
                total          += _move_count(step.solution)
            row["total_moves"] = total
            writer.writerow(row)


def generate_solves(scrambles_list: list, method_list: list, workspace_root: str):
    """
    For each method, solve every scramble and append results to
    data/solves/<method_name>.csv. Also serializes each method's feature
    vector to methods.csv.

    Runs in parallel if parallel.enabled is true in config, otherwise
    falls back to sequential execution.

    Columns: scramble, orientation, <step_name>..., total_moves
    """
    _ensure_dirs(workspace_root)

    for method in method_list:
        serialize_method(workspace_root, method)

    if PARALLEL:
        _generate_solves_parallel(scrambles_list, method_list, workspace_root)
    else:
        _generate_solves_sequential(scrambles_list, method_list, workspace_root)


def _generate_solves_sequential(scrambles_list: list, method_list: list, workspace_root: str):
    """Sequential fallback for generate_solves."""
    runner = MethodRunner(
        solver_path=_solver_path(),
        workspace_root=workspace_root,
        timeout=TIMEOUT,
    )
    for method in method_list:
        results = [runner.run(method, scramble) for scramble in scrambles_list]
        _write_solves(method, results, workspace_root)

def _generate_solves_parallel(scrambles_list: list, method_list: list, workspace_root: str):
    """
    Parallel implementation of generate_solves.

    Streams results as they complete and writes each method's solves
    immediately once all its scrambles are done.
    """

    from collections import defaultdict

    tasks = [
        (method, scramble)
        for method in method_list
        for scramble in scrambles_list
    ]

    total_tasks = len(tasks)

    print(f"[parallel] Submitting {total_tasks} tasks "
          f"({len(method_list)} methods × {len(scrambles_list)} scrambles)")

    # Track progress + per-method accumulation
    method_map    = {m.name: m for m in method_list}
    method_data   = defaultdict(list)
    method_counts = defaultdict(int)

    completed = 0

# Smoke test — run one task sequentially before handing off to workers
    test_method, test_scramble = tasks[0]
    runner = MethodRunner(solver_path=_solver_path(), workspace_root=workspace_root, timeout=TIMEOUT)
    test_result = runner.run(test_method, test_scramble)
    print(f"[SMOKE TEST] {test_method.name}: {test_result}", flush=True)

    for method, result in run_parallel_solves(tasks, workspace_root):
        completed += 1
        method_name = method.name

        method_counts[method_name] += 1
        method_data[method_name].append(result)

        # Progress output (adjust frequency as needed)
        if completed % 50 == 0 or completed == total_tasks:
            print(f"[progress] {completed}/{total_tasks} solves completed", flush=True)

        # If this method is fully done → write immediately
        if method_counts[method_name] == len(scrambles_list):
            print(f"[WRITE] {method_name} ({method_counts[method_name]} solves)", flush=True)

            _write_solves(
                method_map[method_name],
                method_data[method_name],
                workspace_root
            )

            # Free memory immediately
            del method_data[method_name]
            del method_counts[method_name]

    # Final accounting
    if completed < total_tasks:
        print(f"[WARN] {total_tasks - completed} tasks failed or were skipped.")

    print(f"[parallel] {completed}/{total_tasks} solves completed.")

def generate_algorithms(method_list: list, num_solves: int, workspace_root: str):
    """
    Generate num_solves random scrambles and run solves for each method
    sequentially to warm the algorithm cache before parallel generation runs.

    Always runs sequentially — cache warming is the goal here, and
    concurrent writes during cold start add unnecessary risk.
    """
    runner = MethodRunner(
        solver_path=_solver_path(),
        workspace_root=workspace_root,
        timeout=TIMEOUT,
    )
    for method in method_list:
        for _ in range(num_solves):
            scramble = " ".join(Scramble.Cube3x3x3())
            runner.run(method, scramble)


def evaluate_solves(method_list: list, workspace_root: str, scorer=score_method):
    """
    Read data/solves/<method_name>.csv for each method and produce a combined
    evaluation CSV at data/evaluation/evaluation_<timestamp>.csv.

    Also updates each method's row in methods.csv with the computed score,
    using `scorer` to compute it. `scorer` must be a callable that accepts an
    eval row dict and returns a float. Defaults to score_method.

    Output columns: method, total_solves, avg_total_moves, num_steps,
                    avg_moves_per_step, num_algs, score
    """
    _ensure_dirs(workspace_root)
    rows = []

    for method in method_list:
        path = _solves_path(workspace_root, method.name)
        if not os.path.exists(path):
            print(f"[WARN] No solves file for '{method.name}' at {path}, skipping.")
            continue

        with open(path, newline="") as f:
            solve_rows = list(csv.DictReader(f))

        if not solve_rows:
            print(f"[WARN] Solves file for '{method.name}' is empty, skipping.")
            continue

        non_step_cols = {"scramble", "orientation", "total_moves"}
        step_cols     = [c for c in solve_rows[0].keys() if c not in non_step_cols]
        num_steps     = len(step_cols)

        total_moves_sum = 0
        for row in solve_rows:
            try:
                total_moves_sum += int(row["total_moves"])
            except (KeyError, ValueError):
                pass

        num_rows           = len(solve_rows)
        avg_total_moves    = round(total_moves_sum / num_rows, 2) if num_rows else 0
        avg_moves_per_step = round(avg_total_moves / num_steps, 2) if num_steps else 0

        eval_row = {
            "method":             method.name,
            "total_solves":       num_rows,
            "avg_total_moves":    avg_total_moves,
            "num_steps":          num_steps,
            "avg_moves_per_step": avg_moves_per_step,
            "num_algs":           _num_algs(workspace_root, method),
        }

        score            = scorer(eval_row)
        eval_row["score"] = score

        # Write score back into methods.csv
        methods_csv = _methods_csv_path(workspace_root)
        if os.path.exists(methods_csv) and os.path.getsize(methods_csv) > 0:
            with open(methods_csv, newline="") as f:
                method_rows = list(csv.DictReader(f))
            for r in method_rows:
                if r["method_name"] == method.name:
                    r["score"] = score
                    break
            with open(methods_csv, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=METHOD_FIELDNAMES)
                writer.writeheader()
                writer.writerows(method_rows)

        rows.append(eval_row)

    if not rows:
        print("[WARN] No data to evaluate.")
        return

    out_path   = _eval_path(workspace_root)
    fieldnames = ["method", "total_solves", "avg_total_moves", "num_steps",
                  "avg_moves_per_step", "num_algs", "score"]

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[OK] Evaluation written to {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _has_solves(workspace_root: str, method: Method) -> bool:
    path = _solves_path(workspace_root, method.name)
    return os.path.exists(path) and os.path.getsize(path) > 0

def main():
    default_ws = CONFIG["general"]["scratch_workspace"]
    workspace  = sys.argv[1] if len(sys.argv) > 1 else default_ws
    dsl_dir    = os.path.join(workspace, "dsl")

    print("[1/4] Loading methods...")
    methods = []
    for filename in os.listdir(dsl_dir):
        if not filename.endswith(".dsl"):
            continue

        path = os.path.join(dsl_dir, filename)

        try:
            method = method_from_file(path)
            methods.append(method)
        except Exception as e:
            print(f"[WARN] Failed to load {filename}: {e}")

    methods_no_solves = [m for m in methods if not _has_solves(workspace, m)]
    methods_solves = [m for m in methods if _has_solves(workspace, m)]

    methods = methods_no_solves
    print(f"[INFO] Loaded {len(methods)} methods.")

    # print(f"[2/4] Generating algorithms ({NUM_ALG_SOLVES} solves)...")
    # generate_algorithms(methods, num_solves=NUM_ALG_SOLVES, workspace_root=workspace)

    print(f"[3/4] Generating solves ({NUM_SCRAMBLES} scrambles)...")
    scrambles = generate_scrambles(NUM_SCRAMBLES)
    generate_solves(scrambles, methods, workspace_root=workspace)

    # methods = methods_solves
    print("[4/4] Evaluating solves...")
    evaluate_solves(methods, workspace_root=workspace)

    print("[DONE]")


if __name__ == "__main__":
    main()
