# -*- coding: utf-8 -*-
"""
build_exe.py —— 把 VibSpec 打包成可独立运行的 exe（PyInstaller）。

需使用**已安装全部依赖的解释器**运行本脚本，并**强烈建议使用独立的构建环境**。

注意：**不要使用装有 torch / tensorflow / dask 等重型包的"全家桶"环境打包。**
PyInstaller 收集 scipy 子模块时会触发 scipy._lib.array_api_compat 的自动探测，
把已安装的数组/深度学习库整条依赖链拉进分析图——实测打包耗时数十分钟、
产物从约 100 MB 膨胀到 GB 级。本脚本已对常见重包加了防御性排除，
仍建议按下面的方式建立干净的构建环境。

    set PY=<构建环境路径>\\Scripts\\python.exe
    "%PY%" -m pip install PyQt5 numpy scipy matplotlib pyinstaller EMD-signal
    "%PY%" build_exe.py

产物：
    dist\\VibSpec.exe          单文件；首次启动需解包，约 5~15 s
    或 dist\\VibSpec\\VibSpec.exe目录版（--onedir）；启动更快，分发时需携带整个目录

用法：
    python build_exe.py            # 默认单文件
    python build_exe.py --onedir   # 目录版（启动更快）

说明：
- 构建环境中的依赖会一并打包进 exe，**目标机器无需安装 Python**。
- 如果构建环境里装了 EMD-signal，则界面里的「EMD 第1个IMF」链路在 exe 中同样可用。
- 崩溃日志写在 exe 同目录的 VibSpec_error.log（windowed 模式下无控制台输出）。
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "app.py")

# 写入 exe 属性（右键 → 属性 → 详细信息）的软件信息
APP_TITLE = "VibSpec 振动信号分析器"
APP_VERSION = (1, 1, 2, 0)
APP_AUTHOR = "yang"
APP_HOMEPAGE = ""     # 如有项目主页 / GitHub 地址，填入此处即可一并写入 exe 属性


def write_version_file(path):
    """生成 PyInstaller 版本信息文件，用于填充 exe 的「属性 → 详细信息」。

    这些字段只影响 Windows 文件属性显示与可执行文件的署名，不影响程序功能。
    """
    ver = tuple(APP_VERSION)
    ver_str = ".".join(str(x) for x in ver)
    fields = [
        ("CompanyName", APP_AUTHOR),
        ("FileDescription", APP_TITLE),
        ("FileVersion", ver_str),
        ("InternalName", "VibSpec"),
        ("LegalCopyright", f"Copyright (C) 2026 {APP_AUTHOR}"),
        ("OriginalFilename", "VibSpec.exe"),
        ("ProductName", APP_TITLE),
        ("ProductVersion", ver_str),
    ]
    if APP_HOMEPAGE:
        fields.append(("Homepage", APP_HOMEPAGE))

    def esc(v):
        return str(v).replace("\\", "\\\\").replace("'", "\\'")

    lines = [
        "VSVersionInfo(",
        "  ffi=FixedFileInfo(",
        f"    filevers={ver}, prodvers={ver},",
        "    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,",
        "    subtype=0x0, date=(0, 0)",
        "  ),",
        "  kids=[",
        "    StringFileInfo([",
        "      StringTable('080404B0', [",
    ]
    lines += [f"        StringStruct('{k}', '{esc(v)}')," for k, v in fields]
    lines += [
        "      ])",
        "    ]),",
        "    VarFileInfo([VarStruct('Translation', [2052, 1200])])",
        "  ]",
        ")",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def check_deps():
    """检查当前解释器是否具备打包所需的全部依赖，缺失项会明确列出。"""
    missing = []
    for mod, pipname in (("PyQt5", "PyQt5"), ("numpy", "numpy"),
                         ("scipy", "scipy"), ("matplotlib", "matplotlib"),
                         ("PyInstaller", "pyinstaller")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pipname)
    if missing:
        print("[错误] 当前 Python 缺少以下包：", ", ".join(missing))
        print("       请先安装后再执行打包：")
        print(f'       "{sys.executable}" -m pip install ' + " ".join(missing))
        sys.exit(1)
    try:
        import PyEMD  # noqa: F401
        print("[信息] 检测到 PyEMD：EMD 处理链将一并打包。")
    except ImportError:
        print("[信息] 未检测到 PyEMD：exe 中选择 EMD 方式时将提示安装依赖（其他功能不受影响）。")


def has_emd():
    try:
        import PyEMD  # noqa: F401
        return True
    except ImportError:
        return False


def build(onedir=False):
    check_deps()
    mode = ["--onedir"] if onedir else ["--onefile"]

    ver_file = os.path.join(tempfile.gettempdir(), "vibspec_version_info.txt")
    write_version_file(ver_file)
    print(f"[信息] 版本信息：{APP_TITLE} "
          f"{'.'.join(str(x) for x in APP_VERSION)} / {APP_AUTHOR}")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        *mode,
        "--windowed",                       # GUI 程序，不弹出控制台窗口
        "--name", "VibSpec",
        "--version-file", ver_file,         # 写入 exe 属性（署名 / 版本 / 版权）
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
        # 显式声明项目自带的本地模块，避免 PyInstaller 静态分析遗漏
        "--hidden-import", "loader",
        "--hidden-import", "analysis",
        "--hidden-import", "i18n",
        "--hidden-import", "qt_localize",
        # matplotlib：字体、样式等数据文件必须显式收集，否则中文标题会显示为方块
        "--collect-data", "matplotlib",
        "--hidden-import", "PyQt5.sip",
        # scipy 部分子模块为运行时动态导入，PyInstaller 静态分析无法识别
        "--collect-submodules", "scipy._lib",
        "--collect-submodules", "scipy.special",
        "--collect-submodules", "scipy.interpolate",
        # 排除不需要的重型模块，以减小分发包体积
        "--exclude-module", "tkinter",
        "--exclude-module", "PyQt5.QtWebEngineWidgets",
        "--exclude-module", "PyQt5.QtQuick",
        "--exclude-module", "PyQt5.QtQml",
        "--exclude-module", "PyQt5.Qt3DCore",
        "--exclude-module", "PyQt5.QtMultimedia",
        "--exclude-module", "IPython",
        "--exclude-module", "pytest",
        "--exclude-module", "PySide2",
        "--exclude-module", "PySide6",
        # 下面这批是防御性排除：本工具只依赖 numpy/scipy/matplotlib/PyQt5，
        # 但若构建环境同时装有 torch / tensorflow / dask 等包，
        # scipy._lib.array_api_compat 的自动探测会把它们整条依赖链拉进分析图，
        # 导致打包耗时数十分钟、产物膨胀到 GB 级（已实测）。
        # 在此显式排除，使其在任何构建环境中都不会被牵连打包。
        "--exclude-module", "torch",
        "--exclude-module", "torchvision",
        "--exclude-module", "tensorflow",
        "--exclude-module", "keras",
        "--exclude-module", "jax",
        "--exclude-module", "cupy",
        "--exclude-module", "dask",
        "--exclude-module", "distributed",
        "--exclude-module", "bokeh",
        "--exclude-module", "numba",
        "--exclude-module", "llvmlite",
        "--exclude-module", "jupyter",
        "--exclude-module", "jupyterlab",
        "--exclude-module", "notebook",
        "--exclude-module", "nbformat",
        "--exclude-module", "boto3",
        "--exclude-module", "botocore",
        "--exclude-module", "s3fs",
        "--exclude-module", "gcsfs",
        "--exclude-module", "openpyxl",
        "--exclude-module", "docutils",
    ]
    if has_emd():
        args += ["--collect-submodules", "PyEMD"]
    args.append(ENTRY)

    print("=" * 72)
    print("执行 PyInstaller：")
    print(" ".join(args))
    print("=" * 72)
    subprocess.check_call(args, cwd=HERE)

    out = (os.path.join(HERE, "dist", "VibSpec", "VibSpec.exe") if onedir
           else os.path.join(HERE, "dist", "VibSpec.exe"))
    print()
    print("=" * 72)
    if os.path.exists(out):
        mb = os.path.getsize(out) / 1024 / 1024
        print(f"打包完成：{out}  ({mb:.1f} MB)")
        if onedir:
            print("注意：这是目录版，分发时需携带整个 dist\\VibSpec 目录。")
        else:
            print("单文件版：分发该 exe 即可（首次启动需解包，耗时略长）。")
    else:
        print("未生成预期产物，请检查上述 PyInstaller 输出。")
        sys.exit(1)
    print("=" * 72)


def main():
    onedir = "--onedir" in sys.argv
    if "--clean-artifacts" in sys.argv:
        for d in ("build", "dist"):
            p = os.path.join(HERE, d)
            if os.path.isdir(p):
                print("清理", p)
                shutil.rmtree(p, ignore_errors=True)
        return
    build(onedir=onedir)


if __name__ == "__main__":
    main()
