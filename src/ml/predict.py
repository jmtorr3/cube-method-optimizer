"""
predict py — Score a method given its feature vector.

Input:  method_vector(method) from generation.data_generation
Output: predicted score (float)

Not yet implemented.
"""

# filesystems
import os
# print warnings without stopping execution
import warnings
# load and save ML models efficiently
import joblib
import numpy as np
# converts method object into numpy feature vector
from ml.features import extract_from_method

# dictionary to store loaded models in memory
# keyed by models absolute path 
# makes sure we dont have to keep reading from disk
_MODEL_CACHE: dict = {}

# gets path of ML model file inside the workspace
# workspace_root: root directory
def _model_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, "data", "ml", "model.pkl")


# load model from disk
# if its not cached, checks if file exists
# if exists, loads model with joblib.load and caches it
def load_model(workspace_root: str):
    # gets absolute path to the model file
    path = os.path.abspath(_model_path(workspace_root))
    # checking if model is already in memory
    if path not in _MODEL_CACHE:
        if not os.path.exists(path):
            warnings.warn(
                f"[ml.predict] No model found at {path}. "
                "Run `python -m ml.train` first.",
                RuntimeWarning,
                stacklevel=2,
            )
            return None
        _MODEL_CACHE[path] = joblib.load(path)
 
    return _MODEL_CACHE[path]

# clear in process model cache
# if pass in a workspace path it removes only that model
def invalidate_cache(workspace_root=None):
    if workspace_root is None:
        _MODEL_CACHE.clear()
    else:
        path = os.path.abspath(_model_path(workspace_root))
        _MODEL_CACHE.pop(path, None)
        

# Hypothesis
 
# apply the learned hypothesis to a single feature vector
def _predict_from_model(model: dict, x_raw: np.ndarray) -> float:
    # learned weights of model including bias
    theta = model["theta"]
    # mean of features (for normalization)
    mean  = model["mean"]
    # standard deviation of features (for normalization)
    std   = model["std"]
    # standardize features, ensures model sees data on same scale it was trained on
    x_norm = (x_raw - mean) / std
    # add bias term at start of feature term
    # score = theta0 + theta1 x1 + theta1 x2 ...
    # linear models use the theta0 term as bias weight
    x_b    = np.concatenate([[1.0], x_norm])
    # dot product to give the score = ... equation
    return float(np.dot(theta, x_b))

# predict score without running solves
# predicts score of a method object
def predict(method, workspace_root: str):
    # loads model
    model = load_model(workspace_root)
    if model is None:
        return None
    # converts method object into feature vector
    x_raw = extract_from_method(method)
    # applies model to feature vector get predicted score
    return _predict_from_model(model, x_raw)