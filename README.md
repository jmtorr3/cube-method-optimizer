# cube_solver

A constraint-driven Rubik's Cube method execution engine.

## Structure

```
cube_solver/
├── src/
│   ├── core/           # Shared foundation: models, DSL parser, rotation, cache
│   ├── solver/         # MethodRunner execution engine + run.py entry point
│   ├── generation/     # Data generation pipeline
│   ├── ml/             # Model training and prediction (planned)
│   └── discovery/      # Method mutation and search loop (planned)
│
├── bin/
│   ├── linux/kube_solver
│   ├── mac/kube_solver
│   └── windows/kube_solver.exe
│
├── workspace/
│   ├── stable/         # Hand-written or promoted methods — never auto-cleared
│   │   ├── dsl/
│   │   ├── algs/
│   │   └── data/
│   └── scratch/        # Discovery output — safe to wipe between runs
│       ├── dsl/
│       ├── algs/
│       └── data/
│
└── tests/
```

## Entry points

Run a single solve:
    python -m solver.run <dsl_file> [workspace]

Generate data:
    python -m generation.data_generation [workspace]

Both default to `workspace/stable` if no workspace argument is provided.

## Workspace

`workspace/stable/` holds your curated DSL files, algorithm caches, and
generated data. Never cleared automatically.

`workspace/scratch/` is used by the discovery loop for thousands of generated
DSLs and their data. Safe to delete entirely between discovery runs.


## Setup Guide

Follow these steps to get the project running locally.

### 1. Clone the repository

```bash
git clone <repo-url>
cd cube_solver
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate      # Linux / macOS
# .venv\Scripts\activate     # Windows
```


### 3. Install dependencies

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

### 4. Install the project (editable mode)

This allows you to run modules cleanly using `python -m ...`:

```bash
pip install -e .
```

### 5. Verify solver binary

Ensure the correct solver binary exists for your platform:

```
bin/
├── linux/kube_solver
├── mac/kube_solver
└── windows/kube_solver.exe
```

The code will automatically select the correct one using `platform.system()`.


### 6. Run a smoke test

From the project root:

```bash
python -m solver.run workspace/stable/dsl/zz_method.dsl
```

If everything is set up correctly, this should execute a solve and print the result.


### 7. (Optional) Run tests

```bash
pytest tests/
```

## Notes

* Always run commands from the **project root**, not inside `src/`
* The project uses a **workspace system**:

  * `workspace/stable/` → persistent, curated methods and data
  * `workspace/scratch/` → temporary discovery output
* Editable install (`pip install -e .`) ensures `src/` is correctly added to Python’s module path


---
## Acknowledgements

This project builds on top of [kubesolver](https://github.com/kuba97531/kubesolver), a high-performance Rubik’s Cube solver by kuba97531.
