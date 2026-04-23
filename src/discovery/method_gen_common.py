import copy
import hashlib
import os
from typing import Optional

from core.models import Step, Group, Method
from core.dsl import method_to_dsl_text
from core.config import CONFIG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_CONSTRAINTS_PER_STEP = CONFIG["generation"]["min_constraints_per_step"]
MAX_CONSTRAINTS_PER_STEP = CONFIG["generation"]["max_constraints_per_step"]
TARGET_COUNT = CONFIG["generation"]["target_count"]

_ALL_EDGES = ["BL", "BR", "BU", "BD", "FL", "FR", "FU", "FD", "LU", "LD", "RU", "RD"]
_ALL_CORNERS = ["BLU", "BLD", "BRU", "BRD", "FLU", "FLD", "FRU", "FRD"]
_PIECE_POOL = _ALL_EDGES + _ALL_CORNERS  # Exactly 20 pieces


def _piece_line(piece: str) -> str:
    if len(piece) == 2:
        return f"add_edge {piece}"
    return f"add_corner {piece}"


def _line_to_piece(line: str) -> Optional[str]:
    if line.startswith("add_edge ") or line.startswith("add_corner "):
        parts = line.split()
        if len(parts) >= 2:
            return parts[1].strip()
    return None


def is_piece_constraint(line: str) -> bool:
    return _line_to_piece(line) is not None


def safe_method_to_dsl(method: Method) -> str:
    """Safely converts Method to DSL, handling potential int-symmetry issues."""
    orig_sym = method.symmetry_orientations
    if method.symmetry_orientations:
        method.symmetry_orientations = [str(s) for s in method.symmetry_orientations]
    try:
        text = method_to_dsl_text(method)
    finally:
        method.symmetry_orientations = orig_sym
    return text


def method_hash(method: Method) -> str:
    return hashlib.md5(safe_method_to_dsl(method).encode()).hexdigest()


def workspace_dsl_dir(workspace: str) -> str:
    return os.path.join(workspace, "dsl")


def load_seen_hashes_from_workspace(workspace: str) -> set[str]:
    """
    Hash all existing .dsl files in workspace/dsl by file contents.
    This lets random generation and mutation avoid colliding with methods already saved.
    """
    dsl_dir = workspace_dsl_dir(workspace)
    seen = set()

    if not os.path.isdir(dsl_dir):
        return seen

    for filename in os.listdir(dsl_dir):
        if not filename.endswith(".dsl"):
            continue
        path = os.path.join(dsl_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        seen.add(hashlib.md5(text.encode()).hexdigest())

    return seen


# ---------------------------------------------------------------------------
# Recursive step helpers
# ---------------------------------------------------------------------------

def _collect_leaf_steps_from_items(items: list) -> list[Step]:
    steps = []
    for item in items:
        if isinstance(item, Step):
            steps.append(item)
        elif isinstance(item, Group):
            steps.extend(_collect_leaf_steps_from_items(item.steps))
    return steps


def collect_leaf_steps(method: Method) -> list[Step]:
    """
    Return all executable leaf steps in method execution order, including
    steps nested inside groups.
    """
    return _collect_leaf_steps_from_items(method.items)


def step_piece_lists(method: Method) -> list[list[str]]:
    """
    Return the piece constraints for every leaf step as lists of piece strings.
    Non-piece constraints are ignored.
    """
    piece_lists = []
    for step in collect_leaf_steps(method):
        pieces = []
        for line in step.constraints:
            piece = _line_to_piece(line)
            if piece is not None:
                pieces.append(piece)
        piece_lists.append(pieces)
    return piece_lists


def step_piece_bounds(method: Method) -> list[tuple[int, int]]:
    """
    Per-step bounds for mutation.

    Rules:
      - steps with 0 piece constraints stay immutable: (0, 0)
      - otherwise min is 1, so piece-bearing steps can shrink but not disappear
      - max is at least the current piece count, and at least
        MAX_CONSTRAINTS_PER_STEP from config

    This lets existing methods like CFOP/ZZ mutate even if their piece-step
    sizes do not match the random-generator config exactly.
    """
    bounds = []
    for pieces in step_piece_lists(method):
        count = len(pieces)
        if count == 0:
            bounds.append((0, 0))
        else:
            bounds.append((1, max(MAX_CONSTRAINTS_PER_STEP, count)))
    return bounds


def method_has_mutable_pieces(method: Method) -> bool:
    return any(len(pieces) > 0 for pieces in step_piece_lists(method))


def rebuild_method_from_piece_lists(method: Method, piece_lists: list[list[str]]) -> Method:
    """
    Rebuild a method from piece lists while preserving:
      - method metadata
      - tree structure (groups, removes, directives, etc.)
      - step names / cache flags / free layers
      - all non-piece constraints in their original order

    Piece constraints are replaced as a block at the position of the first
    original piece constraint in that step.
    """
    child = copy.deepcopy(method)
    leaf_steps = collect_leaf_steps(child)

    if len(leaf_steps) != len(piece_lists):
        raise ValueError("Piece list count does not match number of leaf steps")

    for step, new_pieces in zip(leaf_steps, piece_lists):
        original = step.constraints
        piece_indices = [i for i, line in enumerate(original) if is_piece_constraint(line)]
        new_piece_lines = [_piece_line(p) for p in new_pieces]

        if not piece_indices:
            # No original piece constraints in this step.
            # Keep the step unchanged; mutation should not add pieces here.
            step.constraints = list(original)
            continue

        first_piece_idx = piece_indices[0]
        rebuilt = []
        inserted = False

        for i, line in enumerate(original):
            if i == first_piece_idx and not inserted:
                rebuilt.extend(new_piece_lines)
                inserted = True

            if not is_piece_constraint(line):
                rebuilt.append(line)

        if not inserted:
            rebuilt.extend(new_piece_lines)

        step.constraints = rebuilt

    return child
