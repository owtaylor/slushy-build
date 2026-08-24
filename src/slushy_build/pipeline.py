import json
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PREFETCH_PARAM = "prefetch-input"


class PipelineError(Exception):
    """Raised when a PipelineRun's prefetch-input is present but unusable."""


def update_pipelines(
    pipeline_dir: Path,
    *,
    requirements_file: Path | None,
    build_files: list[Path],
) -> None:
    """Sync the pip entry of each PipelineRun's prefetch-input to the generated files.

    Scans ``pipeline_dir`` for ``*.yaml`` files. For each file that is a
    ``kind: PipelineRun`` with a ``prefetch-input`` param, the pip entry's
    ``requirements_build_files`` (and, when ``requirements_file`` is given, its
    ``requirements_files``) are updated to match the freshly generated files.

    Corner cases:
      * Invalid YAML, or a PipelineRun missing the prefetch-input param, are
        warned about and skipped.
      * A prefetch-input value that is not valid JSON, not a list of dicts, or
        whose scalar cannot be located in the file for an in-place edit (e.g. a
        double-quoted or block scalar), raises :class:`PipelineError`.
    """
    if not pipeline_dir.is_dir():
        return

    for yaml_file in sorted(pipeline_dir.glob("*.yaml")):
        _update_file(yaml_file, requirements_file=requirements_file, build_files=build_files)


def _update_file(
    yaml_file: Path,
    *,
    requirements_file: Path | None,
    build_files: list[Path],
) -> None:
    text = yaml_file.read_text()

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        logger.warning("Skipping %s: invalid YAML (%s)", yaml_file, e)
        return

    if not isinstance(doc, dict) or doc.get("kind") != "PipelineRun":
        return

    params = doc.get("spec", {}).get("params") if isinstance(doc.get("spec"), dict) else None
    param = None
    if isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and p.get("name") == PREFETCH_PARAM:
                param = p
                break

    if param is None:
        logger.warning("Skipping %s: no %s param", yaml_file, PREFETCH_PARAM)
        return

    old_scalar = param.get("value")
    if not isinstance(old_scalar, str):
        raise PipelineError(f"{yaml_file}: {PREFETCH_PARAM} value is not a string")

    try:
        entries = json.loads(old_scalar)
    except json.JSONDecodeError as e:
        raise PipelineError(f"{yaml_file}: {PREFETCH_PARAM} is not valid JSON ({e})") from e

    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise PipelineError(f"{yaml_file}: {PREFETCH_PARAM} must be a list of objects")

    _apply(entries, requirements_file=requirements_file, build_files=build_files)

    new_scalar = json.dumps(entries)
    if new_scalar == old_scalar:
        logger.info("%s: %s already up to date", yaml_file, PREFETCH_PARAM)
        return

    if old_scalar not in text:
        raise PipelineError(
            f"{yaml_file}: could not locate {PREFETCH_PARAM} value for in-place update "
            "(is it double-quoted or a block scalar?)"
        )

    yaml_file.write_text(text.replace(old_scalar, new_scalar, 1))
    logger.info("Updated %s in %s", PREFETCH_PARAM, yaml_file)


def _apply(
    entries: list[dict],
    *,
    requirements_file: Path | None,
    build_files: list[Path],
) -> None:
    pip = next((e for e in entries if e.get("type") == "pip"), None)
    if pip is None:
        pip = {"type": "pip", "path": "."}
        entries.append(pip)

    if requirements_file is not None:
        pip["requirements_files"] = [str(requirements_file)]
    pip["requirements_build_files"] = [str(f) for f in build_files]
