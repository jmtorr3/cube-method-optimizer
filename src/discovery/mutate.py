# """
# mutate.py — Method mutation and generation logic.
#
# Generates new Method objects or DSL files by mutating existing ones.
# Writes generated DSLs to workspace/scratch/dsl/.
#
# Design philosophy:
#     Every valid method must collectively place all 20 pieces of the cube
#     (12 edges + 8 corners) across its steps. Mutations preserve this
#     invariant by operating on a piece-coverage model rather than raw
#     constraint strings. Steps are kept small and face-coherent so the
#     solver can find solutions quickly. Pathological methods are rejected
#     before entering the mutation pool.
#
# Key constraints enforced:
#     - All 20 pieces placed exactly once across all steps (no gaps, no overlap)
#     - Orientation constraints (add_edges_orientation / add_corners_orientation)
#       are tracked separately and may appear freely alongside placement
#     - Max constraints per step (default 5)
#     - Steps are never left empty
# """
#
# import copy
# import random
# import hashlib
# import os
# from collections import defaultdict
# from typing import Optional
#
# from core.models import Step, Group, Remove, Method
# from core.dsl import method_from_file, method_to_file, method_to_dsl_text
#
#
# # ---------------------------------------------------------------------------
# # Tunables
# # ---------------------------------------------------------------------------
#
# MAX_CONSTRAINTS_PER_STEP = 5    # hard cap on placement constraints per step
# MAX_MUTATION_ATTEMPTS    = 300  # give up after this many consecutive failures
#
#
# # ---------------------------------------------------------------------------
# # Cube piece universe
# # ---------------------------------------------------------------------------
#
# # All 12 edges and 8 corners of a 3x3 cube.
# # Stored in canonical form (alphabetically sorted, uppercase).
#
# _ALL_EDGES: list[str] = [
#     "BL", "BR", "BU", "BD",
#     "FL", "FR", "FU", "FD",
#     "LU", "LD",
#     "RU", "RD",
# ]
#
# _ALL_CORNERS: list[str] = [
#     "BLU", "BLD", "BRU", "BRD",
#     "FLU", "FLD", "FRU", "FRD",
# ]
#
# _ALL_PIECES: set[str] = set(_ALL_EDGES) | set(_ALL_CORNERS)
#
#
# def _canonical(piece: str) -> str:
#     """Canonical form: sorted letters, uppercased."""
#     return "".join(sorted(piece.upper()))
#
#
# def _is_edge(piece: str) -> bool:
#     return len(piece) == 2
#
#
# def _face(piece: str) -> str:
#     """Dominant face: first letter of canonical piece name."""
#     return piece[0] if piece else "?"
#
#
# def _piece_line(piece: str) -> str:
#     """Constraint line for a specific piece."""
#     if _is_edge(piece):
#         return f"add_edge {piece}"
#     return f"add_corner {piece}"
#
#
# # ---------------------------------------------------------------------------
# # Constraint parsing
# # ---------------------------------------------------------------------------
#
# def _parse_placement(line: str) -> Optional[str]:
#     """
#     If line is a specific-piece placement, return canonical piece name.
#     Returns None for wildcards, orientation lines, and everything else.
#     """
#     parts = line.strip().split()
#     if len(parts) == 2 and parts[0] in ("add_edge", "add_corner"):
#         return _canonical(parts[1])
#     return None
#
#
# def _is_orientation_line(line: str) -> bool:
#     return line.strip().startswith(("add_edges_orientation", "add_corners_orientation"))
#
#
# def _is_wildcard_line(line: str) -> bool:
#     parts = line.strip().split()
#     return len(parts) == 1 and parts[0] in ("add_edges", "add_corners")
#
#
# def _pieces_placed_by(constraints: list[str]) -> set[str]:
#     """
#     Set of canonical pieces placed by a constraint list.
#     Wildcards expand to their full set. Orientation lines are ignored.
#     """
#     placed = set()
#     for line in constraints:
#         if _is_wildcard_line(line):
#             parts = line.strip().split()
#             if parts[0] == "add_edges":
#                 placed.update(_ALL_EDGES)
#             else:
#                 placed.update(_ALL_CORNERS)
#         else:
#             p = _parse_placement(line)
#             if p is not None:
#                 placed.add(p)
#     return placed
#
#
# def _placement_lines(constraints: list[str]) -> list[str]:
#     """Placement constraints only (specific + wildcard, not orientation)."""
#     return [c for c in constraints if not _is_orientation_line(c)]
#
#
# def _orientation_lines(constraints: list[str]) -> list[str]:
#     return [c for c in constraints if _is_orientation_line(c)]
#
#
# # ---------------------------------------------------------------------------
# # Method-level coverage helpers
# # ---------------------------------------------------------------------------
#
# def _all_steps(method: Method) -> list[Step]:
#     steps = []
#     for item in method.items:
#         if isinstance(item, Step):
#             steps.append(item)
#         elif isinstance(item, Group):
#             steps.extend(item.steps)
#     return steps
#
#
# def _method_placed_pieces(method: Method) -> set[str]:
#     placed = set()
#     for step in _all_steps(method):
#         placed |= _pieces_placed_by(step.constraints)
#     return placed
#
#
# def _is_complete(method: Method) -> bool:
#     return _method_placed_pieces(method) == _ALL_PIECES
#
#
# def _missing_pieces(method: Method) -> set[str]:
#     return _ALL_PIECES - _method_placed_pieces(method)
#
#
# def _duplicate_pieces(method: Method) -> set[str]:
#     seen:  set[str] = set()
#     dupes: set[str] = set()
#     for step in _all_steps(method):
#         placed = _pieces_placed_by(step.constraints)
#         dupes |= placed & seen
#         seen  |= placed
#     return dupes
#
#
# # ---------------------------------------------------------------------------
# # Step naming
# # ---------------------------------------------------------------------------
#
# def _step_name(step: Step) -> str:
#     pieces = _pieces_placed_by(step.constraints)
#     if not pieces:
#         return "Step_GEN"
#     return "Step_" + "_".join(sorted(pieces))
#
#
# # ---------------------------------------------------------------------------
# # Viability gate
# # ---------------------------------------------------------------------------
#
# def _is_viable(method: Method) -> bool:
#     """
#     True if the method is structurally valid and solver-friendly.
#
#     Requirements:
#         - At least one step
#         - No empty steps
#         - No step exceeds MAX_CONSTRAINTS_PER_STEP placements
#         - All 20 pieces placed exactly once (no gaps, no overlap)
#     """
#     steps = _all_steps(method)
#     if not steps:
#         return False
#
#     for step in steps:
#         pl = _placement_lines(step.constraints)
#         if not pl:
#             return False
#         if len(pl) > MAX_CONSTRAINTS_PER_STEP:
#             return False
#
#     if _duplicate_pieces(method):
#         return False
#
#     if not _is_complete(method):
#         return False
#
#     return True
#
#
# # ---------------------------------------------------------------------------
# # Coverage repair
# # ---------------------------------------------------------------------------
#
# def _fix_coverage(method: Method):
#     """
#     Mutate `method` in-place so every piece is placed exactly once.
#
#     Pass 1 — deduplicate: keep each piece only in the first step that has it.
#     Pass 2 — fill gaps: place missing pieces into steps with room, preferring
#               face-coherent fit.
#     """
#     steps = _all_steps(method)
#
#     # Pass 1: remove duplicates
#     seen: set[str] = set()
#     for step in steps:
#         new_pl = []
#         for line in _placement_lines(step.constraints):
#             piece = _parse_placement(line)
#             if piece is None or piece not in seen:
#                 new_pl.append(line)
#                 if piece:
#                     seen.add(piece)
#         step.constraints = new_pl + _orientation_lines(step.constraints)
#
#     # Pass 2: fill missing pieces
#     missing = list(_ALL_PIECES - seen)
#     random.shuffle(missing)
#
#     for piece in missing:
#         best_step  = None
#         best_score = -1
#
#         for step in steps:
#             room = MAX_CONSTRAINTS_PER_STEP - len(_placement_lines(step.constraints))
#             if room <= 0:
#                 continue
#             # Prefer steps that already have pieces on the same face
#             same_face = sum(
#                 1 for p in _pieces_placed_by(step.constraints)
#                 if _face(p) == _face(piece)
#             )
#             if same_face > best_score:
#                 best_score = same_face
#                 best_step  = step
#
#         if best_step is None:
#             # No existing step has room — add a new one
#             # new_step = Step(
#             #     name=f"Step_{piece}",
#             #     constraints=[_piece_line(piece)],
#             #     cache_alg=False,
#             #     free_layers=[],
#             # )
#             new_step = Step(name=f"Step_{piece}")
#
#             new_step.constraints = [_piece_line(piece)]
#             new_step.cache_alg = False
#             new_step.free_layers = []
#             method.items.append(new_step)
#         else:
#             best_step.constraints.append(_piece_line(piece))
#             best_step.name = _step_name(best_step)
#
#
# # ---------------------------------------------------------------------------
# # Coherence-biased piece sampling
# # ---------------------------------------------------------------------------
#
# def _coherent_sample(pieces: list[str], max_count: int) -> list[str]:
#     """
#     Pick up to max_count pieces, biased toward a shared face.
#     """
#     if len(pieces) <= max_count:
#         return pieces[:]
#
#     by_face: dict[str, list[str]] = defaultdict(list)
#     for p in pieces:
#         by_face[_face(p)].append(p)
#
#     anchor_face = max(by_face, key=lambda f: len(by_face[f]))
#     anchor = by_face[anchor_face][:]
#     random.shuffle(anchor)
#
#     rest = [p for f, ps in by_face.items() if f != anchor_face for p in ps]
#     random.shuffle(rest)
#
#     return (anchor + rest)[:max_count]
#
#
# # ---------------------------------------------------------------------------
# # Atomic mutations
# # ---------------------------------------------------------------------------
#
# def _mutate_redistribute(method: Method) -> Method:
#     """
#     Collect all 20 pieces, shuffle them, and redistribute across existing
#     steps while respecting the per-step cap and face coherence.
#     This is the primary exploration mutation.
#     """
#     m     = copy.deepcopy(method)
#     steps = _all_steps(m)
#
#     all_pieces = list(_ALL_PIECES)
#     random.shuffle(all_pieces)
#
#     # Save orientation lines per step
#     ori: dict[str, list[str]] = {s.name: _orientation_lines(s.constraints) for s in steps}
#
#     remaining = list(all_pieces)
#     assignments: dict[str, list[str]] = defaultdict(list)
#
#     for i, step in enumerate(steps):
#         is_last = (i == len(steps) - 1)
#         if is_last:
#             assignments[step.name] = remaining[:]
#             remaining = []
#         else:
#             cap   = random.randint(1, MAX_CONSTRAINTS_PER_STEP)
#             taken = _coherent_sample(remaining, cap)
#             assignments[step.name] = taken
#             taken_set = set(taken)
#             remaining = [p for p in remaining if p not in taken_set]
#
#     # Spill overflow from last step into earlier steps
#     last = steps[-1]
#     overflow = assignments[last.name][MAX_CONSTRAINTS_PER_STEP:]
#     assignments[last.name] = assignments[last.name][:MAX_CONSTRAINTS_PER_STEP]
#
#     for piece in overflow:
#         for step in steps[:-1]:
#             if len(assignments[step.name]) < MAX_CONSTRAINTS_PER_STEP:
#                 assignments[step.name].append(piece)
#                 break
#
#     # Rebuild
#     for step in steps:
#         placement = [_piece_line(p) for p in assignments[step.name]]
#         step.constraints = placement + ori.get(step.name, [])
#         step.name = _step_name(step)
#
#     return m
#
#
# def _mutate_move_piece(method: Method) -> Method:
#     """
#     Move one piece from a donor step to a receiver step.
#     Preserves exact coverage — no piece is added or removed.
#     """
#     m     = copy.deepcopy(method)
#     steps = _all_steps(m)
#     if len(steps) < 2:
#         return m
#
#     donors = [s for s in steps if len(_placement_lines(s.constraints)) > 1]
#     if not donors:
#         return m
#
#     donor    = random.choice(donors)
#     receiver = random.choice([s for s in steps if s is not donor])
#
#     if len(_placement_lines(receiver.constraints)) >= MAX_CONSTRAINTS_PER_STEP:
#         return m
#
#     donor_placements = _placement_lines(donor.constraints)
#     line_to_move     = random.choice(donor_placements)
#
#     if _parse_placement(line_to_move) is None:
#         return m  # don't move wildcards
#
#     donor.constraints    = [c for c in donor.constraints if c != line_to_move]
#     receiver.constraints = receiver.constraints + [line_to_move]
#     donor.name    = _step_name(donor)
#     receiver.name = _step_name(receiver)
#     return m
#
#
# def _mutate_shuffle_steps(method: Method) -> Method:
#     """Randomly reorder top-level items."""
#     m = copy.deepcopy(method)
#     random.shuffle(m.items)
#     return m
#
#
# def _mutate_split_step(method: Method) -> Method:
#     """
#     Split a step with 2+ placements into two steps divided by face.
#     """
#     m          = copy.deepcopy(method)
#     candidates = [
#         (i, item) for i, item in enumerate(m.items)
#         if isinstance(item, Step) and len(_placement_lines(item.constraints)) >= 2
#     ]
#     if not candidates:
#         return m
#
#     idx, step = random.choice(candidates)
#     placements = _placement_lines(step.constraints)
#     oris       = _orientation_lines(step.constraints)
#
#     by_face: dict[str, list[str]] = defaultdict(list)
#     for line in placements:
#         piece = _parse_placement(line)
#         by_face[_face(piece) if piece else "?"].append(line)
#
#     faces = list(by_face.keys())
#     if len(faces) < 2:
#         mid     = len(placements) // 2
#         group_a = placements[:mid]
#         group_b = placements[mid:]
#     else:
#         random.shuffle(faces)
#         half    = max(1, len(faces) // 2)
#         set_a   = set(faces[:half])
#         group_a = [l for l in placements if _face(_parse_placement(l) or "") in set_a]
#         group_b = [l for l in placements if l not in group_a]
#
#     if not group_a or not group_b:
#         return m
#
#     step_a             = copy.deepcopy(step)
#     step_a.constraints = group_a + oris
#     step_a.name        = _step_name(step_a)
#
#     step_b             = copy.deepcopy(step)
#     step_b.constraints = group_b  # don't duplicate orientation lines
#     step_b.name        = _step_name(step_b)
#
#     m.items[idx] = step_a
#     m.items.insert(idx + 1, step_b)
#     return m
#
#
# def _mutate_merge_steps(method: Method) -> Method:
#     """
#     Merge two adjacent steps whose combined placements fit within the cap.
#     """
#     m         = copy.deepcopy(method)
#     top_steps = [(i, item) for i, item in enumerate(m.items) if isinstance(item, Step)]
#     if len(top_steps) < 2:
#         return m
#
#     pairs = [
#         (top_steps[i], top_steps[i + 1])
#         for i in range(len(top_steps) - 1)
#         if (len(_placement_lines(top_steps[i][1].constraints)) +
#             len(_placement_lines(top_steps[i+1][1].constraints))) <= MAX_CONSTRAINTS_PER_STEP
#     ]
#     if not pairs:
#         return m
#
#     (idx_a, step_a), (idx_b, step_b) = random.choice(pairs)
#
#     merged             = copy.deepcopy(step_a)
#     merged_pl          = _placement_lines(step_a.constraints) + _placement_lines(step_b.constraints)
#     # Deduplicate orientation lines
#     merged_ori         = list(dict.fromkeys(
#         _orientation_lines(step_a.constraints) + _orientation_lines(step_b.constraints)
#     ))
#     merged.constraints = merged_pl + merged_ori
#     merged.name        = _step_name(merged)
#
#     m.items[idx_a] = merged
#     del m.items[idx_b]
#     return m
#
#
# def _mutate_cross_pollinate(method: Method, donor_pool: list[Method]) -> Method:
#     """
#     Replace one step's pieces with a donor step's pieces, then repair
#     coverage so all 20 pieces remain placed exactly once.
#     """
#     if not donor_pool:
#         return copy.deepcopy(method)
#
#     m = copy.deepcopy(method)
#
#     donor_steps = [s for dm in donor_pool for s in _all_steps(dm)]
#     if not donor_steps:
#         return m
#
#     my_steps = _all_steps(m)
#     if not my_steps:
#         return m
#
#     target     = random.choice(my_steps)
#     donor_step = random.choice(donor_steps)
#
#     donor_pl           = _placement_lines(donor_step.constraints)[:MAX_CONSTRAINTS_PER_STEP]
#     target.constraints = donor_pl + _orientation_lines(target.constraints)
#     target.name        = _step_name(target)
#
#     _fix_coverage(m)
#     return m
#
#
# # ---------------------------------------------------------------------------
# # Mutation dispatcher
# # ---------------------------------------------------------------------------
#
# _MUTATIONS = [
#     (_mutate_redistribute,  4),
#     (_mutate_move_piece,    4),
#     (_mutate_shuffle_steps, 2),
#     (_mutate_split_step,    2),
#     (_mutate_merge_steps,   1),
# ]
#
#
# def _weighted_choice(options):
#     items, weights = zip(*options)
#     return random.choices(items, weights=weights, k=1)[0]
#
#
# # def mutate_method(
# #     method: Method,
# #     method_list: list[Method] = [],
# #     allow_cross: bool = True,
# # ) -> Method:
# #     """
# #     Apply one atomic mutation, optionally followed by cross-pollination.
# #     All results have coverage repaired before returning.
# #     """
# #     fn     = _weighted_choice(_MUTATIONS)
# #     result = fn(method)
# #
# #     if allow_cross and method_list and random.random() < 0.35:
# #         result = _mutate_cross_pollinate(result, method_list)
# #
# #     for step in _all_steps(result):
# #         step.name = _step_name(step)
# #
# #     return result
#
# def mutate_method(
#     method: Method,
#     method_list: list[Method] = [],
#     allow_cross: bool = True,
# ) -> Method:
#
#     fn     = _weighted_choice(_MUTATIONS)
#     result = fn(method)
#
#     # 🔥 CRITICAL FIX
#     _fix_coverage(result)
#
#     if allow_cross and method_list and random.random() < 0.35:
#         result = _mutate_cross_pollinate(result, method_list)
#
#     for step in _all_steps(result):
#         step.name = _step_name(step)
#
#     return result
#
# # ---------------------------------------------------------------------------
# # Batch generation
# # ---------------------------------------------------------------------------
#
# def generate_mutations(
#     base_method: Method,
#     n: int,
#     method_list: list[Method] = [],
# ) -> list[Method]:
#     """
#     Generate `n` distinct, viable mutations starting from `base_method`.
#
#     Only methods passing _is_viable() enter the pool or output list.
#     Deduplication is hash-based. Gives up after MAX_MUTATION_ATTEMPTS
#     consecutive failures.
#     """
#     if base_method not in method_list:
#         method_list.append(base_method)
#
#     mutations:   list[Method] = []
#     seen_hashes: set[str]     = {
#         hashlib.md5(method_to_dsl_text(m).encode()).hexdigest()
#         for m in method_list
#     }
#     attempts_since_success = 0
#
#     while len(mutations) < n:
#         if attempts_since_success >= MAX_MUTATION_ATTEMPTS:
#             print(
#                 f"[WARN] generate_mutations: gave up after {MAX_MUTATION_ATTEMPTS} "
#                 f"consecutive failed attempts ({len(mutations)}/{n} generated)."
#             )
#             break
#
#         parent = random.choice(method_list)
#         child  = mutate_method(parent, method_list)
#
#         if not _is_viable(child):
#             attempts_since_success += 1
#             continue
#
#         h = hashlib.md5(method_to_dsl_text(child).encode()).hexdigest()
#         if h in seen_hashes:
#             attempts_since_success += 1
#             continue
#
#         seen_hashes.add(h)
#         method_list.append(child)
#         mutations.append(child)
#         attempts_since_success = 0
#
#     return mutations
#
#
# # ---------------------------------------------------------------------------
# # Entry point
# # ---------------------------------------------------------------------------
#
# if __name__ == "__main__":
#
#     workspace = "workspace/scratch"
#     dsl_dir   = os.path.join(workspace, "dsl")
#     os.makedirs(dsl_dir, exist_ok=True)
#
#     print("[1/3] Loading base methods...")
#     base_methods = [
#         method_from_file(os.path.join(dsl_dir, "zz_method.dsl")),
#         method_from_file(os.path.join(dsl_dir, "cfop_method.dsl")),
#         method_from_file(os.path.join(dsl_dir, "roux_method.dsl")),
#     ]
#
#     method_pool = base_methods.copy()
#
#     TARGET = 1000
#     print(f"[2/3] Generating {TARGET} mutations...")
#
#     all_mutations = generate_mutations(
#         base_methods[0],
#         n=TARGET,
#         method_list=method_pool,
#     )
#
#     print("[3/3] Writing mutations...")
#     for i, m in enumerate(all_mutations):
#         dsl_text    = method_to_dsl_text(m)
#         method_hash = hashlib.md5(dsl_text.encode()).hexdigest()[:8]
#         m.name      = f"mutation_{method_hash}"
#         method_to_file(m, workspace)
#
#         if (i + 1) % 100 == 0:
#             print(f"  -> Written {i+1}/{TARGET}")
#
#     print(f"[DONE] Generated and saved {len(all_mutations)} mutations.")
import copy
import random
import hashlib
import os
from typing import Optional

from core.models import Step, Group, Method
from core.dsl import method_to_file, method_to_dsl_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CONSTRAINTS_PER_STEP = 5

_ALL_EDGES = ["BL", "BR", "BU", "BD", "FL", "FR", "FU", "FD", "LU", "LD", "RU", "RD"]
_ALL_CORNERS = ["BLU", "BLD", "BRU", "BRD", "FLU", "FLD", "FRU", "FRD"]
_PIECE_POOL = _ALL_EDGES + _ALL_CORNERS # Exactly 20 pieces

def _piece_line(piece: str) -> str:
    if len(piece) == 2:
        return f"add_edge {piece}"
    return f"add_corner {piece}"

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

# ---------------------------------------------------------------------------
# Random Method Generator
# ---------------------------------------------------------------------------

def generate_random_method(name: str) -> Method:
    """
    Creates a valid 20-piece method with no wildcards.
    Distributes 20 pieces into 5 steps (4 pieces each) to stay under MAX.
    """
    method = Method(name=name, rotation_str="x2")
    
    # Shuffle the master pool
    pieces = list(_PIECE_POOL)
    random.shuffle(pieces)
    
    # Divide into 5 steps (20 / 4 = 5 steps)
    # This ensures we never hit the MAX_CONSTRAINTS_PER_STEP (5)
    step_size = 4
    for i in range(0, len(pieces), step_size):
        chunk = pieces[i : i + step_size]
        step_name = f"step_{i//step_size}"
        new_step = Step(name=step_name)
        new_step.constraints = [_piece_line(p) for p in chunk]
        method.items.append(new_step)
        
    return method

# ---------------------------------------------------------------------------
# Execution Block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    workspace = "workspace/scratch"
    dsl_dir = os.path.join(workspace, "dsl")
    os.makedirs(dsl_dir, exist_ok=True)

    TARGET_COUNT = 1000
    print(f"[1/2] Generating {TARGET_COUNT} random methods...")

    generated_count = 0
    seen_hashes = set()

    while generated_count < TARGET_COUNT:
        # 1. Generate a candidate
        candidate_name = f"random_gen_{generated_count}"
        method = generate_random_method(candidate_name)
        
        # 2. Hash it to ensure uniqueness
        dsl_string = safe_method_to_dsl(method)
        m_hash = hashlib.md5(dsl_string.encode()).hexdigest()
        
        if m_hash not in seen_hashes:
            seen_hashes.add(m_hash)
            
            # 3. Save to file
            # We use the hash in the filename to prevent overwrites
            method.name = f"rand_{m_hash[:8]}"
            method_to_file(method, workspace)
            
            generated_count += 1
            
            if generated_count % 100 == 0:
                print(f"  -> Generated {generated_count}/{TARGET_COUNT}")

    print(f"[2/2] Done! Saved {generated_count} unique random methods to {dsl_dir}")
