"""Локальный режим моделей без изменения переносимых определений."""

from pathlib import Path
import re
import yaml

from .errors import AgentKitError
from .io import atomic_write, load_yaml
from .paths import KitPaths


def model_enforcement(paths: KitPaths, project_id: str | None = None) -> bool:
    enabled = True
    roots = [paths.overrides / 'global']
    if project_id:
        roots.append(paths.overrides / 'projects' / project_id)
    for root in roots:
        path = root / 'model-enforcement.yaml'
        if path.is_file():
            value = load_yaml(path)
            if set(value) != {'version', 'enabled'} or value['version'] != 1 or not isinstance(value['enabled'], bool):
                raise AgentKitError(f'Некорректный режим моделей: {path}')
            enabled = value['enabled']
    return enabled


def set_model_enforcement(root: Path, enabled: bool) -> None:
    atomic_write(root / 'model-enforcement.yaml', '# Локальная проверка model-привязок; каталог providers не меняется.\n' + yaml.safe_dump({'version': 1, 'enabled': enabled}))


def portable_content(content: str) -> str:
    """Снять только структурированную привязку к моделям в копии Markdown."""
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', content, re.S)
    if not match:
        return content
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        return content
    metadata.pop('model', None)
    return '---\n' + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + '---\n' + content[match.end():]
