"""
evaluate.py - Compare predicted vs actual scores from methods.csv
Usage: python -m ml.evaluate [workspace]
"""
import sys
import csv
import os
import numpy as np
from core.config import CONFIG
from ml.predict import load_model, _predict_from_model
from ml.features import FEATURE_COLS, extract_from_row

def main():
    default_ws = CONFIG["general"]["default_workspace"]
    workspace  = sys.argv[1] if len(sys.argv) > 1 else default_ws

    model = load_model(workspace)
    if model is None:
        print("No model found. Run python -m ml.train first.")
        return

    path = os.path.join(workspace, "data", "methods", "methods.csv")
    INCLUDE = {"ZZ", "CFOP", "Roux", "BEGINNERS", "PETRUS", "APB", "rand_d2de834a"}

    results = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("method_name", "").strip()
            if name not in INCLUDE:
                continue
            score_str = row.get("score", "").strip()
            if not score_str:
                continue
            actual = float(score_str)
            x_raw = extract_from_row(row)
            predicted = _predict_from_model(model, x_raw)
            results.append((name, actual, predicted))

    results.sort(key=lambda r: r[1])

    print(f"\n{'Method':<40} {'Actual':>10} {'Predicted':>10} {'Error':>10}")
    
    for name, actual, predicted in results:
        error = predicted - actual
        print(f"{name:<40} {actual:>10.6f} {predicted:>10.6f} {error:>+10.6f}")

    errors = [r[2] - r[1] for r in results]
    if errors:
        mae = np.mean(np.abs(errors))
        print(f"\n  Mean absolute error: {mae:.6f}")
        print(f"  Max over-prediction:       {max(errors):+.6f}")
        print(f"  Max under-prediction:      {min(errors):+.6f}")

if __name__ == "__main__":
    main()
