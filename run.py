# -*- coding: utf-8 -*-
"""
run.py —— 备用启动器（双击即可，不依赖 .bat 编码）

背景说明：
  批处理文件（.bat）若以 UTF-8 无 BOM + LF 换行保存，cmd.exe 解析将失败，
  并报告 "'cho' 不是内部或外部命令" 一类的错误。该类编码问题较为隐蔽，
  故额外提供此纯 Python 启动器作为替代入口：
  双击本文件即可由 .py 关联的 Python 解释器直接运行。

用法：
    双击本文件，或在命令行执行:
        python run.py
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def ensure_deps():
    missing = []
    for mod, pkg in (("numpy", "numpy"), ("scipy", "scipy"),
                     ("matplotlib", "matplotlib"), ("PyQt5", "PyQt5")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        msg = ("缺少依赖: " + ", ".join(missing) +
               "\n\n请执行:\n    " + sys.executable +
               " -m pip install " + " ".join(missing))
        print(msg)
        try:
            import tkinter.messagebox as mb
            mb.showerror("VibSpec 启动失败", msg)
        except Exception:
            input("按回车退出...")
        return False
    return True


def main():
    os.chdir(HERE)
    if not ensure_deps():
        return 1

    # 中文字体配置（避免图表中文显示为方块）
    import matplotlib
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    try:
        import app
        app.main()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        try:
            import tkinter.messagebox as mb
            mb.showerror("VibSpec 运行出错", tb[-1500:])
        except Exception:
            input("按回车退出...")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
