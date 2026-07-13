import logging

from pybuild_deps.finder import find_build_dependencies

from .requirements import PackageVersion

logger = logging.getLogger(__name__)


class BuildDependencyError(Exception):
    pass


def get_build_dependencies(package: PackageVersion) -> list[str]:
    """Return PEP 508 requirement strings for the build deps of a package."""
    try:
        return find_build_dependencies(
            package.name,
            package.version,
            raise_setuppy_parsing_exc=False,
        )
    except Exception as e:
        raise BuildDependencyError(
            f"Failed to find build dependencies for {package.name}=={package.version}: {e}"
        ) from e
