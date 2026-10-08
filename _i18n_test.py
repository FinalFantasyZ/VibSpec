# -*- coding: utf-8 -*-
"""
_i18n_test.py —— 中英文界面切换、菜单栏、工具栏与 matplotlib 对话框的回归测试。

覆盖：
  1. 默认中文、窗口标题
  2. 顶部菜单栏（关于 / 语言）
  3. 切到英文 → 切回中文；**关键取值不被译文破坏**（窗函数键、归一化模式）
  4. matplotlib 对话框本地化，且标题栏「?」按钮已移除
  5. 工具栏不含失效的「主页 / 后退 / 前进」
  6. 文件信息面板的类型名不暴露内部标识

运行方式：python _i18n_test.py
退出码 0 = 全部通过。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                    # noqa: E402
from PyQt5 import QtWidgets                            # noqa: E402
from PyQt5.QtCore import Qt, QCoreApplication          # noqa: E402
from scipy.io import savemat                           # noqa: E402

import app as A                                        # noqa: E402
import i18n                                            # noqa: E402

OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  |  {detail}")


def main():
    qapp = QtWidgets.QApplication(sys.argv)
    QCoreApplication.setOrganizationName("VibSpec")
    QCoreApplication.setApplicationName("VibSpec")
    w = A.MainWindow()

    print("== 1. 默认语言与标题 ==")
    check("默认中文", w.lang == "zh", w.lang)
    check("标题为中文且不含人名字样",
          "振动信号分析器" in w.windowTitle() and "yang" not in w.windowTitle(),
          w.windowTitle())
    check("按钮为中文", w.btn_file.text() == "导入文件", w.btn_file.text())

    print("== 2. 顶部菜单栏 ==")
    mb = w.menuBar()
    menus = [a.text() for a in mb.actions()]
    check("有「关于」与「语言」两个菜单", len(menus) == 2, str(menus))
    about_items = [a.text() for a in mb.actions()[0].menu().actions()]
    check("关于菜单仅一项", about_items == ["关于 VibSpec"], str(about_items))
    check("已无「打开项目主页」菜单项", not any("主页" in x for x in about_items),
          str(about_items))

    print("== 3. 工具栏 ==")
    tb = w.toolbar
    labels = [a.text() for a in tb.actions() if not a.isSeparator()]
    check("已移除失效的 主页/后退/前进",
          not any(x in labels for x in ("主页", "后退", "前进")), str(labels))
    check("保留 平移/缩放/子图/自定义/保存",
          all(any(k in x for x in labels)
              for k in ("平移", "缩放", "子图", "自定义", "保存")), str(labels))

    print("== 4. 切到英文 ==")
    w.set_language("en")
    check("语言状态", w.lang == "en", w.lang)
    check("标题切英文", "Vibration Signal Analyzer" in w.windowTitle(), w.windowTitle())
    check("按钮切英文", w.btn_file.text() == "Import Files", w.btn_file.text())
    ppt = [w.cmb_pp.itemText(i) for i in range(w.cmb_pp.count())]
    check("处理链下拉英文", ppt[0] == "High-pass filter", str(ppt))
    wt = [w.cmb_window.itemText(i) for i in range(w.cmb_window.count())]
    check("窗函数下拉英文", wt[1] == "Hann", str(wt))
    check("菜单全英文",
          all(ord(c) < 128 for m in [a.text() for a in mb.actions()] for c in m),
          str([a.text() for a in mb.actions()]))

    print("== 5. 英文下关键取值仍正确 ==")
    check("_window_key()", w._window_key() == "hann", w._window_key())
    check("_norm_mode()", w._norm_mode() == "none", w._norm_mode())
    w.cmb_window.setCurrentIndex(4)
    check("切到平顶后 key 正确", w._window_key() == "flattop", w._window_key())
    w.cmb_window.setCurrentIndex(1)
    w.cmb_norm.setCurrentIndex(2)
    check("切到峰值归一后 key 正确", w._norm_mode() == "peak", w._norm_mode())
    w.cmb_norm.setCurrentIndex(0)

    print("== 6. 切回中文 ==")
    w.set_language("zh")
    check("标题回中文", "振动信号分析器" in w.windowTitle(), w.windowTitle())
    check("按钮回中文", w.btn_file.text() == "导入文件", w.btn_file.text())
    ppt = [w.cmb_pp.itemText(i) for i in range(w.cmb_pp.count())]
    check("下拉回中文", ppt[0] == "高通滤波", str(ppt))
    check("取值仍正确", w._window_key() == "hann", w._window_key())

    print("== 7. 导入文件 + 信息面板类型名 ==")
    tmpd = tempfile.mkdtemp(prefix="vibspec_i18n_")
    n, fs = 20000, 25600.0
    t = np.arange(n) / fs
    sig = (1 + 0.7 * np.sin(2 * np.pi * 24.7 * t)) * np.sin(2 * np.pi * 2200 * t)
    p = os.path.join(tmpd, "t_meta.mat")
    savemat(p, {"CH01": sig.reshape(-1, 1).astype("float32"),
                "capture_fs": np.array([[fs]]),
                "capture_effective_fs": np.array([[fs]])})
    w._add_paths([p])
    w._check_all(True)
    w.plot_all()
    qapp.processEvents()
    check("文件已导入", len(w.signals) == 1, f"{len(w.signals)} 个")
    w.tree.topLevelItem(0).setSelected(True)
    qapp.processEvents()
    info = w.info.toPlainText()
    check("类型名不暴露内部标识",
          "blackbox_mat" not in info and "scope_mat" not in info,
          info.splitlines()[1] if info else "")

    print("== 8. matplotlib 对话框 ==")
    tb.edit_parameters()
    for _ in range(3):
        qapp.processEvents()
    dlg = getattr(tb, "_fedit_dialog", None)
    check("图形参数对话框已创建", dlg is not None, str(dlg))
    if dlg is not None:
        check("对话框保持可见（回归：此前会闪退）", dlg.isVisible(),
              f"isVisible={dlg.isVisible()}")
        check("标题已中文化", dlg.windowTitle() == "图形参数", dlg.windowTitle())
        check("已移除「?」按钮",
              not bool(dlg.windowFlags() & Qt.WindowContextHelpButtonHint), "")

    from matplotlib.backends.backend_qt import SubplotToolQt
    dlg2 = SubplotToolQt(w.windows[0]["time"].fig, w)
    groups = [g.title() for g in dlg2.findChildren(QtWidgets.QGroupBox)]
    btns = [b.text() for b in dlg2.findChildren(QtWidgets.QPushButton)]
    check("子图调整已中文化", "边距" in groups and "间距" in groups, str(groups))
    check("按钮已中文化", "导出数值" in btns and "关闭" in btns, str(btns))
    check("子图调整已移除「?」",
          not bool(dlg2.windowFlags() & Qt.WindowContextHelpButtonHint), "")

    print()
    print("=" * 64)
    print(f"结果：PASS {OK} 项，FAIL {FAIL} 项")
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
