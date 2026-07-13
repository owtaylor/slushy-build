import pytest

from slushy_build.build_deps import (
    BuildDependencyError,
    get_build_dependencies,
)
from slushy_build.requirements import PackageVersion


class TestGetBuildDependencies:
    def test_success(self, mocker):
        mock_find = mocker.patch("slushy_build.build_deps.find_build_dependencies")
        mock_find.return_value = ["setuptools>=67.0", "wheel"]
        pkg = PackageVersion("requests", "2.31.0")
        result = get_build_dependencies(pkg)
        assert result == ["setuptools>=67.0", "wheel"]
        mock_find.assert_called_once_with(
            "requests",
            "2.31.0",
            raise_setuppy_parsing_exc=False,
        )

    def test_no_deps(self, mocker):
        mock_find = mocker.patch("slushy_build.build_deps.find_build_dependencies")
        mock_find.return_value = []
        pkg = PackageVersion("pure-pkg", "1.0.0")
        result = get_build_dependencies(pkg)
        assert result == []

    def test_error_raises(self, mocker):
        mock_find = mocker.patch("slushy_build.build_deps.find_build_dependencies")
        mock_find.side_effect = RuntimeError("download failed")
        pkg = PackageVersion("bad-pkg", "1.0.0")
        with pytest.raises(BuildDependencyError, match="bad-pkg"):
            get_build_dependencies(pkg)
