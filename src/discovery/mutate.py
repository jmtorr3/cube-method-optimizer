import os
import random
import sys
from typing import Optional

from core.models import Method
from core.dsl import method_from_file, method_to_file
from core.config import CONFIG

from .method_gen_common import (
    TARGET_COUNT,
    step_piece_lists,
    step_piece_bounds,
    method_has_mutable_pieces,
    rebuild_method_from_piece_lists,
    method_hash,
    load_seen_hashes_from_workspace,
    workspace_dsl_dir,
)


# ---------------------------------------------------------------------------
# Internal mutation helpers
# ---------------------------------------------------------------------------

def _validate_piece_lists(piece_lists: list[list[str]], bounds: list[tuple[int, int]], total_piece_count: int) -> bool:
    if len(piece_lists) != len(bounds):
        return False

    for pieces, (lo, hi) in zip(piece_lists, bounds):
        n = len(pieces)
        if n < lo or n > hi:
            return False

    return sum(len(pieces) for pieces in piece_lists) == total_piece_count


def _mutable_step_indices(piece_lists: list[list[str]], bounds: list[tuple[int, int]]) -> list[int]:
    return [i for i, ((lo, hi), pieces) in enumerate(zip(bounds, piece_lists)) if hi > 0 and len(pieces) > 0]


def _mutate_move(piece_lists: list[list[str]], bounds: list[tuple[int, int]]) -> bool:
    """
    Move one piece constraint from one step to another.
    Respects per-step piece-count bounds.
    """
    src_candidates = []
    dst_candidates = []

    for i, (pieces, (lo, hi)) in enumerate(zip(piece_lists, bounds)):
        if hi == 0:
            continue
        if len(pieces) > lo:
            src_candidates.append(i)
        if len(pieces) < hi:
            dst_candidates.append(i)

    valid_pairs = [(src, dst) for src in src_candidates for dst in dst_candidates if src != dst]
    if not valid_pairs:
        return False

    src, dst = random.choice(valid_pairs)
    piece_idx = random.randrange(len(piece_lists[src]))
    piece = piece_lists[src].pop(piece_idx)
    piece_lists[dst].append(piece)
    return True


def _mutate_swap(piece_lists: list[list[str]], bounds: list[tuple[int, int]]) -> bool:
    """
    Swap one piece constraint between two different mutable steps.
    """
    candidates = _mutable_step_indices(piece_lists, bounds)
    if len(candidates) < 2:
        return False

    for _ in range(10):
        a, b = random.sample(candidates, 2)
        if not piece_lists[a] or not piece_lists[b]:
            continue

        ia = random.randrange(len(piece_lists[a]))
        ib = random.randrange(len(piece_lists[b]))

        if piece_lists[a][ia] == piece_lists[b][ib]:
            continue

        piece_lists[a][ia], piece_lists[b][ib] = piece_lists[b][ib], piece_lists[a][ia]
        return True

    return False


def _mutate_replace_from_donor(piece_lists: list[list[str]], donor_piece_lists: list[list[str]], bounds: list[tuple[int, int]]) -> bool:
    """
    Replace one child piece constraint with one donor piece constraint.

    This is the safest interpretation of "pieces can also be exchanged between
    methods" because it:
      - works even if the two methods have different numbers of steps
      - preserves the child's step structure and piece-count totals
      - allows donor pieces to enter the child
    """
    child_candidates = _mutable_step_indices(piece_lists, bounds)
    donor_candidates = [i for i, pieces in enumerate(donor_piece_lists) if pieces]

    if not child_candidates or not donor_candidates:
        return False

    for _ in range(20):
        child_step = random.choice(child_candidates)
        donor_step = random.choice(donor_candidates)

        child_idx = random.randrange(len(piece_lists[child_step]))
        donor_piece = random.choice(donor_piece_lists[donor_step])

        if piece_lists[child_step][child_idx] == donor_piece:
            continue

        piece_lists[child_step][child_idx] = donor_piece
        return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mutate_method(parent: Method, donor: Optional[Method] = None, num_mutations: Optional[int] = None) -> Method:
    """
    Create a mutated child from an existing method.

    Mutation operates on leaf-step piece constraints only.
    Non-piece constraints, group structure, step names, directives, cache flags,
    and free-layer settings are all preserved.

    Supported mutations:
      - move: move a piece constraint between steps
      - swap: swap piece constraints between steps
      - donor_replace: replace one child piece with one donor piece
    """
    child_piece_lists = step_piece_lists(parent)
    bounds = step_piece_bounds(parent)
    total_piece_count = sum(len(pieces) for pieces in child_piece_lists)

    if total_piece_count == 0:
        raise ValueError("Parent method has no mutable piece constraints")

    donor_piece_lists = step_piece_lists(donor) if donor is not None else None

    if num_mutations is None:
        num_mutations = random.randint(1, 3)

    changed = False

    for _ in range(num_mutations):
        ops = ["move", "swap"]
        if donor_piece_lists:
            ops.append("donor_replace")

        random.shuffle(ops)

        for op in ops:
            snapshot = [list(step) for step in child_piece_lists]

            if op == "move":
                applied = _mutate_move(child_piece_lists, bounds)
            elif op == "swap":
                applied = _mutate_swap(child_piece_lists, bounds)
            else:
                applied = _mutate_replace_from_donor(child_piece_lists, donor_piece_lists, bounds)

            if applied and _validate_piece_lists(child_piece_lists, bounds, total_piece_count):
                changed = True
                break

            child_piece_lists = snapshot

    if not changed:
        # Still rebuild for consistency, but the caller will usually filter this out
        return rebuild_method_from_piece_lists(parent, child_piece_lists)

    return rebuild_method_from_piece_lists(parent, child_piece_lists)


def mutate_methods(method_list: list[Method], num_new_methods: int, seen_hashes: set[str]) -> list[Method]:
    """
    Generate num_new_methods unique mutated children from method_list.

    Newly created children are immediately added back into the parent pool so
    they can be selected again for further mutation.
    """
    if not method_list:
        raise ValueError("mutate_methods requires at least one source method")

    population = list(method_list)
    children = []

    attempts = 0
    max_attempts = max(5000, num_new_methods * 50)

    while len(children) < num_new_methods:
        attempts += 1
        if attempts > max_attempts:
            raise RuntimeError(
                f"Only generated {len(children)}/{num_new_methods} unique mutations "
                f"after {attempts} attempts"
            )

        parent = random.choice(population)

        donor = None
        if len(population) >= 2 and random.random() < 0.7:
            donor_candidates = [m for m in population if m is not parent]
            if donor_candidates:
                donor = random.choice(donor_candidates)

        child = mutate_method(parent, donor=donor)
        m_hash = method_hash(child)

        if m_hash == method_hash(parent):
            continue
        if m_hash in seen_hashes:
            continue

        seen_hashes.add(m_hash)
        child.name = f"mut_{m_hash[:8]}"
        children.append(child)
        population.append(child)  # immediately reselection-eligible

    return children


# ---------------------------------------------------------------------------
# Workspace loading
# ---------------------------------------------------------------------------

def _load_workspace_methods(workspace: str) -> list[Method]:
    dsl_dir = workspace_dsl_dir(workspace)
    methods = []

    if not os.path.isdir(dsl_dir):
        return methods

    for filename in os.listdir(dsl_dir):
        if not filename.endswith(".dsl"):
            continue

        path = os.path.join(dsl_dir, filename)
        try:
            method = method_from_file(path)
        except Exception as e:
            print(f"[WARN] Failed to load {filename}: {e}")
            continue

        if not method_has_mutable_pieces(method):
            print(f"[WARN] Skipping non-mutable method {filename}")
            continue

        methods.append(method)

    return methods


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    default_ws = CONFIG["general"]["scratch_workspace"]
    workspace = sys.argv[1] if len(sys.argv) > 1 else default_ws

    dsl_dir = workspace_dsl_dir(workspace)
    os.makedirs(dsl_dir, exist_ok=True)

    print("[1/3] Loading base methods...")
    methods = _load_workspace_methods(workspace)

    if not methods:
        raise RuntimeError(f"No mutable methods found in {dsl_dir}")

    print(f"[INFO] Loaded {len(methods)} base methods.")

    print(f"[2/3] Generating {TARGET_COUNT} mutations...")
    seen_hashes = load_seen_hashes_from_workspace(workspace)
    children = mutate_methods(methods, TARGET_COUNT, seen_hashes)

    print("[3/3] Saving mutated methods...")
    for i, method in enumerate(children, start=1):
        method_to_file(method, workspace)

        if i % 100 == 0:
            print(f"  -> Saved {i}/{TARGET_COUNT}")

    print(f"[DONE] Saved {len(children)} mutated methods to {dsl_dir}")
