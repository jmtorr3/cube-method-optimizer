"""
train py — Train a model to predict method score from method_vector features.

Input:  data/methods/methods.csv joined with data/evaluation/*.csv
Output: trained model artifact
"""

import os
import sys
import csv
import joblib
import numpy as np
 
from ml.features import FEATURE_COLS, extract_from_row
from core.config import CONFIG
 
# Hyperparameters
 
# step size for gradient descent
LEARNING_RATE  = 0.005
# number of iterations for gradient descent
NUM_ITERATIONS = 2000

# paths to methods csv and model file
def _methods_csv_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, "data", "methods", "methods.csv")
 
def _model_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, "data", "ml", "model.pkl")

# scan the data and return a score dict from most recent evaluation file
# fallback when methods.csv doesnt have scores yet
def _load_eval_scores(workspace_root: str) -> dict:
    # sets path to evaluation directory
    eval_dir = os.path.join(workspace_root, "data", "evaluation")
    if not os.path.isdir(eval_dir):
        return {}
    # lists all csv files in evaluation folder
    eval_files = sorted(
        [f for f in os.listdir(eval_dir) if f.endswith(".csv")],
        reverse=True,
    )
    # goes through each csv, opens it, and skips file without a score column
    scores = {}
    for fname in eval_files:
        path = os.path.join(eval_dir, fname)
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            if "score" not in (reader.fieldnames or []):
                continue
            # reads each row, gets method name and score
            # stores in scores dict, only keeps the first and latest score for each method
            for row in reader:
                name = row.get("method", "").strip()
                score_str = row.get("score", "").strip()
                if name and score_str and name not in scores:
                    try:
                        scores[name] = float(score_str)
                    except ValueError:
                        pass
    # prints how many scores were loaded
    if scores:
        print(f"Loaded {len(scores)} score(s) from evaluation CSV fallback.")
    return scores
 
# read methods.csv and return (X,y,method_names)
def load_training_data(workspace_root: str) -> tuple:
    # checks that methods.csv exists and raises error if not
    path = _methods_csv_path(workspace_root)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"methods.csv not found at {path}. "
            "Run data_generation first to populate it."
        )
 
    # cerates containers for features, labels, and method names
    eval_scores = None
    X_rows, y_vals, names = [], [], []
    # counts rows without scores
    skipped = 0
    
    # reads methods.csv row by row
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            method_name = row.get("method_name", "").strip()
            score_str   = row.get("score", "").strip()
            score       = None
            # converts score to float if its there
            if score_str:
                try:
                    score = float(score_str)
                except ValueError:
                    pass
            # if no score, fallback to evaluation csv scores
            if score is None:
                if eval_scores is None:
                    eval_scores = _load_eval_scores(workspace_root)
                score = eval_scores.get(method_name)
            # if still nothing, skip
            if score is None:
                skipped += 1
                continue
            # adds features
            X_rows.append(extract_from_row(row))
            # adds labels
            y_vals.append(score)
            # adds method names
            names.append(method_name)
    # prints out if there was anything skipped
    if skipped:
        print(f"Skipped {skipped} rows with no score.")
    # error if theres no data
    if not X_rows:
        raise ValueError(
            "No scored rows found in methods.csv or evaluation CSVs. Run evaluate_solves() first, then retry"
        )
    # converts features and labels to numpy arrays
    return np.array(X_rows), np.array(y_vals), names

# Normalization
 
# standardize features to zero mean and variance
def normalize(X: np.ndarray) -> tuple:

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    # avoid division by zero for constant features
    std[std == 0] = 1   
    return (X - mean) / std, mean, std

# Hypothesis

# compute prediction for all m examples
# h(x) = theta0 + theta1x1 + ... + theta n xn
def hypothesis(X_b: np.ndarray, theta: np.ndarray) -> np.ndarray:
    return X_b @ theta

# Cost function

# MSE cost function from slides
# J(theta) = (1/2m) sum (i)(h(xi)-yi)^2
def compute_cost(X_b: np.ndarray, y: np.ndarray, theta: np.ndarray) -> float:
    m = len(y)
    errors = hypothesis(X_b, theta) - y
    return float((1 / (2 * m)) * np.dot(errors, errors))


# Gradient descent
 
# gradient descent for linear regression
def gradient_descent(
    X_b: np.ndarray,
    y: np.ndarray,
    alpha: float = LEARNING_RATE,
    num_iterations: int = NUM_ITERATIONS,
) -> tuple:
    # init weight to zero
    m = len(y)
    theta = np.zeros(X_b.shape[1]) 
    cost_history = []
    # compute prediction errors
    for i in range(num_iterations):
        # h(xi) - yi for all i
        errors = hypothesis(X_b, theta) - y
        # vectorised update across all theta j
        grad = (1 / m) * (X_b.T @ errors)
        theta = theta - alpha * grad
        # log progress every 100 iterations and last iteration
        if i % 100 == 0 or i == num_iterations - 1:
            cost = compute_cost(X_b, y, theta)
            cost_history.append(cost)
            print(f"  iter {i:>5d}   J(θ) = {cost:.8f}")
    # return final weights and cost history
    return theta, cost_history


# Public API
 
def train(workspace_root: str) -> dict:

    # load data
    print(f"Loading training data from {_methods_csv_path(workspace_root)} ...")
    X, y, names = load_training_data(workspace_root)
    m, n = X.shape
    print(f"      {m} scored methods, {n} features.")
 
    print("Normalizing features")
    X_norm, mean, std = normalize(X)
 
    # Prepend bias column of 1s for theta0 (intercept)
    X_b = np.hstack([np.ones((m, 1)), X_norm])     # shape (m, n+1)
    print(f"      Feature matrix shape: {X_b.shape}  (includes bias column)")
 
    print(f"Running gradient descent  (α={LEARNING_RATE}, {NUM_ITERATIONS} iters)")
    # run gradient descent to get weights
    theta, cost_history = gradient_descent(X_b, y, alpha=LEARNING_RATE, num_iterations=NUM_ITERATIONS)
 
    # get root mean squared error from final cost
    # cost was (1/2m) sum errors ^2, so multiply by 2 before sqrt
    train_rmse = float(np.sqrt(2 * cost_history[-1]))
    print(f"      Final train RMSE: {train_rmse:.6f}")
    # store model parameters for prediction
    model = {"theta": theta, "mean": mean, "std": std}
 
    print("Saving model")
    model_path = _model_path(workspace_root)
    # creates directories if missing, save to disk
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    joblib.dump(model, model_path)
    print(f"      Saved to {model_path}")
    print(f"\n  Learned parameters:")
    print(f"      Theta0  {'(bias)':<35s} = {theta[0]:.6f}")
    for i, (col, w) in enumerate(zip(FEATURE_COLS, theta[1:]), 1):
        print(f"      θ{i:<2d}  {col:<35s} = {w:.6f}")
 
    return model

def main():
    default_ws = CONFIG["general"]["default_workspace"]
    workspace  = sys.argv[1] if len(sys.argv) > 1 else default_ws
    train(workspace)
 
 
if __name__ == "__main__":
    main()
