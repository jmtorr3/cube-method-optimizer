import os
import random
import sys

from core.models import Step, Method
from core.dsl import method_to_file
from core.config import CONFIG

from .method_gen_common import (
    MIN_CONSTRAINTS_PER_STEP,
    MAX_CONSTRAINTS_PER_STEP,
    TARGET_COUNT,
    _PIECE_POOL,
    _piece_line,
    method_hash,
    load_seen_hashes_from_workspace,
    workspace_dsl_dir,
)


def generate_random_method(name: str) -> Method:
    """
    Creates a valid method with no wildcards.

    The piece pool is split into randomly-sized steps, where each step size is
    between MIN_CONSTRAINTS_PER_STEP and MAX_CONSTRAINTS_PER_STEP inclusive.
    """
    method = Method(name=name, rotation_str="x2")

    pieces = list(_PIECE_POOL)
    random.shuffle(pieces)

    total_pieces = len(pieces)

    if MIN_CONSTRAINTS_PER_STEP <= 0:
        raise ValueError("MIN_CONSTRAINTS_PER_STEP must be > 0")

    if MIN_CONSTRAINTS_PER_STEP > MAX_CONSTRAINTS_PER_STEP:
        raise ValueError("MIN_CONSTRAINTS_PER_STEP cannot be greater than MAX_CONSTRAINTS_PER_STEP")

    step_sizes = []
    remaining = total_pieces

    while remaining > 0:
        valid_sizes = []

        for size in range(MIN_CONSTRAINTS_PER_STEP, MAX_CONSTRAINTS_PER_STEP + 1):
            if size > remaining:
                continue

            leftover = remaining - size

            if leftover == 0:
                valid_sizes.append(size)
                continue

            min_steps_needed = (leftover + MAX_CONSTRAINTS_PER_STEP - 1) // MAX_CONSTRAINTS_PER_STEP
            max_steps_possible = leftover // MIN_CONSTRAINTS_PER_STEP

            if min_steps_needed <= max_steps_possible:
                valid_sizes.append(size)

        if not valid_sizes:
            raise ValueError(
                f"Cannot partition {total_pieces} pieces into step sizes between "
                f"{MIN_CONSTRAINTS_PER_STEP} and {MAX_CONSTRAINTS_PER_STEP}"
            )

        chosen_size = random.choice(valid_sizes)
        step_sizes.append(chosen_size)
        remaining -= chosen_size

    start = 0
    for idx, size in enumerate(step_sizes):
        chunk = pieces[start:start + size]
        start += size

        new_step = Step(name=f"step_{idx}")
        new_step.constraints = [_piece_line(p) for p in chunk]
        method.items.append(new_step)

    return method


def generate_random_methods(num_new_methods: int, seen_hashes: set[str]) -> list[Method]:
    """
    Generate num_new_methods unique random methods.
    seen_hashes is updated in-place.
    """
    generated = []

    while len(generated) < num_new_methods:
        candidate_name = f"random_gen_{len(generated)}"
        method = generate_random_method(candidate_name)

        m_hash = method_hash(method)
        if m_hash in seen_hashes:
            continue

        seen_hashes.add(m_hash)
        method.name = f"rand_{m_hash[:8]}"
        generated.append(method)

    return generated


if __name__ == "__main__":
    default_ws = CONFIG["general"]["scratch_workspace"]
    workspace = sys.argv[1] if len(sys.argv) > 1 else default_ws

    dsl_dir = workspace_dsl_dir(workspace)
    os.makedirs(dsl_dir, exist_ok=True)

    print(f"[1/2] Generating {TARGET_COUNT} random methods...")

    seen_hashes = load_seen_hashes_from_workspace(workspace)
    methods = generate_random_methods(TARGET_COUNT, seen_hashes)

    for i, method in enumerate(methods, start=1):
        method_to_file(method, workspace)

        if i % 100 == 0:
            print(f"  -> Generated {i}/{TARGET_COUNT}")

    print(f"[2/2] Done! Saved {len(methods)} unique random methods to {dsl_dir}")
