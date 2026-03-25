"""
mutate.py — Method mutation and generation logic.

Generates new Method objects or DSL files by mutating existing ones.
Writes generated DSLs to workspace/scratch/dsl/.

Not yet implemented.
"""

import copy
import random
import hashlib
from core.models import Step, Group, Remove, Method


# ---------------------------------------------------------------------------
# Core mutation operations
# ---------------------------------------------------------------------------


def _generate_step_name(step: Step) -> str:
    """Generate a step name from the pieces it affects (from constraints)."""
    pieces = set()
    for c in step.constraints:
        for token in c.split():
            if token.isupper():  # crude filter for cube pieces like UR, UF, etc.
                pieces.add(token)
    if not pieces:
        pieces.add("GEN")
    return "Step_" + "_".join(sorted(pieces))

def mutate_method(method: Method, method_list: list = [], allow_cross: bool = True) -> Method:
    """
    Generate a mutated copy of a method:
    - Shuffle the order of steps
    - Shuffle the constraints within steps
    - Optionally copy a step from another method (cross-polination)
    """
    new_method = copy.deepcopy(method)

    # Shuffle steps in method.items (for both Steps and Groups)
    top_level_steps = [item for item in new_method.items if isinstance(item, Step)]
    random.shuffle(top_level_steps)

    # Shuffle constraints in each step
    for item in new_method.items:
        if isinstance(item, Step):
            random.shuffle(item.constraints)
            item.name = _generate_step_name(item)
        elif isinstance(item, Group):
            random.shuffle(item.steps)
            for s in item.steps:
                random.shuffle(s.constraints)
                s.name = _generate_step_name(s)

    # Optional cross-polination
    if allow_cross and method_list:
        donor = random.choice(method_list)
        donor_steps = [s for s in donor.items if isinstance(s, Step)]
        donor_steps += [s for g in donor.items if isinstance(g, Group) for s in g.steps]
        if donor_steps:
            chosen = random.choice(donor_steps)
            # pick a random target step
            target_candidates = [s for s in new_method.items if isinstance(s, Step)]
            target_candidates += [s for g in new_method.items if isinstance(g, Group) for s in g.steps]
            if target_candidates:
                target = random.choice(target_candidates)
                target.constraints = chosen.constraints.copy()
                target.name = _generate_step_name(target)

    return new_method

def generate_mutations(base_method: Method, n: int, method_list: list[Method] = []) -> list[Method]:
    """
    Generate `n` distinct mutations starting from base_method.
    Mutations are added to method_list as they are created for further cross-polination.
    """
    if base_method not in method_list:
        method_list.append(base_method)

    mutations = []
    seen_hashes = set(hashlib.md5(method_to_dsl_text(m).encode("utf-8")).hexdigest() for m in method_list)

    while len(mutations) < n:
        parent = random.choice(method_list)
        child = mutate_method(parent, method_list)
        h = hashlib.md5(method_to_dsl_text(child).encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        method_list.append(child)
        mutations.append(child)

    return mutations

if __name__ == "__main__":
    import os
    import hashlib
    from core.config import CONFIG
    from core.dsl import method_from_file, method_to_file, method_to_dsl_text
    from core.models import Step, Group

    # Workspace / DSL directory
    workspace = "workspace/scratch"
    dsl_dir = os.path.join(workspace, "dsl")
    os.makedirs(dsl_dir, exist_ok=True)

    print("[1/3] Loading base methods...")
    base_methods = [
        method_from_file(os.path.join(dsl_dir, "zz_method.dsl")),
        method_from_file(os.path.join(dsl_dir, "cfop_method.dsl")),
        method_from_file(os.path.join(dsl_dir, "roux_method.dsl")),
    ]

    # Combine all methods for cross-method mutation pool
    method_pool = base_methods.copy()

    print("[2/3] Generating mutations...")
    all_mutations = []
    for m in base_methods:
        mutated_methods = generate_mutations(m, n=5, method_list=method_pool)
        all_mutations.extend(mutated_methods)

    print("[3/3] Summary of mutations:")
    for i, m in enumerate(all_mutations):
        # Generate a unique name for the mutation using a hash of the DSL text
        dsl_text = method_to_dsl_text(m)
        method_hash = hashlib.md5(dsl_text.encode("utf-8")).hexdigest()[:8]
        m.name = f"mutation_{method_hash}"

        # Write mutated method to file
        method_to_file(m, workspace)

        # Count steps and constraints
        num_steps = sum(1 for item in m.items if isinstance(item, Step)) + \
                    sum(len(item.steps) for item in m.items if isinstance(item, Group))
        num_constraints = sum(len(s.constraints) for item in m.items
                              for s in ([item] if isinstance(item, Step) else item.steps if isinstance(item, Group) else []))

        print(f"Mutation {i+1}: {m.name}, steps={num_steps}, constraints={num_constraints}")

    print(f"[DONE] Generated {len(all_mutations)} mutated methods.")
