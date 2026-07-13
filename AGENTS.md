# slushy-build

A tool for consolidating build requirements for Python packages. See README.md for details.

## Development

- Install dependencies: `uv sync --group dev`
- Run tests: `uv run pytest`
- Lint and format before committing:
  - `uv run ruff check --fix`
  - `uv run ruff format`
