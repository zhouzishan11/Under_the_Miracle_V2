"""《神迹之下》启动入口。

直接运行： python main.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from under_the_miracle.gui import run  # noqa: E402

if __name__ == "__main__":
    run()