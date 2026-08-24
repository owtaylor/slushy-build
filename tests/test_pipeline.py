import json
from pathlib import Path

import pytest

from slushy_build.pipeline import PipelineError, update_pipelines


def _pipelinerun(prefetch_value: str | None, *, extra_params: str = "") -> str:
    """Build a minimal PipelineRun yaml, optionally with a prefetch-input param."""
    params = "    - name: git-url\n      value: '{{ source_url }}'\n"
    if prefetch_value is not None:
        params += f"\n    # Hermeto prefetch note\n    - name: prefetch-input\n      value: '{prefetch_value}'\n"
    params += extra_params
    return (
        "apiVersion: tekton.dev/v1\n"
        "kind: PipelineRun\n"
        "metadata:\n"
        "  name: example-pr\n"
        "spec:\n"
        "  params:\n"
        f"{params}"
        "  pipelineRef:\n"
        "    name: pipeline-build-multiarch\n"
    )


def _get_prefetch(text: str) -> list:
    import yaml

    doc = yaml.safe_load(text)
    for param in doc["spec"]["params"]:
        if param["name"] == "prefetch-input":
            return json.loads(param["value"])
    raise AssertionError("no prefetch-input param")


@pytest.fixture
def pipeline_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".tekton"
    d.mkdir()
    return d


BUILD_FILES = [
    Path(".konflux/requirements-build.txt"),
    Path(".konflux/requirements-build-1.txt"),
]
REQ_FILE = Path(".konflux/requirements.txt")


class TestUpdatePipelines:
    def test_updates_existing_pip_entry(self, pipeline_dir):
        value = (
            '[{"type": "pip", "path": ".", "requirements_files": [".konflux/requirements.txt"], '
            '"requirements_build_files": [".konflux/requirements-build.1.txt"]}, '
            '{"type": "rpm", "path": "."}]'
        )
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun(value))

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        entries = _get_prefetch(yaml_file.read_text())
        pip = next(e for e in entries if e["type"] == "pip")
        assert pip["requirements_files"] == [".konflux/requirements.txt"]
        assert pip["requirements_build_files"] == [
            ".konflux/requirements-build.txt",
            ".konflux/requirements-build-1.txt",
        ]
        # rpm entry preserved
        assert any(e["type"] == "rpm" for e in entries)

    def test_preserves_comments_and_formatting(self, pipeline_dir):
        value = '[{"type": "pip", "requirements_build_files": [".konflux/old.txt"]}, {"type": "rpm", "path": "."}]'
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun(value))

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        text = yaml_file.read_text()
        assert "# Hermeto prefetch note" in text
        assert "apiVersion: tekton.dev/v1" in text
        assert "pipelineRef:" in text

    def test_adds_missing_pip_entry(self, pipeline_dir):
        value = '[{"type": "rpm", "path": "."}]'
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun(value))

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        entries = _get_prefetch(yaml_file.read_text())
        pip = next(e for e in entries if e["type"] == "pip")
        assert pip["type"] == "pip"
        assert pip["path"] == "."
        assert pip["requirements_files"] == [".konflux/requirements.txt"]
        assert pip["requirements_build_files"] == [
            ".konflux/requirements-build.txt",
            ".konflux/requirements-build-1.txt",
        ]
        assert any(e["type"] == "rpm" for e in entries)

    def test_r_mode_leaves_requirements_files_untouched(self, pipeline_dir):
        value = (
            '[{"type": "pip", "requirements_files": ["custom/requirements.txt"], '
            '"requirements_build_files": [".konflux/old.txt"]}]'
        )
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun(value))

        update_pipelines(pipeline_dir, requirements_file=None, build_files=BUILD_FILES)

        pip = next(e for e in _get_prefetch(yaml_file.read_text()) if e["type"] == "pip")
        assert pip["requirements_files"] == ["custom/requirements.txt"]
        assert pip["requirements_build_files"] == [
            ".konflux/requirements-build.txt",
            ".konflux/requirements-build-1.txt",
        ]

    def test_invalid_yaml_warns_and_skips(self, pipeline_dir, caplog):
        yaml_file = pipeline_dir / "broken.yaml"
        yaml_file.write_text("kind: PipelineRun\nspec: [unbalanced\n")
        original = yaml_file.read_text()

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        assert yaml_file.read_text() == original
        assert any("broken.yaml" in r.message for r in caplog.records)

    def test_non_pipelinerun_skipped(self, pipeline_dir):
        yaml_file = pipeline_dir / "other.yaml"
        content = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: foo\n"
        yaml_file.write_text(content)

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        assert yaml_file.read_text() == content

    def test_missing_prefetch_param_warns_and_skips(self, pipeline_dir, caplog):
        yaml_file = pipeline_dir / "no_prefetch.yaml"
        yaml_file.write_text(_pipelinerun(None))
        original = yaml_file.read_text()

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        assert yaml_file.read_text() == original
        assert any("no_prefetch.yaml" in r.message for r in caplog.records)

    def test_invalid_json_raises(self, pipeline_dir):
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun("not json at all"))

        with pytest.raises(PipelineError):
            update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

    def test_json_not_list_of_dicts_raises(self, pipeline_dir):
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun('{"type": "pip"}'))

        with pytest.raises(PipelineError):
            update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

    def test_json_list_with_non_dict_raises(self, pipeline_dir):
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun('[{"type": "pip"}, "rpm"]'))

        with pytest.raises(PipelineError):
            update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

    def test_missing_dir_is_noop(self, tmp_path):
        # Should not raise
        update_pipelines(tmp_path / "nonexistent", requirements_file=REQ_FILE, build_files=BUILD_FILES)

    def test_already_up_to_date_no_rewrite(self, pipeline_dir, mocker):
        """When the value already matches, the file must not be rewritten at all."""
        value = (
            '[{"type": "pip", "path": ".", "requirements_files": [".konflux/requirements.txt"], '
            '"requirements_build_files": [".konflux/requirements-build.txt", ".konflux/requirements-build-1.txt"]}]'
        )
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(_pipelinerun(value))

        write = mocker.patch("pathlib.Path.write_text")
        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)
        write.assert_not_called()

    def test_unlocatable_scalar_raises(self, pipeline_dir):
        """A value whose scalar can't be found verbatim (double-quoted with escapes) is a hard error."""
        # Double-quoted YAML: safe_load unescapes \" so the parsed string won't
        # appear verbatim in the raw text, making an in-place edit impossible.
        double_quoted = '"[{\\"type\\": \\"pip\\", \\"requirements_build_files\\": [\\".konflux/old.txt\\"]}]"'
        yaml_file = pipeline_dir / "pull_request.yaml"
        yaml_file.write_text(
            "apiVersion: tekton.dev/v1\n"
            "kind: PipelineRun\n"
            "spec:\n"
            "  params:\n"
            "    - name: prefetch-input\n"
            f"      value: {double_quoted}\n"
        )

        with pytest.raises(PipelineError):
            update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

    def test_processes_all_yaml_files(self, pipeline_dir):
        value = '[{"type": "pip", "requirements_build_files": [".konflux/old.txt"]}]'
        for name in ("a.yaml", "b.yaml"):
            (pipeline_dir / name).write_text(_pipelinerun(value))

        update_pipelines(pipeline_dir, requirements_file=REQ_FILE, build_files=BUILD_FILES)

        for name in ("a.yaml", "b.yaml"):
            pip = next(e for e in _get_prefetch((pipeline_dir / name).read_text()) if e["type"] == "pip")
            assert pip["requirements_build_files"] == [
                ".konflux/requirements-build.txt",
                ".konflux/requirements-build-1.txt",
            ]
