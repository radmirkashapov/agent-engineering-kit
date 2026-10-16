from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_engineering_kit.discovery import discover_components
import agent_engineering_kit.discovery as discovery_module
from agent_engineering_kit.errors import AgentKitError


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_maven_modules_keep_coordinates_and_dependencies(tmp_path: Path) -> None:
    _write(tmp_path, "pom.xml", "<project><groupId>dev.example</groupId><artifactId>parent</artifactId><version>1</version><modules><module>core</module><module>api</module></modules></project>")
    _write(tmp_path, "core/pom.xml", "<project><parent><groupId>dev.example</groupId><artifactId>parent</artifactId><version>1</version></parent><artifactId>core</artifactId></project>")
    _write(tmp_path, "api/pom.xml", "<project><parent><groupId>dev.example</groupId><artifactId>parent</artifactId><version>1</version></parent><artifactId>api</artifactId><dependencies><dependency><groupId>dev.example</groupId><artifactId>core</artifactId></dependency></dependencies></project>")
    rows = discover_components({"root": tmp_path})
    by_path = {row["path"]: row for row in rows}
    assert by_path["api"]["id"] == "maven:dev.example:api"
    assert by_path["api"]["dependencies"] == ["maven:dev.example:core"]
    assert by_path["api"]["evidence"] == ["api/pom.xml"]
    assert by_path["api"]["confidence"] == "high"


def test_gradle_settings_discover_modules_and_project_dependency(tmp_path: Path) -> None:
    _write(tmp_path, "settings.gradle.kts", 'rootProject.name = "platform"\ninclude(":core", ":api")\n')
    _write(tmp_path, "core/build.gradle.kts", "plugins { java }\n")
    _write(tmp_path, "api/build.gradle.kts", 'dependencies { implementation(project(":core")) }\n')
    rows = discover_components({"root": tmp_path})
    api = next(row for row in rows if row["path"] == "api")
    assert api["id"] == "gradle:platform:api"
    assert api["dependencies"] == ["gradle:platform:core"]


def test_node_workspace_uses_package_names_and_dependencies(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", json.dumps({"name": "acme", "workspaces": ["packages/*"]}))
    _write(tmp_path, "packages/core/package.json", json.dumps({"name": "@acme/core"}))
    _write(tmp_path, "packages/web/package.json", json.dumps({"name": "@acme/web", "dependencies": {"@acme/core": "workspace:*"}}))
    rows = discover_components({"root": tmp_path})
    web = next(row for row in rows if row["path"] == "packages/web")
    assert web["id"] == "node:acme/web"
    assert web["dependencies"] == ["node:acme/core"]


def test_go_work_and_modules(tmp_path: Path) -> None:
    _write(tmp_path, "go.work", "go 1.23\nuse (\n ./core\n ./api\n)\n")
    _write(tmp_path, "core/go.mod", "module example.com/core\n")
    _write(tmp_path, "api/go.mod", "module example.com/api\nrequire example.com/core v0.0.0\n")
    rows = discover_components({"root": tmp_path})
    api = next(row for row in rows if row["path"] == "api")
    assert api["id"] == "go:example.com/api"
    assert api["dependencies"] == ["go:example.com/core"]


def test_cargo_workspace_and_path_dependency(tmp_path: Path) -> None:
    _write(tmp_path, "Cargo.toml", '[workspace]\nmembers = ["crates/*"]\n')
    _write(tmp_path, "crates/core/Cargo.toml", '[package]\nname = "core"\nversion = "0.1"\n')
    _write(tmp_path, "crates/api/Cargo.toml", '[package]\nname = "api"\nversion = "0.1"\n[dependencies]\ncore = { path = "../core" }\n')
    rows = discover_components({"root": tmp_path})
    api = next(row for row in rows if row["path"] == "crates/api")
    assert api["id"] == "cargo:api"
    assert api["dependencies"] == ["cargo:core"]


def test_dotnet_solution_and_project_reference(tmp_path: Path) -> None:
    _write(tmp_path, "App.sln", 'Project("{x}") = "Core", "Core/Core.csproj", "{a}"\nProject("{x}") = "Api", "Api/Api.csproj", "{b}"\n')
    _write(tmp_path, "Core/Core.csproj", "<Project><PropertyGroup><AssemblyName>Core</AssemblyName></PropertyGroup></Project>")
    _write(tmp_path, "Api/Api.csproj", '<Project><ItemGroup><ProjectReference Include="../Core/Core.csproj" /></ItemGroup></Project>')
    rows = discover_components({"root": tmp_path})
    api = next(row for row in rows if row["path"] == "Api")
    assert api["id"] == "dotnet:Api"
    assert api["dependencies"] == ["dotnet:Core"]


def test_python_project_and_bazel_target(tmp_path: Path) -> None:
    _write(tmp_path, "service/pyproject.toml", '[project]\nname = "sample-service"\ndependencies = ["sample-core>=1"]\n')
    _write(tmp_path, "core/pyproject.toml", '[project]\nname = "sample-core"\n')
    _write(tmp_path, "bazel/BUILD.bazel", 'py_library(name = "shared", deps = ["//core:lib"])\n')
    rows = discover_components({"root": tmp_path})
    service = next(row for row in rows if row["path"] == "service")
    assert service["id"] == "python:sample-service"
    assert service["dependencies"] == ["python:sample-core"]
    assert any(row["id"] == "bazel://bazel:shared" for row in rows)


def test_discovery_is_stable_and_skips_generated_directories(tmp_path: Path) -> None:
    _write(tmp_path, "src/pyproject.toml", '[project]\nname = "stable"\n')
    _write(tmp_path, "node_modules/junk/package.json", '{"name":"junk"}')
    first = discover_components({"root": tmp_path})
    second = discover_components({"root": tmp_path})
    assert first == second
    assert [row["id"] for row in first] == ["python:stable"]


def test_duplicate_build_coordinates_are_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "a/pyproject.toml", '[project]\nname = "same"\n')
    _write(tmp_path, "b/pyproject.toml", '[project]\nname = "same"\n')
    with pytest.raises(AgentKitError, match="component ID"):
        discover_components({"root": tmp_path})


def test_excluded_component_is_not_in_inventory_or_dependencies(tmp_path: Path) -> None:
    _write(tmp_path, "app/pyproject.toml", '[project]\nname = "app"\ndependencies = ["hidden"]\n')
    _write(tmp_path, "generated/pyproject.toml", '[project]\nname = "hidden"\n')
    rows = discover_components({"root": tmp_path}, exclude_paths=["generated"])
    assert [row["id"] for row in rows] == ["python:app"]
    assert rows[0]["dependencies"] == []


def test_dependency_ids_include_repository_namespace(tmp_path: Path) -> None:
    core = tmp_path / "core-repo"
    _write(core, "core/pyproject.toml", '[project]\nname = "core"\n')
    _write(core, "app/pyproject.toml", '[project]\nname = "app"\ndependencies = ["core"]\n')
    rows = discover_components({"backend": core})
    app = next(row for row in rows if row["path"] == "app")
    assert app["id"] == "python:backend/app"
    assert app["dependencies"] == ["python:backend/core"]


def test_python_310_toml_fallback_reads_workspace_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "tomllib", None)
    _write(tmp_path, "pyproject.toml", '[project]\nname = "app"\ndependencies = ["core>=1", "requests"]\n')
    _write(tmp_path, "core/pyproject.toml", '[project]\nname = "core"\n')
    rows = discover_components({"root": tmp_path})
    app = next(row for row in rows if row["id"] == "python:app")
    assert app["dependencies"] == ["python:core"]


def test_nested_repository_is_not_scanned_through_parent_binding(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    _write(backend, "pyproject.toml", '[project]\nname = "backend"\n')

    rows = discover_components({"root": tmp_path, "backend": backend})

    assert [(row["id"], row["repository"], row["path"]) for row in rows] == [
        ("python:backend/backend", "backend", ".")
    ]
