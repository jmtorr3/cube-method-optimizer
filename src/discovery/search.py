"""
search.py - Orchestrates a model-guided hill-climbing discovery loop.

The search loop treats the trained ML model as an oracle: methods are scored
from their feature vector without running solves, then the best predicted
candidate is mutated to produce the next frontier.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import itertools
import os
from dataclasses import dataclass

import numpy as np

from core.dsl import method_from_file
from core.models import Method
from core.config import CONFIG
from core.rotation import orientation_rotation_string
from generation.data_generation import evaluate_solves, generate_scrambles, generate_solves
from ml.features import extract_from_method
from ml.predict import _predict_from_model, load_model, predict

from .method_gen_common import (
    method_has_mutable_pieces,
    workspace_dsl_dir,
)
from .mutate import mutate_method


DISCOVERY_CONFIG = CONFIG.get("discovery", {})
DEFAULT_WORKSPACE = DISCOVERY_CONFIG.get("workspace", "workspace/hillclimb")
DEFAULT_SEED_WORKSPACE = DISCOVERY_CONFIG.get("seed_workspace", DEFAULT_WORKSPACE)
DEFAULT_MAX_METHODS = DISCOVERY_CONFIG.get("max_methods", 10000)
DEFAULT_MAX_SEED_METHODS = DISCOVERY_CONFIG.get("max_seed_methods", 250)
DEFAULT_MUTATIONS_PER_METHOD = DISCOVERY_CONFIG.get("mutations_per_method", 18)
DEFAULT_MUTATION_STRENGTH = DISCOVERY_CONFIG.get("mutation_strength", 3)
DEFAULT_VERIFY_TOP_N = DISCOVERY_CONFIG.get("verify_top_n", 20)
DEFAULT_VERIFY_NUM_SCRAMBLES = DISCOVERY_CONFIG.get("verify_num_scrambles", 10)


@dataclass
class ScoredMethod:
    method: Method
    score: float
    method_hash: str
    parent_hash: str = ""
    depth: int = 0
    source: str = "mutated"


class MethodQueue:
    """Max-priority queue keyed by predicted score."""

    def __init__(self):
        self._heap = []
        self._counter = itertools.count()

    def push(self, scored: ScoredMethod):
        heapq.heappush(self._heap, (-scored.score, next(self._counter), scored))

    def pop(self) -> ScoredMethod:
        return heapq.heappop(self._heap)[2]

    def __len__(self) -> int:
        return len(self._heap)


def _method_to_search_dsl(method: Method) -> str:
    """
    Serialize a method to parser-compatible DSL for discovery output.

    The core parser stores symmetry orientations as numeric indices, but the
    DSL parser accepts macros or rotation strings. Convert indices back to
    canonical rotation strings on write.
    """
    from core.dsl import method_to_dsl_text

    original_symmetry = method.symmetry_orientations
    normalized = []
    for value in original_symmetry:
        if isinstance(value, int):
            normalized.append(orientation_rotation_string(value))
            continue
        if isinstance(value, str) and value.isdigit():
            normalized.append(orientation_rotation_string(int(value)))
            continue
        normalized.append(str(value))

    method.symmetry_orientations = normalized
    try:
        return method_to_dsl_text(method)
    finally:
        method.symmetry_orientations = original_symmetry


def search_method_hash(method: Method) -> str:
    """
    Hash the method structure while ignoring method.name.

    Discovery renames generated methods, so name-sensitive hashes would let
    identical methods re-enter the search under different names.
    """
    original_name = method.name
    method.name = "__canonical_method__"
    try:
        return hashlib.md5(_method_to_search_dsl(method).encode()).hexdigest()
    finally:
        method.name = original_name


def get_method_score(method: Method, workspace_root: str = DEFAULT_WORKSPACE) -> float:
    """
    Score a method using the trained ML model in workspace_root.

    Higher is better, matching generation.data_generation.score_method.
    """
    score = predict(method, workspace_root)
    if score is None:
        raise RuntimeError(
            f"No ML model available for {workspace_root}. "
            "Run `python -m ml.train <workspace>` before search."
        )
    return float(score)


def get_method_scores(methods: list[Method], workspace_root: str = DEFAULT_WORKSPACE) -> list[float]:
    """Score methods in one model call when the artifact supports batching."""
    model = load_model(workspace_root)
    if model is None:
        raise RuntimeError(
            f"No ML model available for {workspace_root}. "
            "Run `python -m ml.train <workspace>` before search."
        )

    if model.get("model_type") == "random_forest":
        rows = np.asarray([extract_from_method(method) for method in methods])
        return [float(score) for score in model["estimator"].predict(rows)]

    return [_predict_from_model(model, extract_from_method(method)) for method in methods]


def add_methods(
    method_scores: MethodQueue,
    new_methods: list[Method],
    seen_hashes: set[str],
    workspace_root: str,
    parent_hash: str = "",
    depth: int = 0,
    source: str = "mutated",
) -> list[ScoredMethod]:
    """
    Score and enqueue new unique methods.

    seen_hashes is updated in-place so the same DSL is never scored twice in
    one search run.
    """
    unique_methods = []
    unique_hashes = []

    for method in new_methods:
        m_hash = search_method_hash(method)
        if m_hash in seen_hashes:
            continue

        seen_hashes.add(m_hash)
        unique_methods.append(method)
        unique_hashes.append(m_hash)

    if not unique_methods:
        return []

    scores = get_method_scores(unique_methods, workspace_root)
    added = []

    for method, m_hash, score in zip(unique_methods, unique_hashes, scores):
        scored = ScoredMethod(
            method=method,
            score=score,
            method_hash=m_hash,
            parent_hash=parent_hash,
            depth=depth,
            source=source,
        )
        method_scores.push(scored)
        added.append(scored)

    return added


def mutate_method_batch(
    method: Method,
    num_mutations: int = DEFAULT_MUTATIONS_PER_METHOD,
    mutation_strength: int = DEFAULT_MUTATION_STRENGTH,
) -> list[Method]:
    """Generate a batch of children from one parent method."""
    children = []
    for _ in range(num_mutations):
        child = mutate_method(method, num_mutations=mutation_strength)
        child_hash = search_method_hash(child)
        child.name = f"hill_{child_hash[:8]}"
        children.append(child)
    return children


def export_method(scored: ScoredMethod, workspace_root: str) -> str:
    """
    Write a discovered method under workspace_root/dsl.

    The filename includes rank signal and hash so repeated runs do not collide
    on method.name alone.
    """
    dsl_dir = workspace_dsl_dir(workspace_root)
    os.makedirs(dsl_dir, exist_ok=True)

    score_part = f"{scored.score:.8f}".replace(".", "p")
    filename = f"{score_part}_{scored.method_hash[:12]}.dsl"
    path = os.path.join(dsl_dir, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(_method_to_search_dsl(scored.method))
        f.write("\n")

    return path


def output_group_stats(examined_methods: list[ScoredMethod], workspace_root: str) -> str:
    """Write one summary row per examined method."""
    out_dir = os.path.join(workspace_root, "data", "discovery")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "hillclimb_results.csv")

    fieldnames = ["rank", "method_name", "predicted_score", "method_hash", "parent_hash", "depth", "source"]
    rows = sorted(examined_methods, key=lambda item: item.score, reverse=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, scored in enumerate(rows, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "method_name": scored.method.name,
                    "predicted_score": f"{scored.score:.10f}",
                    "method_hash": scored.method_hash,
                    "parent_hash": scored.parent_hash,
                    "depth": scored.depth,
                    "source": scored.source,
                }
            )

    return path


def load_methods(dsl_dir: str, max_methods: int | None = None) -> list[Method]:
    """Load mutable DSL methods from a directory."""
    methods = []
    if not os.path.isdir(dsl_dir):
        raise FileNotFoundError(f"DSL directory not found: {dsl_dir}")

    for filename in sorted(os.listdir(dsl_dir)):
        if not filename.endswith(".dsl"):
            continue

        path = os.path.join(dsl_dir, filename)
        try:
            method = load_method(path)
        except Exception as e:
            print(f"[WARN] Failed to load {filename}: {e}")
            continue

        if not method_has_mutable_pieces(method):
            continue

        methods.append(method)
        if max_methods is not None and len(methods) >= max_methods:
            break

    return methods


def _methods_csv_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, "data", "methods", "methods.csv")


def _load_scored_method_names(workspace_root: str) -> list[str]:
    """Return method names ordered by known score descending."""
    path = _methods_csv_path(workspace_root)
    if not os.path.exists(path):
        return []

    scored = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            method_name = row.get("method_name", "").strip()
            score_text = row.get("score", "").strip()
            if not method_name or not score_text:
                continue
            try:
                scored.append((float(score_text), method_name))
            except ValueError:
                continue

    return [name for _, name in sorted(scored, reverse=True)]


def load_seed_methods(seed_workspace: str, max_methods: int | None = None) -> list[Method]:
    """
    Load seed methods, preferring methods that already have actual scores.

    These seeds guide the search but are not counted as discovered methods.
    """
    dsl_dir = workspace_dsl_dir(seed_workspace)
    methods = []
    seen_names = set()

    for name in _load_scored_method_names(seed_workspace):
        path = os.path.join(dsl_dir, f"{name}.dsl")
        if not os.path.exists(path):
            continue

        try:
            method = load_method(path)
        except Exception as e:
            print(f"[WARN] Failed to load scored seed {name}: {e}")
            continue

        if not method_has_mutable_pieces(method):
            continue

        methods.append(method)
        seen_names.add(method.name)
        if max_methods is not None and len(methods) >= max_methods:
            return methods

    for method in load_methods(dsl_dir):
        if method.name in seen_names:
            continue
        methods.append(method)
        if max_methods is not None and len(methods) >= max_methods:
            break

    return methods


def load_method(path: str) -> Method:
    """Load one DSL file as a Method object."""
    return method_from_file(path)


def find_method(
    methods: list[Method],
    max_methods: int,
    workspace_root: str = DEFAULT_WORKSPACE,
    mutations_per_method: int = DEFAULT_MUTATIONS_PER_METHOD,
    mutation_strength: int = DEFAULT_MUTATION_STRENGTH,
) -> list[ScoredMethod]:
    """
    Explore method mutations, always expanding the best predicted candidate.

    Returns examined methods sorted best-first and writes each examined method
    plus a summary CSV into workspace_root.
    """
    if max_methods < 1:
        raise ValueError("max_methods must be >= 1")
    if not methods:
        raise ValueError("find_method requires at least one seed method")

    examined_hashes = set()
    queued_hashes = set()
    method_scores = MethodQueue()

    add_methods(
        method_scores,
        methods,
        queued_hashes,
        workspace_root=workspace_root,
        depth=0,
        source="seed",
    )

    examined_methods = []

    while len(examined_methods) < max_methods and len(method_scores) > 0:
        scored = method_scores.pop()
        if scored.method_hash in examined_hashes:
            continue

        examined_hashes.add(scored.method_hash)
        if scored.source != "seed":
            examined_methods.append(scored)
            export_method(scored, workspace_root)

            if len(examined_methods) % 500 == 0:
                print(f"[progress] {len(examined_methods)}/{max_methods} oracle-scored methods", flush=True)

        children = mutate_method_batch(
            scored.method,
            num_mutations=mutations_per_method,
            mutation_strength=mutation_strength,
        )
        add_methods(
            method_scores,
            children,
            queued_hashes,
            workspace_root=workspace_root,
            parent_hash=scored.method_hash,
            depth=scored.depth + 1,
        )

    output_group_stats(examined_methods, workspace_root)
    return sorted(examined_methods, key=lambda item: item.score, reverse=True)


def _latest_evaluation_path(workspace_root: str) -> str | None:
    eval_dir = os.path.join(workspace_root, "data", "evaluation")
    if not os.path.isdir(eval_dir):
        return None

    candidates = [
        os.path.join(eval_dir, filename)
        for filename in os.listdir(eval_dir)
        if filename.endswith(".csv")
    ]
    if not candidates:
        return None

    return max(candidates, key=os.path.getmtime)


def verify_top_methods(
    scored_methods: list[ScoredMethod],
    workspace_root: str,
    top_n: int = DEFAULT_VERIFY_TOP_N,
    num_scrambles: int = DEFAULT_VERIFY_NUM_SCRAMBLES,
) -> str | None:
    """Run real solves for the top predicted methods and write actual scores."""
    if top_n <= 0 or num_scrambles <= 0 or not scored_methods:
        return None

    top_scored = sorted(scored_methods, key=lambda item: item.score, reverse=True)[:top_n]
    methods = [item.method for item in top_scored]
    predicted_by_name = {item.method.name: item.score for item in top_scored}

    print(f"[verify] Generating {num_scrambles} solves for top {len(methods)} methods", flush=True)
    scrambles = generate_scrambles(num_scrambles)
    generate_solves(scrambles, methods, workspace_root=workspace_root)
    evaluate_solves(methods, workspace_root=workspace_root)

    eval_path = _latest_evaluation_path(workspace_root)
    if eval_path is None:
        return None

    out_dir = os.path.join(workspace_root, "data", "discovery")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "hillclimb_top_actual_scores.csv")

    with open(eval_path, newline="", encoding="utf-8") as f:
        eval_rows = [
            row for row in csv.DictReader(f)
            if row.get("method", "").strip() in predicted_by_name
        ]

    eval_rows.sort(key=lambda row: float(row.get("score", 0) or 0), reverse=True)
    fieldnames = [
        "actual_rank",
        "method",
        "predicted_score",
        "actual_score",
        "avg_total_moves",
        "num_steps",
        "avg_moves_per_step",
        "total_solves",
        "num_algs",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, row in enumerate(eval_rows, start=1):
            method_name = row["method"]
            writer.writerow(
                {
                    "actual_rank": rank,
                    "method": method_name,
                    "predicted_score": f"{predicted_by_name[method_name]:.10f}",
                    "actual_score": row.get("score", ""),
                    "avg_total_moves": row.get("avg_total_moves", ""),
                    "num_steps": row.get("num_steps", ""),
                    "avg_moves_per_step": row.get("avg_moves_per_step", ""),
                    "total_solves": row.get("total_solves", ""),
                    "num_algs": row.get("num_algs", ""),
                }
            )

    return out_path


def main():
    workspace = DEFAULT_WORKSPACE
    seed_workspace = DEFAULT_SEED_WORKSPACE

    methods = load_seed_methods(seed_workspace, max_methods=DEFAULT_MAX_SEED_METHODS)
    print(f"[seeds] Loaded {len(methods)} seed methods from {seed_workspace}", flush=True)

    results = find_method(
        methods,
        max_methods=DEFAULT_MAX_METHODS,
        workspace_root=workspace,
        mutations_per_method=DEFAULT_MUTATIONS_PER_METHOD,
        mutation_strength=DEFAULT_MUTATION_STRENGTH,
    )

    best = results[0]
    stats_path = os.path.join(workspace, "data", "discovery", "hillclimb_results.csv")
    print(f"[DONE] Examined {len(results)} methods.", flush=True)
    print(f"[BEST] {best.method.name} score={best.score:.10f} hash={best.method_hash}", flush=True)
    print(f"[STATS] {stats_path}", flush=True)

    actual_path = verify_top_methods(
        results,
        workspace_root=workspace,
        top_n=DEFAULT_VERIFY_TOP_N,
        num_scrambles=DEFAULT_VERIFY_NUM_SCRAMBLES,
    )
    if actual_path is not None:
        print(f"[ACTUAL] {actual_path}", flush=True)


if __name__ == "__main__":
    main()
