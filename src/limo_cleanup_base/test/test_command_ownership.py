import ast
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parents[3]
SOURCE_ROOT = WORKSPACE_ROOT / 'src'
SCRIPTS_ROOT = WORKSPACE_ROOT / 'scripts'


def _production_python_files():
    for path in SOURCE_ROOT.rglob('*.py'):
        if 'test' not in path.parts:
            yield path


def test_only_tracked_gateway_creates_a_twist_publisher():
    owners = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'create_publisher'
                    and node.args):
                continue
            message_type = node.args[0]
            if isinstance(message_type, ast.Name) and message_type.id == 'Twist':
                owners.append(path.relative_to(WORKSPACE_ROOT).as_posix())

    assert owners == [
        'src/limo_cleanup_base/limo_cleanup_base/'
        'tracked_base_controller.py',
    ]


def test_only_stage2_wrapper_launches_vendor_limo_base():
    owners = []
    for path in _production_python_files():
        source = path.read_text(encoding='utf-8')
        if "package='limo_base'" in source:
            owners.append(path.relative_to(WORKSPACE_ROOT).as_posix())

    assert owners == [
        'src/limo_cleanup_bringup/launch/'
        'tracked_base_vendor_stage2.launch.py',
    ]


def test_project_scripts_never_publish_or_launch_vendor_motion_directly():
    forbidden = (
        'ros2 topic pub /cmd_vel',
        'ros2 launch limo_base',
        'ros2 run limo_base',
    )
    violations = []
    for path in sorted(SCRIPTS_ROOT.iterdir()):
        if not path.is_file() or path.suffix not in ('.py', '.sh'):
            continue
        source = path.read_text(encoding='utf-8')
        for token in forbidden:
            if token in source:
                violations.append((path.name, token))

    assert violations == []
