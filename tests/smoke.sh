#!/bin/sh
# 离线回归；不访问账号、不联网、不消耗模型额度。
set -eu
cd "$(dirname "$0")/.."
HUB_TEST_HOME=$(mktemp -d "$PWD/.smoke-XXXXXX")
trap 'rm -rf "$HUB_TEST_HOME"' EXIT HUP INT TERM
export HUB_HOME="$HUB_TEST_HOME"
unset HUB_PARENT HUB_RUN HUB_DEPTH HUB_META HUB_READONLY
export PYTHONDONTWRITEBYTECODE=1
export HUB_NO_AUTOTITLE=1  # 自动起名会真的叫模型，离线测试里关掉
python3 - <<'PY'
import ast
from pathlib import Path
ast.parse(Path('hub').read_text(), feature_version=(3, 9))
PY
python3 hub --help >/dev/null
python3 tests/test_hub.py
python3 tests/test_api.py
python3 tests/test_council.py
python3 tests/test_lan.py
python3 tests/test_pressure.py
python3 tests/test_effort.py
python3 tests/test_side.py
python3 tests/test_resume.py
python3 tests/test_images.py
python3 tests/test_names.py
python3 tests/test_handoff.py
python3 tests/test_toggles.py
python3 tests/test_denied.py
node tests/test_ui.js
node tests/test_ui_layout.js
node tests/test_ui_council.js
node tests/test_ui_groups.js
node tests/test_ui_effort.js
node tests/test_ui_side.js
echo "smoke ok"
