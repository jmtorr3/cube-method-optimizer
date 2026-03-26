"""
features.py — Feature engineering on top of method_vector.

Any transforms, normalization, or derived features needed before
feeding method vectors into a model live here.

Not yet implemented.
"""

import numpy as np

# Must stay in sync with METHOD_FIELDNAMES in data_generation.py.
# Drop 'method_name' (identifier) and 'score' (label), everything else is a feature
FEATURE_COLS = [
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
]

 # extract a feature vector from methods.csv dict row
def extract_from_row(row: dict) -> np.ndarray:
    feature_values = []

    # Loop over each feature column defined above
    for col in FEATURE_COLS:
        # Get the value from the row dictionary
        value = row[col]
    
        # Convert the value to a float
        numeric_value = float(value)
    
        # Add the value to feature list
        feature_values.append(numeric_value)

    # Convert the list of numeric values into a numpy array
    feature_vector = np.array(feature_values, dtype=np.float64)

    # Return the resulting feature vector
    return feature_vector

# extract a feature vector directly from a method object
def extract_from_method(method) -> np.ndarray:
    # Import here to avoid circular imports at module load time
    from generation.data_generation import method_vector
 
    vec = method_vector(method)
    return np.array([float(vec[col]) for col in FEATURE_COLS], dtype=np.float64)