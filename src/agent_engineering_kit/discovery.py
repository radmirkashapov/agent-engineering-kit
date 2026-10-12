"""Read-only build metadata discovery for logical project components."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None  # type: ignore[assignment]

import yaml

from .errors import AgentKitError


_SKIP = {".git", ".venv", "venv", "node_modules", "vendor", "target", "build", "dist", ".gradle", ".next"}
_MANIFESTS = {"pom.xml", "settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "package.json", "go.mod", "Cargo.toml", "pyproject.toml", "BUILD", "BUILD.bazel"}


def _files(root: Path) -> list[Path]:
    found: list[Path] = []
    for directory, dirs, files in __import__("os").walk(root):
        dirs[:] = sorted(name for name in dirs if name not in _SKIP and not name.startswith("."))
        found.extend(Path(directory) / name for name in files if name in _MANIFESTS or name.endswith((".csproj", ".fsproj", ".sln", ".slnx")))
    return sorted(found)


def _relative(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    return "." if value == "." else value


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _xml(path: Path) -> ET.Element | None:
    try:
        root = ET.parse(path).getroot()
        for node in root.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        return root
    except ET.ParseError:
        return None


def _child_text(node: ET.Element, path: str) -> str:
    child = node.find(path)
    return (child.text or "").strip() if child is not None else ""


def _toml(path: Path) -> dict[str, Any]:
    if tomllib is not None:
        try:
            return tomllib.loads(_text(path))
        except (ValueError, UnicodeError):
            return {}
    # Python 3.10 fallback covers the metadata fields used by discovery.
    data: dict[str, Any] = {}
    section: dict[str, Any] = data
    for line in _text(path).splitlines():
        heading = re.match(r"^\[([\w.-]+)\]$", line.strip())
        if heading:
            section = data
            for part in heading.group(1).split("."):
                section = section.setdefault(part, {})
            continue
        pair = re.match(r"^\s*([\w-]+)\s*=\s*(.+)$", line)
        if pair:
            try:
                section[pair.group(1)] = yaml.safe_load(pair.group(2))
            except yaml.YAMLError:
                pass
    return data


def _add(rows: list[dict[str, Any]], repo: str, root: Path, path: Path, kind: str, coordinate: str, evidence: Path, dependencies: list[str] | None = None, confidence: str = "high") -> None:
    if not coordinate:
        return
    prefix = "" if repo == "root" else f"{repo}/"
    rows.append({"id": f"{kind}:{prefix}{coordinate}", "repository": repo, "path": _relative(path, root), "type": kind, "dependencies": dependencies or [], "evidence": [_relative(evidence, root)], "confidence": confidence})


def _maven(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name != "pom.xml":
            continue
        xml = _xml(path)
        if xml is None:
            continue
        group = _child_text(xml, "groupId") or _child_text(xml, "parent/groupId")
        artifact = _child_text(xml, "artifactId")
        dependencies = [f"maven:{_child_text(node, 'groupId')}:{_child_text(node, 'artifactId')}" for node in xml.findall("dependencies/dependency") if _child_text(node, "groupId") and _child_text(node, "artifactId")]
        _add(rows, repo, root, path.parent, "maven", f"{group}:{artifact}" if group else artifact, path, dependencies, "high" if group and artifact else "medium")


def _gradle(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    settings = [path for path in files if path.name.startswith("settings.gradle")]
    builds = {path.parent: path for path in files if path.name.startswith("build.gradle")}
    for setting in settings:
        content = _text(setting)
        name_match = re.search(r"rootProject\.name\s*=\s*['\"]([^'\"]+)", content)
        project = name_match.group(1) if name_match else setting.parent.name
        modules = re.findall(r"['\"](:[\w:.-]+)['\"]", "\n".join(line for line in content.splitlines() if "include" in line))
        for module in ["", *modules]:
            module_path = setting.parent.joinpath(*module.strip(":").split(":")) if module else setting.parent
            build = builds.get(module_path)
            if module and not build:
                continue
            evidence = build or setting
            deps = re.findall(r"project\s*\(\s*['\"](:[\w:.-]+)['\"]\s*\)", _text(build)) if build else []
            coordinate = project + (":" + module.strip(":").replace(":", ":") if module else "")
            _add(rows, repo, root, module_path, "gradle", coordinate, evidence, [f"gradle:{project}:{item.strip(':')}" for item in deps])


def _node(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name != "package.json":
            continue
        try:
            data = json.loads(_text(path))
        except (ValueError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if not isinstance(name, str):
            continue
        deps = [f"node:{dep.lstrip('@')}" for field in ("dependencies", "devDependencies", "peerDependencies") for dep in data.get(field, {}) if isinstance(data.get(field), dict)]
        _add(rows, repo, root, path.parent, "node", name.lstrip("@"), path, deps)


def _go(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name != "go.mod":
            continue
        content = _text(path)
        match = re.search(r"(?m)^module\s+(\S+)", content)
        if not match:
            continue
        deps = re.findall(r"(?m)^\s*(?:require\s+)?([\w.-]+(?:/[\w.-]+)+)\s+v\d", content)
        _add(rows, repo, root, path.parent, "go", match.group(1), path, [f"go:{dep}" for dep in deps])


def _cargo(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name != "Cargo.toml":
            continue
        data = _toml(path)
        package = data.get("package", {})
        name = package.get("name") if isinstance(package, dict) else None
        if not isinstance(name, str):
            continue
        dependencies = data.get("dependencies", {})
        deps = [f"cargo:{value.get('package', key) if isinstance(value, dict) else key}" for key, value in dependencies.items()] if isinstance(dependencies, dict) else []
        _add(rows, repo, root, path.parent, "cargo", name, path, deps)


def _dotnet(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.suffix not in {".csproj", ".fsproj"}:
            continue
        xml = _xml(path)
        if xml is None:
            continue
        assembly = next((node.text for node in xml.findall(".//AssemblyName") if node.text), path.stem)
        references = [Path(node.attrib["Include"].replace("\\", "/")).stem for node in xml.findall(".//ProjectReference") if node.attrib.get("Include")]
        deps = [f"dotnet:{name}" for name in references]
        _add(rows, repo, root, path.parent, "dotnet", assembly, path, deps)


def _python(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name != "pyproject.toml":
            continue
        data = _toml(path)
        project = data.get("project", {})
        tool = data.get("tool", {})
        poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
        name = project.get("name") or poetry.get("name")
        if not isinstance(name, str):
            continue
        deps = []
        for value in project.get("dependencies", []):
            if isinstance(value, str) and (match := re.match(r"[A-Za-z0-9_.-]+", value)):
                deps.append(f"python:{match.group(0).lower().replace('_', '-')}")
        _add(rows, repo, root, path.parent, "python", name.lower().replace("_", "-"), path, deps)


def _bazel(rows: list[dict[str, Any]], repo: str, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.name not in {"BUILD", "BUILD.bazel"}:
            continue
        content = _text(path)
        package = "" if path.parent == root else path.parent.relative_to(root).as_posix()
        for match in re.finditer(r"\b\w+_(?:library|binary|test)\s*\(\s*name\s*=\s*['\"]([^'\"]+)['\"]", content):
            _add(rows, repo, root, path.parent, "bazel", f"//{package}:{match.group(1)}", path, [], "medium")


def discover_components(repositories: dict[str, Path], *, exclude_paths: list[str] | None = None) -> list[dict[str, Any]]:
    """Discover components from build metadata without writing to repositories."""
    rows: list[dict[str, Any]] = []
    for repository, root in sorted(repositories.items()):
        root = root.expanduser().resolve()
        if not root.is_dir():
            continue
        files = _files(root)
        for discoverer in (_maven, _gradle, _node, _go, _cargo, _dotnet, _python, _bazel):
            discoverer(rows, repository, root, files)
    exclusions = [value.rstrip("/") for value in (exclude_paths or [])]
    rows = [row for row in rows if not any((row["path"] if row["repository"] == "root" else f"{row['repository']}/{row['path']}") == path or (row["path"] if row["repository"] == "root" else f"{row['repository']}/{row['path']}").startswith(path + "/") for path in exclusions)]
    seen: dict[str, str] = {}
    for row in rows:
        if row["id"] in seen:
            raise AgentKitError(f"Повторяющийся component ID: {row['id']} ({seen[row['id']]} и {row['path']})")
        seen[row["id"]] = row["path"]
    ids = set(seen)
    for row in rows:
        resolved: set[str] = set()
        for dependency in row["dependencies"]:
            kind, coordinate = dependency.split(":", 1)
            local = f"{kind}:{row['repository']}/{coordinate}" if row["repository"] != "root" else dependency
            matches = [value for value in ids if value == dependency or value.endswith("/" + coordinate) and value.startswith(kind + ":")]
            target = local if local in ids else dependency if dependency in ids else matches[0] if len(matches) == 1 else None
            if target and target != row["id"]:
                resolved.add(target)
        row["dependencies"] = sorted(resolved)
    return sorted(rows, key=lambda row: (row["repository"], row["type"], row["id"], row["path"]))
