# Cube Method Optimizer

A Rubik's Cube method optimizer built around a DSL method format, a native
cube solver binary, generated solve/evaluation data, and an ML model used to
score candidate methods during discovery.

The Python package is currently named `cube_solver`.

## Repository Layout

```text
src/
  core/         Shared models, config loading, DSL parsing, rotation, cache I/O
  solver/       MethodRunner and the single-solve CLI
  generation/   Feature extraction, solve CSV handling, and classical evaluation
  ml/           Random forest training, prediction, and prediction evaluation
  discovery/    Random generation, mutation, and ML-guided hill-climb search

bin/
  linux/kube_solver       Native solver binary used on Linux

workspace/
  stable/                 Curated hand-written methods and classical results
  generated_data/          Large generated/evaluated dataset plus trained model
  hillclimb/               ML-guided discovery output and verification results
  scratch/                 Configured scratch workspace; create as needed
```

Important generated files:

- `workspace/*/dsl/*.dsl`: method definitions
- `workspace/*/algs/<method>/*_algs.txt`: cached step algorithms
- `workspace/*/data/solves/<method>.csv`: per-scramble solve results
- `workspace/*/data/evaluation/evaluation_<timestamp>.csv`: classical scores
- `workspace/*/data/methods/methods.csv`: ML feature rows and score labels
- `workspace/*/data/ml/model.pkl`: trained ML model artifact
- `workspace/hillclimb/data/discovery/*.csv`: search diagnostics/results

## Setup

Run commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

The ML code imports `joblib` and `scikit-learn`. If they are not already
available in your environment, install them too:

```bash
pip install joblib scikit-learn
```

On Linux, verify the native solver is executable:

```bash
chmod +x bin/linux/kube_solver
```

## Configuration

Runtime defaults live in `config.toml`.

- `general.default_workspace = "workspace/stable"`
- `general.scratch_workspace = "workspace/scratch"`
- `discovery.workspace = "workspace/hillclimb"`
- `discovery.seed_workspace = "workspace/hillclimb"`
- `generation.num_scrambles = 10`
- `parallel.enabled = true`

Most CLIs accept an optional workspace argument. If omitted, each module uses
the default defined in code/config.

## Run One Solve

```bash
python -m solver.run workspace/stable/dsl/zz_method.dsl workspace/stable
```

With a fixed scramble:

```bash
python -m solver.run workspace/stable/dsl/zz_method.dsl workspace/stable --scramble "R U R' U'"
```

If no arguments are given, `solver.run` uses
`workspace/stable/dsl/zz_method.dsl` and `workspace/stable`.

## Classical Data and Evaluation

The current `generation.data_generation` entry point loads all DSL files in a
workspace and evaluates existing solve CSVs. The solve-generation calls in
`main()` are currently commented out, so this command does not create new solve
CSV files by itself.

Evaluate existing solves and update `methods.csv` scores:

```bash
python -m generation.data_generation workspace/stable
python -m generation.data_generation workspace/generated_data
python -m generation.data_generation workspace/hillclimb
```

This reads:

```text
<workspace>/dsl/*.dsl
<workspace>/data/solves/*.csv
```

and writes:

```text
<workspace>/data/evaluation/evaluation_<timestamp>.csv
<workspace>/data/methods/methods.csv
```

The classical score is computed in `generation.data_generation.score_method`.
Higher is better. It is based on average total moves, completion rate, and a
penalty for high average moves per step.

## Train ML

Train a random forest regressor from scored method features:

```bash
python -m ml.train workspace/generated_data
```

You can train against any workspace that has scored rows in
`data/methods/methods.csv` or score-bearing files in `data/evaluation/`.

Training reads:

```text
<workspace>/data/methods/methods.csv
<workspace>/data/evaluation/*.csv
```

and writes:

```text
<workspace>/data/ml/model.pkl
```

The model predicts the same score produced by the classical evaluator. The
artifact is a `joblib` pickle containing the estimator and feature-column list.

## Evaluate ML

Compare ML predictions against actual scored rows in `methods.csv`:

```bash
python -m ml.evaluate workspace/generated_data
```

This requires:

```text
<workspace>/data/ml/model.pkl
<workspace>/data/methods/methods.csv
```

If a binary is missing for your platform, build it from
[kubesolver](https://github.com/kuba97531/kubesolver):

```bash
git clone https://github.com/kuba97531/kubesolver.git /tmp/kubesolver
cd /tmp/kubesolver
make BUILD=RELEASE -j5            # Linux
make BUILD=RELEASE CC=gcc-15 -j5  # macOS — needs Homebrew gcc for OpenMP
```

Then copy `kube_solver.out` into the matching `bin/<platform>/kube_solver`
(rename, drop the extension, `chmod +x`). On macOS the trailing `strip -s`
step in the upstream makefile fails harmlessly — the binary is already linked
by then.


## Discovery

Generate random DSL methods in the scratch workspace:

```bash
python -m discovery.random_generate workspace/scratch
```

Mutate existing DSL methods in a workspace:

```bash
python -m discovery.mutate workspace/scratch
```

Run ML-guided hill-climb discovery:

```bash
python -m discovery.search
```

`discovery.search` currently takes its workspace and seed workspace from
`config.toml`, not command-line arguments. It expects a trained model at:

```text
workspace/hillclimb/data/ml/model.pkl
```

The search loop scores mutations with the ML model, exports promising DSL files
to `workspace/hillclimb/dsl/`, logs candidate diagnostics under
`workspace/hillclimb/data/discovery/`, and then classically verifies the top
configured candidates.

## Typical ML Workflow

```bash
# 1. Recompute labels from existing solve CSVs.
python -m generation.data_generation workspace/generated_data

# 2. Train or refresh the model.
python -m ml.train workspace/generated_data

# 3. Inspect prediction quality on scored rows.
python -m ml.evaluate workspace/generated_data
```

For hill-climb discovery, train or copy a model into `workspace/hillclimb`:

```bash
python -m ml.train workspace/hillclimb
python -m ml.evaluate workspace/hillclimb
python -m discovery.search
```

## Notes

- Use `workspace/stable` for curated baseline methods.
- Use `workspace/generated_data` for the large evaluated dataset.
- Use `workspace/hillclimb` for ML-guided search output.
- `workspace/scratch` is safe to create and clear for experiments.
- Parallel solve execution is controlled by `config.toml`.

## Acknowledgements

This project builds on [kubesolver](https://github.com/kuba97531/kubesolver),
a high-performance Rubik's Cube solver by kuba97531.
