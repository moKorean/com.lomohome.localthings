"""Static checks on the driver and device modules.

These two files cannot be imported here: they `from homey import driver`, and the SDK
only exists inside the app container. So nothing catches a method that is called but
never defined — it surfaces at runtime, in the one code path that happens to call it.
That is exactly how `'Driver' object has no attribute '_language'` reached a working
repair view: an edit added three call sites and the definition landed in a replacement
that silently did not match.

Parsing the AST costs nothing and closes that gap. Only private names are checked,
which needs no allow-list: `self._foo(...)` must be defined in the same class, while
anything public may legitimately come from the SDK base class.
"""

import ast
from pathlib import Path

import pytest

VIEWS = (
    "settings/index.html",
    "drivers/appliance/pair/configure.html",
    "drivers/appliance/repair/reconnect.html",
)
# The driver and device implementations live in lib/appliance/ so a per-type driver
# can subclass them; drivers/appliance/*.py are thin shims that export a subclass.
# Both are parsed: the shims for their (small) own code, the bases for all of it.
MODULES = (
    "lib/appliance/driver.py",
    "lib/appliance/device.py",
    "drivers/appliance/driver.py",
    "drivers/appliance/device.py",
    "app.py",
    "api.py",
)
APP_ROOT = Path(__file__).parent.parent


def _classes(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield node


def _defined(cls: ast.ClassDef) -> set:
    names = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        # A private callable can also be a class-level attribute holding a function.
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _private_self_calls(cls: ast.ClassDef) -> dict:
    """{name: line} for every `self._name(...)` inside the class."""
    calls = {}
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and func.attr.startswith("_")
            and not func.attr.startswith("__")
        ):
            calls.setdefault(func.attr, func.lineno)
    return calls


@pytest.mark.parametrize("filename", MODULES)
def test_every_private_method_called_on_self_is_defined(filename):
    tree = ast.parse((APP_ROOT / filename).read_text())
    classes = list(_classes(tree))
    if not classes:
        pytest.skip(f"{filename} defines no classes")

    for cls in classes:
        defined = _defined(cls)
        # Inherited private helpers would be a design smell here, but allow anything
        # defined on a base class in the same file.
        for base in cls.bases:
            if isinstance(base, ast.Name):
                for other in classes:
                    if other.name == base.id:
                        defined |= _defined(other)

        for name, line in _private_self_calls(cls).items():
            assert name in defined, (
                f"{filename}:{line} calls self.{name}() but {cls.name} does not "
                f"define it"
            )


def test_the_check_actually_finds_calls():
    """A walk that silently matches nothing would pass the test above forever."""
    tree = ast.parse((APP_ROOT / "lib/appliance/driver.py").read_text())
    total = sum(len(_private_self_calls(cls)) for cls in _classes(tree))
    assert total > 5, f"only found {total} private self-calls; the walk looks broken"


@pytest.mark.parametrize("filename", MODULES)
def test_no_module_imports_something_it_does_not_use(filename):
    """A stale import is harmless; a *missing* one is not, and both come from the same
    kind of half-applied edit. This catches the harmless direction, and ruff's F821
    catches the other."""
    source = (APP_ROOT / filename).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split(".")[0])

    used = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }
    unused = {name for name in imported if name not in used and name != "annotations"}
    assert not unused, f"{filename}: unused imports {sorted(unused)}"


# --- webview scripts -------------------------------------------------------
#
# The same failure mode reaches the views, and did: a helper for rendering a result
# next to its button was added while the call site kept writing to a message area
# three cards further down the page. Nothing was broken enough to notice — the button
# worked, its result just appeared somewhere the user was not looking.


def _view_script(filename: str) -> str:
    import re

    source = (APP_ROOT / filename).read_text()
    blocks = re.findall(r"<script type=\"text/javascript\">(.*?)</script>", source, re.DOTALL)
    assert blocks, f"{filename}: no script block found"
    return "\n".join(blocks)


@pytest.mark.parametrize("filename", VIEWS)
def test_every_view_function_is_called(filename):
    """A declared-but-uncalled function means an edit landed half-applied."""
    import re

    script = _view_script(filename)
    declared = re.findall(r"^\s*function\s+(\w+)\s*\(", script, re.MULTILINE)
    assert declared, f"{filename}: no functions found; the extraction looks broken"

    # Called by Homey rather than by this file.
    external = {"onHomeyReady"}
    for name in declared:
        if name in external:
            continue
        # A call is any occurrence that is not the declaration itself.
        uses = len(re.findall(rf"\b{re.escape(name)}\b", script))
        assert uses > 1, f"{filename}: function {name}() is declared but never used"
