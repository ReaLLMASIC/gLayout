## Regression Tests

This folder contains repository-level regression checks for structural changes
such as import-path migrations.

Run the default suite from the repository root:

```bash
tests/run_regression.sh
```

The current suite focuses on:

- canonical imports under `glayout.cells`
- compatibility imports under `glayout.blocks`
- canonical imports under `glayout.verification`
- repository layout checks for the `legacy/atlas` move
