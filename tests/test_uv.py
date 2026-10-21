import pytest

from slushy_build.uv import uv_pip_compile


@pytest.mark.parametrize("upgrade", [False, True])
def test_compile_upgrade(mocker, tmp_path, upgrade):
    run = mocker.patch("slushy_build.uv.subprocess.run")
    run.return_value.returncode = 0

    uv_pip_compile(tmp_path / "input.in", tmp_path / "output.txt", upgrade=upgrade)

    command = run.call_args.args[0]
    assert ("--upgrade" in command) is upgrade
