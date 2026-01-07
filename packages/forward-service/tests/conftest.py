"""
pytest 配置文件
"""
import sys
from pathlib import Path

# 将包目录添加到 Python 路径
pkg_root = Path(__file__).parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))
