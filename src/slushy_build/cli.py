import logging
from pathlib import Path
from typing import Annotated, Optional

import typer

from .update import run_update
from .uv import UvError

app = typer.Typer()


@app.callback()
def main() -> None:
    """Consolidate build requirements for a Python package."""


@app.command("update")
def update(
    from_scratch: bool = typer.Option(False, help="Ignore existing outputs and start over."),
    uv_lock: bool = typer.Option(False, help="Use uv.lock as the package version source."),
    requirements_file: Annotated[Optional[Path], typer.Option("-r")] = None,
    exclude_newer: Optional[str] = typer.Option(None, help="Ignore packages newer than this date."),
    output_dir: Path = typer.Option(".konflux", help="Output directory for requirements files."),
    annotate_requirements: bool = typer.Option(False, help="Add provenance comments to requirements-build.in files."),
    constrain: Annotated[
        Optional[list[str]],
        typer.Option(help="Add version constraint to a build dependency (e.g. 'uv-build<0.11.8')."),
    ] = None,
) -> None:
    """Update build dependency requirements."""
    if not uv_lock and requirements_file is None:
        if Path("uv.lock").exists():
            uv_lock = True
        else:
            typer.echo("Error: specify --uv-lock or -r <file>", err=True)
            raise typer.Exit(code=1)

    if uv_lock and requirements_file is not None:
        typer.echo("Error: --uv-lock and -r are mutually exclusive", err=True)
        raise typer.Exit(code=1)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        run_update(
            uv_lock=uv_lock,
            requirements_file=requirements_file,
            from_scratch=from_scratch,
            exclude_newer=exclude_newer,
            output_dir=output_dir,
            annotate_requirements=annotate_requirements,
            constraints=constrain or [],
        )
    except UvError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
