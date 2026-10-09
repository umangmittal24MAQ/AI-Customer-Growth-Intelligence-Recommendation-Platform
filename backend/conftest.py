"""
Ensures the project root is on sys.path so `import app...` works no matter
which directory pytest is invoked from. pytest.ini's `pythonpath = .` is the
primary fix; this is a belt-and-suspenders fallback for any pytest/tool
version that doesn't honor that ini option.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
