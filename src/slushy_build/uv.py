import os
import subprocess
from pathlib import Path


class UvError(Exception):
    pass


def uv_export() -> str:
    result = subprocess.run(
        ["uv", "export", "--no-emit-project", "--all-extras", "--no-dev"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UvError(f"uv export failed:\n{result.stderr}")
    return result.stdout


def uv_pip_compile(
    input_file: Path,
    output_file: Path,
    *,
    generate_hashes: bool = False,
    exclude_newer: str | None = None,
) -> None:
    cmd = ["uv", "pip", "compile", "--allow-unsafe"]
    if generate_hashes:
        cmd.append("--generate-hashes")
    if exclude_newer:
        cmd.extend(["--exclude-newer", exclude_newer])
    cmd.extend(["-o", str(output_file), str(input_file)])

    # Isolate from any parent uv/virtualenv environment
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise UvError(f"uv pip compile failed for {input_file}:\n{result.stderr}")
