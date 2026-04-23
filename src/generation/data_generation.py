"""
data_generation.py — Data generation pipeline for the cube method solver.

Entry point:
    python -m generation.data_generation [workspace]

    workspace defaults to workspace/stable
"""

import os
import sys
import csv
import math
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

METHOD_FIELDNAMES = [
    "method_name",
    "num_steps",
    "num_groups",
    "num_removes",
    "total_constraints",
    "avg_constraints_per_step",
    "min_constraints_per_step",
    "max_constraints_per_step",
    "constraints_per_step_range",
    "constraints_per_step_std",
    "step_entropy",
    "num_cache_alg_steps",
    "num_free_layer_steps",
    "symmetry_depth",
    "num_symmetry_orientations",
    "total_step_face_overlap_score",
    "avg_step_face_overlap_score",
    "min_step_face_overlap_score",
    "max_step_face_overlap_score",
    "step_face_overlap_score_range",
    "step_face_overlap_score_std",
    "num_zero_face_overlap_steps",
    "fraction_zero_face_overlap_steps",
    "avg_distinct_faces_per_step",
    "min_distinct_faces_per_step",
    "max_distinct_faces_per_step",
    "num_edge_only_steps",
    "num_corner_only_steps",
    "num_mixed_piece_type_steps",
    "fraction_mixed_piece_type_steps",
    "avg_adjacent_step_face_overlap",
    "max_adjacent_step_face_overlap",
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

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))

def _step_count_entropy(counts: list[int]) -> float:
    """
    Entropy of the distribution of constraints across steps.

    Higher entropy means the method's constraints are distributed more evenly
    across steps. Lower entropy means they are concentrated in fewer steps.
    """
    total = sum(counts)
    if total <= 0:
        return 0.0

    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)

    return entropy


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


def _piece_from_constraint(line: str) -> str | None:
    """
    Extract piece token from a constraint line.

    Supported:
        add_edge UF
        add_corner UFR

    Returns None for non-piece constraints such as orientation constraints.
    """
    if line.startswith("add_edge ") or line.startswith("add_corner "):
        parts = line.split()
        if len(parts) >= 2:
            return parts[1].strip()
    return None


def _step_pieces(step) -> list[str]:
    """Return the list of piece strings in this step."""
    pieces = []
    for line in step.constraints:
        piece = _piece_from_constraint(line)
        if piece is not None:
            pieces.append(piece)
    return pieces


def _step_face_counts(step) -> dict[str, int]:
    """
    Count sticker-letter frequency across all pieces in a step.

    Example:
        UF, URB, UL  -> U:3, F:1, R:1, B:1, L:1
    """
    counts = defaultdict(int)
    for piece in _step_pieces(step):
        for face in piece:
            counts[face] += 1
    return dict(counts)


def _step_face_overlap_score(step) -> int:
    """
    Reward repeated face letters within a step.

    For each face:
        1 occurrence -> 0
        2 occurrences -> 1
        3 occurrences -> 2
        etc.

    Step score = sum(max(count - 1, 0) for each face).
    """
    counts = _step_face_counts(step)
    return sum(max(count - 1, 0) for count in counts.values())


def _step_distinct_face_count(step) -> int:
    """Number of distinct face letters touched by the step."""
    return len(_step_face_counts(step))


def _step_piece_type_profile(step) -> tuple[int, int]:
    """
    Return (#edge_piece_constraints, #corner_piece_constraints) for this step.
    Ignores non-piece constraints.
    """
    num_edges = 0
    num_corners = 0

    for piece in _step_pieces(step):
        if len(piece) == 2:
            num_edges += 1
        elif len(piece) == 3:
            num_corners += 1

    return num_edges, num_corners


def _step_face_set(step) -> set[str]:
    """Set of distinct faces used by the step."""
    return set(_step_face_counts(step).keys())


def _adjacent_step_face_overlaps(steps: list) -> list[int]:
    """
    For each adjacent pair of steps, measure face overlap as the size of the
    intersection of their face sets.
    """
    overlaps = []
    for i in range(len(steps) - 1):
        left_faces = _step_face_set(steps[i])
        right_faces = _step_face_set(steps[i + 1])
        overlaps.append(len(left_faces & right_faces))
    return overlaps


def method_vector(method: Method) -> dict:
    """
    Return the full ML feature vector for a method as a flat dict.

    Drop 'method_name' and 'score' before feeding to a model — they are
    identifier and label respectively, not features.
    """
    steps, groups, removes = _extract_all_steps(method)

    constraint_counts = [len(s.constraints) for s in steps]
    total_constraints = sum(constraint_counts)
    avg_constraints   = round(_mean(constraint_counts), 2) if steps else 0
    min_constraints   = min(constraint_counts) if constraint_counts else 0
    max_constraints   = max(constraint_counts) if constraint_counts else 0
    constraints_range = max_constraints - min_constraints if constraint_counts else 0
    constraints_std   = round(_std(constraint_counts), 2) if steps else 0
    step_entropy      = round(_step_count_entropy(constraint_counts), 4) if steps else 0

    face_overlap_scores = [_step_face_overlap_score(s) for s in steps]
    total_face_overlap  = sum(face_overlap_scores)
    avg_face_overlap    = round(_mean(face_overlap_scores), 2) if steps else 0
    min_face_overlap    = min(face_overlap_scores) if face_overlap_scores else 0
    max_face_overlap    = max(face_overlap_scores) if face_overlap_scores else 0
    face_overlap_range  = max_face_overlap - min_face_overlap if face_overlap_scores else 0
    face_overlap_std    = round(_std(face_overlap_scores), 2) if steps else 0
    zero_face_overlap_steps = sum(1 for score in face_overlap_scores if score == 0)
    frac_zero_face_overlap  = round(zero_face_overlap_steps / len(steps), 4) if steps else 0

    distinct_faces_per_step = [_step_distinct_face_count(s) for s in steps]
    avg_distinct_faces      = round(_mean(distinct_faces_per_step), 2) if steps else 0
    min_distinct_faces      = min(distinct_faces_per_step) if distinct_faces_per_step else 0
    max_distinct_faces      = max(distinct_faces_per_step) if distinct_faces_per_step else 0

    edge_only_steps = 0
    corner_only_steps = 0
    mixed_piece_type_steps = 0

    for step in steps:
        num_edges, num_corners = _step_piece_type_profile(step)
        if num_edges > 0 and num_corners == 0:
            edge_only_steps += 1
        elif num_corners > 0 and num_edges == 0:
            corner_only_steps += 1
        elif num_edges > 0 and num_corners > 0:
            mixed_piece_type_steps += 1

    frac_mixed_piece_type_steps = round(mixed_piece_type_steps / len(steps), 4) if steps else 0

    adjacent_face_overlaps = _adjacent_step_face_overlaps(steps)
    avg_adjacent_overlap   = round(_mean(adjacent_face_overlaps), 2) if adjacent_face_overlaps else 0
    max_adjacent_overlap   = max(adjacent_face_overlaps) if adjacent_face_overlaps else 0

    return {
        "method_name":                      method.name,
        "num_steps":                        len(steps),
        "num_groups":                       len(groups),
        "num_removes":                      len(removes),
        "total_constraints":                total_constraints,
        "avg_constraints_per_step":         avg_constraints,
        "min_constraints_per_step":         min_constraints,
        "max_constraints_per_step":         max_constraints,
        "constraints_per_step_range":       constraints_range,
        "constraints_per_step_std":         constraints_std,
        "step_entropy":                     step_entropy,
        "num_cache_alg_steps":              sum(1 for s in steps if s.cache_alg),
        "num_free_layer_steps":             sum(1 for s in steps if s.free_layers),
        "symmetry_depth":                   method.symmetry_depth,
        "num_symmetry_orientations":        len(method.symmetry_orientations),
        "total_step_face_overlap_score":    total_face_overlap,
        "avg_step_face_overlap_score":      avg_face_overlap,
        "min_step_face_overlap_score":      min_face_overlap,
        "max_step_face_overlap_score":      max_face_overlap,
        "step_face_overlap_score_range":    face_overlap_range,
        "step_face_overlap_score_std":      face_overlap_std,
        "num_zero_face_overlap_steps":      zero_face_overlap_steps,
        "fraction_zero_face_overlap_steps": frac_zero_face_overlap,
        "avg_distinct_faces_per_step":      avg_distinct_faces,
        "min_distinct_faces_per_step":      min_distinct_faces,
        "max_distinct_faces_per_step":      max_distinct_faces,
        "num_edge_only_steps":              edge_only_steps,
        "num_corner_only_steps":            corner_only_steps,
        "num_mixed_piece_type_steps":       mixed_piece_type_steps,
        "fraction_mixed_piece_type_steps":  frac_mixed_piece_type_steps,
        "avg_adjacent_step_face_overlap":   avg_adjacent_overlap,
        "max_adjacent_step_face_overlap":   max_adjacent_overlap,
        "score":                            "",  # populated later by evaluate_solves
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

# def score_method(eval_row: dict) -> float:
#     """
#     Default scoring function for a method. Higher is better.
#
#     Takes an evaluation row dict (as produced by evaluate_solves) and returns
#     a float score. Currently scores purely on solve efficiency: 1 / avg_total_moves.
#
#     To use a custom scorer, pass a function with the same signature to
#     evaluate_solves() via the `scorer` parameter. For example:
#
#         def my_scorer(eval_row):
#             moves = float(eval_row.get("avg_total_moves", 0))
#             steps = int(eval_row.get("num_steps", 1))
#             return round(1 / (moves * steps ** 0.5), 6) if moves > 0 else 0.0
#
#         evaluate_solves(methods, workspace, scorer=my_scorer)
#     """
#     avg_moves = float(eval_row.get("avg_total_moves", 0))
#     total     = int(eval_row.get("total_solves", 0))
#     expected  = NUM_SCRAMBLES
#
#     if avg_moves <= 0 or total == 0:
#         return 0.0
#
#     completion = min(total / expected, 1.0)
#
#     # Completion penalty is quadratic — 80% completion = 0.64x score
#     return round((1 / avg_moves) * (completion ** 2), 6)
def score_method(eval_row: dict) -> float:
    """
    Default scoring function for a method. Higher is better.

    Scores primarily on total move efficiency, but also penalizes methods whose
    average moves per step are too large, since those tend to be less human-
    practical even if the total move count looks good.

    Penalty design:
      - No penalty up to 7 avg moves/step
      - Above 7, penalty grows quadratically

    Completion penalty is still quadratic.
    """
    avg_total_moves = float(eval_row.get("avg_total_moves", 0))
    avg_moves_per_step = float(eval_row.get("avg_moves_per_step", 0))
    total = int(eval_row.get("total_solves", 0))
    expected = NUM_SCRAMBLES

    if avg_total_moves <= 0 or total == 0:
        return 0.0

    completion = min(total / expected, 1.0)
    base_score = 1 / avg_total_moves

    # Human-practicality penalty:
    # no penalty up to 7 avg moves/step, then quadratic growth
    threshold = 7.0
    penalty_strength = 0.15

    if avg_moves_per_step <= threshold:
        step_penalty = 1.0
    else:
        excess = avg_moves_per_step - threshold
        step_penalty = 1 / (1 + penalty_strength * (excess ** 2))

    return round(base_score * (completion ** 2) * step_penalty, 6)


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

        score             = scorer(eval_row)
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

    methods = [m for m in methods if not _has_solves(workspace, m)]
    # methods = [m for m in methods if _has_solves(workspace, m)]
    print(f"[INFO] Loaded {len(methods)} methods.")

    print(f"Generating solves ({NUM_SCRAMBLES} scrambles)...")
    scrambles = generate_scrambles(NUM_SCRAMBLES)
    generate_solves(scrambles, methods, workspace_root=workspace)

    print("[4/4] Evaluating solves...")
    evaluate_solves(methods, workspace_root=workspace)


if __name__ == "__main__":
    main()
