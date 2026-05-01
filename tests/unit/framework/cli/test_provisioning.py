"""Tests for _provisioning helpers used by `agento install` / `agento upgrade`."""
from __future__ import annotations

import json
from pathlib import Path

from agento.framework.cli._provisioning import (
    bump_agento_version,
    detect_python_version,
    enumerate_enabled_extensions,
    materialize_docker_context,
    regenerate_compose,
    render_compose,
    write_project_pyproject,
)


class TestWriteProjectPyproject:
    def test_writes_pinned_dependency(self, tmp_path: Path):
        write_project_pyproject(tmp_path, "myproj", "0.8.0")
        text = (tmp_path / "pyproject.toml").read_text()
        assert 'name = "myproj"' in text
        assert 'agento-core==0.8.0' in text
        assert 'requires-python = ">=3.12"' in text


class TestBumpAgentoVersion:
    def test_replaces_version_pin(self, tmp_path: Path):
        pp = tmp_path / "pyproject.toml"
        pp.write_text(
            '[project]\n'
            'name = "x"\n'
            'dependencies = ["agento-core==0.7.7"]\n'
        )
        bump_agento_version(pp, "0.8.0")
        assert "agento-core==0.8.0" in pp.read_text()
        assert "0.7.7" not in pp.read_text()

    def test_handles_whitespace_around_eq(self, tmp_path: Path):
        pp = tmp_path / "pyproject.toml"
        pp.write_text(
            '[project]\n'
            'dependencies = ["agento-core == 0.7.0"]\n'
        )
        bump_agento_version(pp, "0.9.0")
        assert "agento-core==0.9.0" in pp.read_text()


class TestDetectPythonVersion:
    def test_reads_pyvenv_cfg(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /usr/bin\n"
            "version_info = 3.12.7.final.0\n"
        )
        assert detect_python_version(venv) == "3.12"

    def test_reads_version_key(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version = 3.13.1\n")
        assert detect_python_version(venv) == "3.13"

    def test_falls_back_to_default_when_missing(self, tmp_path: Path):
        # Non-existent venv → fallback "3.12"
        assert detect_python_version(tmp_path / ".venv") == "3.12"

    def test_falls_back_when_unparseable(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version_info = garbage\n")
        assert detect_python_version(venv) == "3.12"


class TestEnumerateEnabledExtensions:
    def _make_project(self, tmp_path: Path) -> Path:
        (tmp_path / "app" / "etc").mkdir(parents=True)
        (tmp_path / "app" / "code").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
        return tmp_path

    def test_lists_only_enabled_pypi_extensions(self, tmp_path: Path):
        proj = self._make_project(tmp_path)
        site = proj / ".venv" / "lib" / "python3.12" / "site-packages"
        for name in ("ext_a", "ext_b", "ext_c"):
            (site / name).mkdir()
            (site / name / "__init__.py").write_text("")

        (proj / "app" / "etc" / "modules.json").write_text(
            json.dumps({"ext_a": True, "ext_b": False, "ext_c": True})
        )

        result = enumerate_enabled_extensions(proj)
        assert result == ["ext_a", "ext_c"]

    def test_excludes_local_modules(self, tmp_path: Path):
        proj = self._make_project(tmp_path)
        site = proj / ".venv" / "lib" / "python3.12" / "site-packages"

        # Same-name local module shadows the PyPI one — local wins.
        (site / "k3_jira").mkdir()
        (site / "k3_jira" / "__init__.py").write_text("")
        (proj / "app" / "code" / "k3_jira").mkdir()
        (proj / "app" / "code" / "k3_jira" / "module.json").write_text("{}")

        (proj / "app" / "etc" / "modules.json").write_text(
            json.dumps({"k3_jira": True})
        )

        # Local takes precedence — not included in PyPI mounts.
        assert enumerate_enabled_extensions(proj) == []

    def test_excludes_disabled_and_missing(self, tmp_path: Path):
        proj = self._make_project(tmp_path)
        (proj / "app" / "etc" / "modules.json").write_text(
            json.dumps({"ghost": True, "off": False})
        )
        # Neither package is installed in venv; both are missing.
        assert enumerate_enabled_extensions(proj) == []


class TestRenderCompose:
    TEMPLATE = (
        "services:\n"
        "  cron:\n"
        "    volumes:\n"
        "      - ../.venv/lib/python{{ python_version }}/site-packages/agento:/opt/agento-src/agento:ro\n"
        "      # {{ extension_mounts_cron }}\n"
        "    environment:\n"
        "      - PY={{ python_version }}\n"
    )

    def test_substitutes_python_version(self):
        out = render_compose(self.TEMPLATE, python_version="3.13", extensions=[])
        assert "python3.13" in out
        assert "PY=3.13" in out

    def test_no_extensions_removes_placeholder_line(self):
        out = render_compose(self.TEMPLATE, python_version="3.12", extensions=[])
        assert "extension_mounts_cron" not in out
        # Placeholder line is gone — no orphan comment markers in output.
        assert "# " not in out.split("environment:")[0].splitlines()[-1]

    def test_extensions_are_inserted(self):
        out = render_compose(
            self.TEMPLATE,
            python_version="3.12",
            extensions=["ext_a", "ext_b"],
        )
        assert "/site-packages/ext_a:/opt/agento-src/ext_a:ro" in out
        assert "/site-packages/ext_b:/opt/agento-src/ext_b:ro" in out
        # Mounts come before `environment:` block.
        assert out.index("ext_a") < out.index("environment:")


class TestMaterializeDockerContext:
    def _seed_project(self, tmp_path: Path) -> Path:
        # Minimal project: pyproject.toml + uv.lock so cron context is complete.
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["agento-core==0.8.0"]\n'
        )
        (tmp_path / "uv.lock").write_text("# lock\n")
        return tmp_path

    def test_writes_dockerfiles_and_stamp(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        materialize_docker_context(proj, force=True)
        target = proj / ".agento" / "docker"
        assert (target / "sandbox" / "Dockerfile").is_file()
        assert (target / "cron" / "Dockerfile").is_file()
        assert (target / "toolbox" / "Dockerfile").is_file()
        assert (target / "version").is_file()

    def test_copies_project_pyproject_into_cron_context(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        materialize_docker_context(proj, force=True)
        copied = (proj / ".agento" / "docker" / "cron" / "pyproject.toml").read_text()
        assert "agento-core==0.8.0" in copied
        assert (proj / ".agento" / "docker" / "cron" / "uv.lock").read_text() == "# lock\n"

    def test_idempotent_when_stamp_matches(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        materialize_docker_context(proj, force=True)
        # Mutate the stamped tree — a second call without force MUST NOT touch it.
        marker = proj / ".agento" / "docker" / "cron" / "Dockerfile"
        marker.write_text("HELLO_MARKER\n")
        materialize_docker_context(proj, force=False)
        assert marker.read_text() == "HELLO_MARKER\n"

    def test_force_reinitializes(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        materialize_docker_context(proj, force=True)
        marker = proj / ".agento" / "docker" / "cron" / "Dockerfile"
        marker.write_text("HELLO_MARKER\n")
        materialize_docker_context(proj, force=True)
        # force=True wipes and recopies — original Dockerfile content is restored.
        assert "HELLO_MARKER" not in marker.read_text()


class TestRegenerateCompose:
    def _seed_project(self, tmp_path: Path) -> Path:
        (tmp_path / "docker").mkdir()
        (tmp_path / "app" / "etc").mkdir(parents=True)
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version_info = 3.12.7\n")
        return tmp_path

    def test_writes_compose_file_with_python_version(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        regenerate_compose(proj)
        content = (proj / "docker" / "docker-compose.yml").read_text()
        assert "python3.12" in content
        # No GHCR images — local build only.
        assert "ghcr.io" not in content
        assert "build:" in content

    def test_inserts_pypi_extension_mounts(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        site = proj / ".venv" / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        (site / "agento_jira_ext").mkdir()
        (site / "agento_jira_ext" / "__init__.py").write_text("")
        (proj / "app" / "etc" / "modules.json").write_text(
            json.dumps({"agento_jira_ext": True})
        )

        regenerate_compose(proj)
        content = (proj / "docker" / "docker-compose.yml").read_text()
        assert "agento_jira_ext:/opt/agento-src/agento_jira_ext:ro" in content

    def test_no_extensions_means_no_orphan_placeholder(self, tmp_path: Path):
        proj = self._seed_project(tmp_path)
        regenerate_compose(proj)
        content = (proj / "docker" / "docker-compose.yml").read_text()
        # Neither raw placeholder nor stray comment marker for it.
        assert "extension_mounts_sandbox" not in content
        assert "extension_mounts_cron" not in content
