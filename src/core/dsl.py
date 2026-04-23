import os
import re

from core.models import Step, Group, Remove, Method
from core.rotation import expand_symmetry_param


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

def _parse_order(raw):
    s = raw.strip()
    m = re.fullmatch(r'(best|worst)_(\d+)', s)
    if m:
        n = int(m.group(2))
        if n < 1:
            raise ValueError(f"Order batch size must be >= 1, got '{s}'")
        return s
    if s in Group._BASE_ORDERS:
        return s
    raise ValueError(f"Unknown group order '{s}'.")


def _parse_group_header(line):
    inner = line[len("[GROUP:"): -1].strip()
    if "|" in inner:
        name_part, opts_part = inner.split("|", 1)
        name = name_part.strip()
        options = {}
        for token in opts_part.split("|"):
            token = token.strip()
            if "=" in token:
                k, v = token.split("=", 1)
                options[k.strip()] = v.strip()
    else:
        name = inner.strip()
        options = {}
    return name, _parse_order(options.get("order", "in_order"))


def _parse_step_header(line):
    inner = line[len("[STEP:"): -1].strip()
    if "|" in inner:
        name_part, opts_part = inner.split("|", 1)
        name = name_part.strip()
        options = {}
        for token in opts_part.split("|"):
            token = token.strip()
            if "=" in token:
                k, v = token.split("=", 1)
                options[k.strip()] = v.strip()
    else:
        name = inner.strip()
        options = {}
    cache_alg = options.get("cache_alg", "false").lower() == "true"
    free_layer_str = options.get("free_layer", "")
    free_layers = _parse_free_layers(free_layer_str) if free_layer_str else []
    return name, cache_alg, free_layers


_FREE_LAYER_MOVES = {
    "U": ["", "U", "U'", "U2"],
    "D": ["", "D", "D'", "D2"],
    "R": ["", "R", "R'", "R2"],
    "L": ["", "L", "L'", "L2"],
    "F": ["", "F", "F'", "F2"],
    "B": ["", "B", "B'", "B2"],
}


def _parse_free_layers(raw):
    layers = []
    for ch in raw.strip().upper():
        if ch not in _FREE_LAYER_MOVES:
            raise ValueError(f"Unknown free layer '{ch}' in free_layer='{raw}'")
        moves = _FREE_LAYER_MOVES[ch]
        if moves not in layers:
            layers.append(moves)
    return layers


def _parse_method_header(line: str) -> Method:
    """
    Parse '[METHOD: ZZ | rotation=x2 | symmetry=U,F | symmetry_depth=1]'
    """
    inner = line[len("[METHOD:"): -1].strip()
    if "|" in inner:
        name_part, opts_part = inner.split("|", 1)
        name = name_part.strip()
        options: dict = {}
        for token in opts_part.split("|"):
            token = token.strip()
            if "=" in token:
                k, v = token.split("=", 1)
                options[k.strip()] = v.strip()
    else:
        name = inner.strip()
        options = {}

    rotation_str = options.get("rotation", "").strip().strip('"').strip("'")

    sym_orientations: list = []
    if "symmetry" in options:
        sym_orientations = expand_symmetry_param(options["symmetry"])

    sym_depth = 1
    if "symmetry_depth" in options:
        try:
            sym_depth = int(options["symmetry_depth"])
            if sym_depth < 1:
                raise ValueError
        except ValueError:
            raise ValueError(
                f"symmetry_depth must be a positive integer, got '{options['symmetry_depth']}'"
            )

    return Method(
        name,
        rotation_str=rotation_str,
        symmetry_orientations=sym_orientations,
        symmetry_depth=sym_depth,
    )

# ---------------------------------------------------------------------------
# Method serialization
# ---------------------------------------------------------------------------

def method_to_dsl_text(method: Method) -> str:
    """
    Convert a Method object into DSL text that can be parsed again.
    Returns a string containing the DSL.
    """
    # Header line with rotation and symmetry
    header_parts = [f"[METHOD: {method.name}"]
    if method.rotation_str:
        header_parts.append(f"rotation={method.rotation_str}")
    if method.symmetry_orientations:
        header_parts.append(f"symmetry={','.join(method.symmetry_orientations)}")
    if method.symmetry_depth != 1:
        header_parts.append(f"symmetry_depth={method.symmetry_depth}")
    header_line = " | ".join(header_parts) + "]"

    lines = [header_line]

    for item in method.items:
        if isinstance(item, Remove):
            lines.append(f"[REMOVE: {item.command}]")
        elif isinstance(item, Group):
            lines.append(f"[GROUP: {item.name} | order={item.order}]")
            for step in item.steps:
                lines.extend(_step_to_lines(step))
            lines.append("[END GROUP]")
        elif isinstance(item, Step):
            lines.extend(_step_to_lines(item))

    lines.append("[END METHOD]")
    return "\n".join(lines)


def _step_to_lines(step: Step) -> list:
    """Helper to convert a Step object into DSL lines"""
    # Convert free_layers from list[list[str]] → layer letters for DSL
    free_layer_str = ""
    if step.free_layers:
        layer_chars = []
        for moves in step.free_layers:
            # pick first non-empty move as representative
            for move in moves:
                if move:  # skip ""
                    layer_chars.append(move[0].upper())
                    break
        free_layer_str = "".join(layer_chars)

    line = f"[STEP: {step.name} | cache_alg={'true' if step.cache_alg else 'false'}"
    if free_layer_str:
        line += f" | free_layer={free_layer_str}"
    line += "]"

    # Step constraints go directly under step
    lines = [line] + step.constraints
    return lines



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dsl(text: str) -> Method:
    """Parse DSL text and return a Method object."""
    lines = text.splitlines()
    method = None
    in_method = False
    current_group = None
    current_step = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith("[METHOD:"):
            method = _parse_method_header(line)
            in_method = True
            continue

        if line == "[END METHOD]":
            in_method = False
            current_group = None
            current_step = None
            continue

        if not in_method:
            continue

        if line.startswith("[REMOVE:"):
            command = line[len("[REMOVE:"): -1].strip()
            method.items.append(Remove(command))
            current_step = None
            continue

        if line.startswith("[GROUP:"):
            name, order = _parse_group_header(line)
            current_group = Group(name, order)
            current_step = None
            method.items.append(current_group)
            continue

        if line.startswith("[END GROUP"):
            current_group = None
            current_step = None
            continue

        if line.startswith("[STEP:"):
            name, cache_alg, free_layers = _parse_step_header(line)
            current_step = Step(name, cache_alg=cache_alg, free_layers=free_layers)
            if current_group is not None:
                current_group.steps.append(current_step)
            else:
                method.items.append(current_step)
            continue

        if line == "init_empty_cube":
            continue

        if current_step is not None:
            current_step.constraints.append(line)
        elif current_group is not None:
            current_group.directives.append(line)

    return method


def method_from_file(path: str) -> Method:
    """Load and parse a DSL file into a Method object."""
    with open(path) as f:
        return parse_dsl(f.read())


def method_from_name(name: str, dsl_dir: str) -> Method:
    """Load a method by filename (without .dsl) from dsl_dir."""
    return method_from_file(os.path.join(dsl_dir, f"{name}.dsl"))

def method_to_file(method: Method, workspace_root: str):
    """
    Save a Method object as a .dsl file under workspace_root/dsl/
    Creates directory if it does not exist.
    """
    dsl_dir = os.path.join(workspace_root, "dsl")
    os.makedirs(dsl_dir, exist_ok=True)
    path = os.path.join(dsl_dir, f"{method.name}.dsl")
    with open(path, "w") as f:
        f.write(method_to_dsl_text(method))
