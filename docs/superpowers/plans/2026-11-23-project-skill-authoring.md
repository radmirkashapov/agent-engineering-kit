# Project Skill Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe authoring commands for corporate bundled skills and sibling project-skills checkouts, plus indexes that let agents discover project and effective skills.

**Architecture:** A new `skill_authoring.py` owns validation, safe copy, Git checkout verification and tracked project index generation. `projects.py` owns manifest construction, while `clients.py` produces the runtime effective index from the existing precedence resolver. `cli.py` only parses arguments and delegates to these services.

**Tech Stack:** Python 3.10+, argparse, pathlib, shutil, subprocess through `run_command`, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-project-skill-authoring-design.md`

## Global Constraints

- Never write project-specific skills into a product repository or Kit-managed checkout.
- Never create commits, branches, push, PR/MR or a remote repository.
- Validate `SKILL.md` against `schemas/skill.schema.json` before publication.
- Source and target skill IDs must match their directory names.
- Existing target directories require explicit `--replace` and a clean developer checkout.
- TTY prompts are skipped for non-interactive stdin and explicit CLI options.
- All user-visible Russian documentation and messages remain professional Russian.

---

### Task 1: Implement safe authoring service and tracked project index

**Files:**
- Create: `src/agent_engineering_kit/skill_authoring.py`
- Test: `tests/test_skill_authoring.py`

**Interfaces:**
- Consumes: `LogicalProject`, `run_command`, `validate_skill_directory`, `atomic_write`.
- Produces: `add_bundled_skill(repository, source, identifier=None, replace=False) -> Path`; `checkout_project_skills(project, destination) -> Path`; `add_project_skill(repository, project, source, checkout, identifier=None, replace=False) -> Path`; `write_project_skill_index(repository, checkout) -> Path`.

- [ ] **Step 1: Write failing service tests**

```python
def test_add_bundled_skill_copies_validated_directory(tmp_path, kit_repository):
    source = write_skill(tmp_path / "source", "review-api", "Review API changes.")
    target = add_bundled_skill(kit_repository, source)
    assert target == kit_repository / "skills/first-party/review-api"
    assert (target / "SKILL.md").is_file()

def test_project_skill_checkout_rejects_product_repository(fixture):
    with pytest.raises(AgentKitError, match="product repository"):
        add_project_skill(fixture.repository, fixture.project, fixture.source, fixture.project.root)

def test_add_project_skill_writes_deterministic_index(fixture):
    checkout = fixture.clone_sibling()
    add_project_skill(fixture.repository, fixture.project, fixture.source, checkout)
    assert "review-api" in (checkout / "skills/INDEX.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/test_skill_authoring.py -q`

Expected: collection fails because `agent_engineering_kit.skill_authoring` does not exist.

- [ ] **Step 3: Implement minimal service**

```python
def add_bundled_skill(repository: Path, source: Path, *, identifier: str | None = None, replace: bool = False) -> Path:
    resolved = _validated_source(repository, source, identifier)
    return _copy_skill(resolved.source, repository / "skills" / "first-party" / resolved.identifier, replace=replace)

def write_project_skill_index(repository: Path, checkout: Path) -> Path:
    skills = _project_skill_directories(repository, checkout)
    rows = [f"| `{item.identifier}` | {item.description} | `{item.identifier}/SKILL.md` |" for item in skills]
    target = checkout / "skills" / "INDEX.md"
    atomic_write(target, "# Project skills\\n\\n| ID | Назначение | Определение |\\n|---|---|---|\\n" + "\\n".join(rows) + "\\n")
    return target
```

Require regular directories (no symlink source/destination), normalized `origin` equality, empty checkout destination for clone, and a clean `git status --porcelain` before `--replace` can overwrite a tracked skill. Stage the copy in a temporary sibling and atomically replace it only after validation.

- [ ] **Step 4: Verify GREEN**

Run: `uv run --extra dev pytest tests/test_skill_authoring.py -q`

Expected: all new unit and Git-fixture tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_engineering_kit/skill_authoring.py tests/test_skill_authoring.py
git commit -m "feat(skills): add safe skill authoring service"
```

### Task 2: Configure project skills during init, including TTY flow

**Files:**
- Modify: `src/agent_engineering_kit/projects.py`
- Modify: `src/agent_engineering_kit/cli.py`
- Modify: `tests/test_projects.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `init_project(..., skills_repository_url: str | None, skills_default_branch: str = "main")`.
- Produces: a validated optional `skills.repository` manifest section.

- [ ] **Step 1: Write failing init and CLI tests**

```python
def test_project_init_records_explicit_skills_repository(tmp_path, kit_repository):
    project = init_project(tmp_path / "demo", kit_repository, paths(tmp_path, kit_repository),
                           skills_repository_url="git@gitlab.example:team/demo-skills.git")
    assert project.skills_repository == {"url": "git@gitlab.example:team/demo-skills.git", "default_branch": "main"}

def test_project_init_parses_skills_repository_arguments():
    args = _parser().parse_args(["project", "init", "--skills-repository-url", "git@gitlab.example:team/demo-skills.git"])
    assert args.skills_repository_url.endswith("demo-skills.git")

def test_interactive_project_init_prompts_for_skills_repository(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "git@gitlab.example:team/demo-skills.git")
    assert _interactive_project_setup(REPOSITORY)["skills_repository_url"].endswith("demo-skills.git")

def test_project_init_keeps_full_codebase_memory_and_serena_indexing(tmp_path, kit_repository, monkeypatch):
    calls = []
    monkeypatch.setattr(projects_module.ProjectMemoryManager, "index", lambda _self, _project, *, mode: calls.append(mode) or {"status": "PASS"})
    init_project(tmp_path / "demo", kit_repository, paths(tmp_path, kit_repository))
    assert calls == ["full"]
```

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/test_projects.py tests/test_cli.py -k 'skills_repository or interactive_project' -q`

Expected: failures from unknown `init_project` keyword and absent parser fields.

- [ ] **Step 3: Implement manifest and TTY handling**

Add `--skills-repository-url` and `--skills-default-branch` to `project init`; reject a branch without URL. Extend `_interactive_project_setup()` with one optional URL prompt after Git selection and use the default `main` branch when a URL is entered. Pass the values to `init_project()`, which inserts `skills.repository` before schema validation. Preserve idempotent init behavior and never prompt in non-TTY mode.

Keep the existing `ProjectMemoryManager.index(project, mode="full")` call after manifest creation; do not add a second scan. The focused test must prove the full mode remains requested.

- [ ] **Step 4: Verify GREEN**

Run: `uv run --extra dev pytest tests/test_projects.py tests/test_cli.py -k 'skills_repository or interactive_project' -q`

Expected: all targeted tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_engineering_kit/projects.py src/agent_engineering_kit/cli.py tests/test_projects.py tests/test_cli.py
git commit -m "feat(projects): configure project skill repositories at init"
```

### Task 3: Expose authoring commands and effective runtime index

**Files:**
- Modify: `src/agent_engineering_kit/cli.py`
- Modify: `src/agent_engineering_kit/clients.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_clients.py`

**Interfaces:**
- Consumes: Task 1 service and `effective_skill_sources()`.
- Produces: `agent-kit skills add`; `agent-kit project skills checkout|add|index`; `effective-skills.md` adjacent to `skills-provenance.json`.

- [ ] **Step 1: Write failing CLI and runtime-index tests**

```python
def test_skill_add_invokes_bundled_authoring(isolated_data, monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "add_bundled_skill", lambda *_args, **_kwargs: Path("/kit/skills/first-party/review-api"))
    assert run(["skills", "add", "--from", "source"]) == 0
    assert "review-api" in capsys.readouterr().out

def test_project_skills_checkout_and_add_are_in_parser():
    assert _parser().parse_args(["project", "skills", "checkout", "--into", "../project-skills"]).project_skills_command == "checkout"
    assert _parser().parse_args(["project", "skills", "add", "--from", "source", "--checkout", "../project-skills"]).project_skills_command == "add"

def test_client_sync_writes_effective_skill_index(publication_fixture):
    sync_clients(publication_fixture.paths.repository, publication_fixture.paths, project=publication_fixture.project)
    index = publication_fixture.paths.installations / "clients/shared/effective-skills.md"
    assert "project-skills" in index.read_text(encoding="utf-8")

def test_resync_keeps_native_mcp_when_docker_is_unavailable(paths, monkeypatch):
    monkeypatch.setattr("agent_engineering_kit.docker_mcp.shutil.which", lambda _: None)
    assert resync(REPOSITORY, paths, update_kit=False).mcp
```

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/test_cli.py tests/test_clients.py -k 'skill_add or project_skills_checkout or effective_skill_index' -q`

Expected: parser tests fail because commands and generated Markdown do not exist.

- [ ] **Step 3: Implement command routing and runtime index**

Add parser entries and CLI dispatch that resolve and validate the current logical project before invoking the service. Print changed file paths and no Git lifecycle claims. In `sync_clients()`, render one deterministic Markdown row per `EffectiveSkillSource` with ID, `description`, effective source, state, revision and shadowed source names; write it atomically to `shared.parent / "effective-skills.md"`. Add the index path to generated adapter content.

Keep Docker MCP Toolkit optional during `resync`: if Docker or its MCP Toolkit is unavailable, preserve the native MCP route and return a successful resync with an explicit skipped/unavailable diagnostic instead of failing the entire operation. Other MCP installation failures remain errors.

- [ ] **Step 4: Verify GREEN**

Run: `uv run --extra dev pytest tests/test_cli.py tests/test_clients.py -k 'skill_add or project_skills_checkout or effective_skill_index' -q`

Expected: all targeted tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_engineering_kit/cli.py src/agent_engineering_kit/clients.py tests/test_cli.py tests/test_clients.py
git commit -m "feat(skills): expose project skill authoring commands"
```

### Task 4: Document and validate the completed workflow

**Files:**
- Modify: `docs/runbooks/corporate-extensions-and-mcp-credentials.md`
- Modify: `docs/wiki/Project-skills.md`
- Modify: `docs/wiki/CLI.md`
- Modify: `README.md`
- Modify: `docs/INDEX.md`
- Test: `tests/test_repository.py`
- Test: `tests/test_documentation.py`

**Interfaces:**
- Consumes: final CLI contracts and source precedence.
- Produces: canonical Russian usage guidance and indexed design/plan documentation.

- [ ] **Step 1: Write failing documentation contract tests where a stable command list is asserted**

```python
def test_project_skills_guide_lists_authoring_commands():
    guide = (REPOSITORY / "docs/wiki/Project-skills.md").read_text(encoding="utf-8")
    assert "project skills checkout" in guide
    assert "project skills add" in guide
```

- [ ] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/test_repository.py tests/test_documentation.py -k 'project_skills_guide' -q`

Expected: the new documentation test fails until the guide is updated.

- [ ] **Step 3: Update documentation and indexes**

Document the sibling checkout workflow, all new flags/commands, the distinction between tracked `skills/INDEX.md` and generated `effective-skills.md`, and the prohibition on authoring through managed storage. Add the plan to `docs/INDEX.md` with a relative link.

- [ ] **Step 4: Verify GREEN and full regression suite**

Run:

```bash
uv run --extra dev pytest
uv run --extra dev agent-kit validate --ci
git diff --check
```

Expected: all tests and CI validation succeed and the diff has no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add README.md docs tests
git commit -m "docs(skills): document skill authoring workflow"
```
