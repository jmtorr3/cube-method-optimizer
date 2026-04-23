"""
features.py — Feature engineering on top of method_vector.

Any transforms, normalization, or derived features needed before
feeding method vectors into a model live here.

"""

import numpy as np
from generation.data_generation import METHOD_FIELDNAMES

# Drop identifier and label columns; everything else is a model feature.
FEATURE_COLS = [
    col for col in METHOD_FIELDNAMES
    if col not in {"method_name", "score"}
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
