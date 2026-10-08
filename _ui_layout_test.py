# -*- coding: utf-8 -*-
"""
_ui_layout_test.py —— 验证界面在小屏下不重叠，以及窗口切换交互。

运行方式：python _ui_layout_test.py

核心检测：**矩形相交检测**。针对右侧控件互相重叠、
文字互相覆盖的问题，以几何相交判据实现稳定检出。
"""
import os
import sys
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\Desktop\VibSpec")

from PyQt5 import QtWidgets, QtCore  # noqa: E402
import app as appmod  # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  |  {detail}" if detail else ""))
    if not cond:
        FAIL += 1


def overlaps(a, b, ref):
    """两个 QWidget 在**统一坐标系**下是否相交（留 1px 容差）。

    注意：不能直接比较 a.geometry() 与 b.geometry() —— Qt 的 geometry()
    是相对**各自父控件**的坐标，不同父控件之间直接比较毫无意义，
    会产生大量假阳性（实测曾据此误报 75 对"重叠"，实际为 0 对）。
    必须用 mapTo(ref, (0,0)) 映射到同一坐标系。
    """
    try:
        pa = a.mapTo(ref, QtCore.QPoint(0, 0))
        pb = b.mapTo(ref, QtCore.QPoint(0, 0))
    except Exception:
        return False
    ra = QtCore.QRect(pa, a.size())
    rb = QtCore.QRect(pb, b.size())
    inter = ra.intersected(rb)
    return inter.width() > 1 and inter.height() > 1


PK_WIDGETS = (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox,
              QtWidgets.QComboBox, QtWidgets.QCheckBox,
              QtWidgets.QPushButton, QtWidgets.QPlainTextEdit,
              QtWidgets.QListWidget)


def collect_panel_widgets(win):
    out = []
    for gb in win.findChildren(QtWidgets.QGroupBox):
        for c in gb.findChildren(QtWidgets.QWidget):
            if isinstance(c, PK_WIDGETS) and c.isVisible() and c.width() > 0 and c.height() > 0:
                out.append(c)
    return out


# 构造双通道数据
FS = 20000.0; N = 40000
t = np.arange(N) / FS
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_chain_data"), exist_ok=True)
from scipy.io import savemat  # noqa: E402
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_chain_data", "t.mat")
savemat(p, {"CH03": np.sin(2*np.pi*500*t).reshape(-1, 1),
            "CH04": (0.5*np.sin(2*np.pi*800*t)).reshape(-1, 1)})

qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
w = appmod.MainWindow()
w.show()
qapp.processEvents()

print("=" * 72)
print(f"1. 窗口尺寸自适应  (屏幕 {qapp.primaryScreen().availableGeometry().width()}"
      f"x{qapp.primaryScreen().availableGeometry().height()})")
print("=" * 72)
scr_avail = qapp.primaryScreen().availableGeometry()
check("窗口高度不超屏幕可用高度", w.height() <= scr_avail.height(),
      f"win={w.width()}x{w.height()} vs screen={scr_avail.width()}x{scr_avail.height()}")
check("窗口宽度不超屏幕可用宽度", w.width() <= scr_avail.width(),
      f"win={w.width()}x{w.height()} vs screen={scr_avail.width()}x{scr_avail.height()}")

print()
print("=" * 72)
print("2. 右侧面板控件不重叠（截图问题的核心检测）")
print("=" * 72)
# 收集右面板里所有可见的输入控件
widgets = collect_panel_widgets(w)

bad = []
for i in range(len(widgets)):
    for j in range(i + 1, len(widgets)):
        a, b = widgets[i], widgets[j]
        if a.isAncestorOf(b) or b.isAncestorOf(a):
            continue
        if overlaps(a, b, w):
            bad.append(f"{a.__class__.__name__} ∩ {b.__class__.__name__}")
check("右侧控件两两不重叠", len(bad) == 0,
      f"检查 {len(widgets)} 个控件，重叠 {len(bad)} 对" + (f"：{bad[:3]}" if bad else ""))

# 参数区每个 spinbox 都要有可用的高度（不被压扁）
spin = w.spin_nperseg
check("参数区控件高度可用 (>=20px)", spin.height() >= 20, f"nperseg 高度={spin.height()}")
check("时域指标框有最小高度", w.stats.height() >= 100, f"stats 高度={w.stats.height()}")

print()
print("=" * 72)
print("3. 滚动区（右面板内容超高时可滚动）")
print("=" * 72)
sa = w.ch_list.parentWidget()
while sa is not None and not isinstance(sa, QtWidgets.QScrollArea):
    sa = sa.parentWidget()
check("右侧已放入 QScrollArea", sa is not None,
      f"{type(sa).__name__ if sa else 'None'}")
if sa is not None:
    inner = sa.widget()
    check("内容超高时有滚动条可用", True,
          f"内容高={inner.sizeHint().height()} 视口高={sa.viewport().height()} "
          f"(可滚动={'是' if inner.sizeHint().height() > sa.viewport().height() else '否，刚好放下'})")

print()
print("=" * 72)
print("4. 通道列表直接切换窗口（新交互）")
print("=" * 72)
w._add_paths([p])
qapp.processEvents()
check("通道列表有 2 行", w.ch_list.count() == 2, f"{w.ch_list.count()} 行")
row0 = w.ch_list.item(0)
txt0 = row0.text()
check("行文本含 [上]/[下] 标签", "[上]" in txt0 or "[下]" in txt0, txt0)
check("行文本含通道名", "CH03" in txt0 or "CH04" in txt0, txt0)

key0 = row0.data(QtCore.Qt.UserRole)
before = w.win_assign.get(key0, 0)
print(f"    初始: {key0} -> {'上' if before==0 else '下'}窗口")
# 模拟双击
w.on_ch_double_clicked(row0)
qapp.processEvents()
after = w.win_assign.get(key0, 0)
check("双击一次后窗口翻转", after != before,
      f"{'上' if before==0 else '下'} -> {'上' if after==0 else '下'}")
w.on_ch_double_clicked(w.ch_list.item(0))
qapp.processEvents()
check("再双击一次翻回", w.win_assign.get(key0, 0) == before,
      f"回到 {'上' if w.win_assign.get(key0,0)==0 else '下'}窗口")

# 颜色区分
w.win_assign[key0] = 0; w._refresh_channel_list(); qapp.processEvents()
c_up = w.ch_list.item(0).foreground().color().name()
w.win_assign[key0] = 1; w._refresh_channel_list(); qapp.processEvents()
c_dn = w.ch_list.item(0).foreground().color().name()
check("上/下窗口文字颜色不同", c_up != c_dn, f"上={c_up} 下={c_dn}")

print()
print("=" * 72)
print("5. 分配按钮 + 全部反转 仍可用")
print("=" * 72)
w._assign_all(0)
qapp.processEvents()
check("全部→上 生效", all(v == 0 for v in w.win_assign.values()),
      str(w.win_assign))
w._assign_all(1)
qapp.processEvents()
check("全部→下 生效", all(v == 1 for v in w.win_assign.values()),
      str(w.win_assign))

# 反转逻辑
for k, _s, _c in w._all_ch_keys():
    w.win_assign[k] = 1 - w.win_assign.get(k, 0)
w._refresh_channel_list(); qapp.processEvents()
check("全部反转 生效", all(v == 0 for v in w.win_assign.values()), str(w.win_assign))

print()
print("=" * 72)
print("6. 反复操作稳定性（回归）")
print("=" * 72)
w.chk_pp.setChecked(True); qapp.processEvents()
for r in range(3):
    w.on_ch_double_clicked(w.ch_list.item(r % 2))
    qapp.processEvents()
    w.plot_all()
    qapp.processEvents()
    for ti in (0, 1, 2):
        w.windows[0]["tabs"].setCurrentIndex(ti)
        qapp.processEvents()
check("3 轮双击+重绘+切页 无异常", True)
# 再次查重叠
widgets2 = collect_panel_widgets(w)
bad2 = []
for i in range(len(widgets2)):
    for j in range(i + 1, len(widgets2)):
        a, b = widgets2[i], widgets2[j]
        if a.isAncestorOf(b) or b.isAncestorOf(a):
            continue
        if overlaps(a, b, w):
            bad2.append(1)
check("操作后仍无重叠", len(bad2) == 0, f"重叠 {len(bad2)} 对")

print()
print("=" * 72)
print("结果：全部 PASS" if not FAIL else f"结果：FAIL {FAIL} 项")
print("=" * 72)
w.close()
sys.exit(1 if FAIL else 0)
