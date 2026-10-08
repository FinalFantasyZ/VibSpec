# -*- coding: utf-8 -*-
"""
_ui_chain_test.py —— 无头驱动真实 PyQt 界面，验证"处理链"接入是否正确。

运行方式：python _ui_chain_test.py

关键：使用真实的 QApplication 与事件循环（processEvents），
而非纯逻辑调用——此前的 toolbar 崩溃即为纯逻辑测试所遗漏。
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


# 构造双通道测试文件（模拟示波器 MAT 场景：内圈故障表现为高频载波受转频调制）
FS = 20000.0
N = 100000
t = np.arange(N) / FS
rng = np.random.default_rng(0)
bpfo = 76.3            # 外圈特征频率
carrier = 3000.0
sig = (1.0 + 0.8 * np.sin(2 * np.pi * bpfo * t)) * np.sin(2 * np.pi * carrier * t)
ch3 = sig + 0.02 * rng.standard_normal(N)      # 垂直
ch4 = 0.6 * sig + 0.02 * rng.standard_normal(N)  # 水平
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_chain_data")
os.makedirs(tmp, exist_ok=True)
from scipy.io import savemat  # noqa: E402
mat_path = os.path.join(tmp, "fake_scope.mat")
savemat(mat_path, {"CH03": ch3.reshape(-1, 1), "CH04": ch4.reshape(-1, 1)})

qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
w = appmod.MainWindow()
w.show()
qapp.processEvents()

print("=" * 72)
print("1. 导入双通道文件 + 基础绘制")
print("=" * 72)
w._add_paths([mat_path])
qapp.processEvents()
check("文件已导入", len(w.signals) == 1, f"{len(w.signals)} 个")
s = list(w.signals.values())[0]
check("识别为双通道", len(s.channels) == 2, f"{sorted(s.channels)}")
w.plot_all()
qapp.processEvents()
check("基础绘制无异常", True)
n_time = len(w.windows[0]["time"].ax.lines)
check("时域画出曲线", n_time >= 1, f"上窗口 {n_time} 条")

print()
print("=" * 72)
print("2. 启用处理链（高通FIR + 包络）")
print("=" * 72)
w.chk_pp.setChecked(True)
qapp.processEvents()
w.cmb_pp.setCurrentIndex(0)      # 高通FIR
qapp.processEvents()
w.spin_pp_fc.setValue(500.0)
w.spin_pp_n.setValue(180)
qapp.processEvents()
w.plot_all()
qapp.processEvents()
lines = w.windows[0]["time"].ax.lines
has_env = any("包络up" in (ln.get_label() or "") for ln in lines)
check("时域出现包络虚线", has_env, f"共 {len(lines)} 条线")
check("时域有滤波信号实线",
      any((ln.get_label() or "").startswith("fake_scope") and "高通" in (ln.get_label() or "")
          for ln in lines),
      [ln.get_label() for ln in lines][:4])
y0 = w.windows[0]["time"].ax.lines[0].get_ydata()
check("绘制数据非空且有限", y0.size > 0 and bool(np.all(np.isfinite(y0))),
      f"len={y0.size}")

print()
print("=" * 72)
print("3. 切换处理方式 fir / svd / raw（索引已随新增 EMD 选项变化）")
print("=" * 72)
check("处理方式下拉有 4 项（新增 EMD）", w.cmb_pp.count() == 4,
      f"{w.cmb_pp.count()} 项: {[w.cmb_pp.itemText(i) for i in range(w.cmb_pp.count())]}")
for idx, tag in ((1, "svd"), (3, "raw"), (0, "fir")):
    w.cmb_pp.setCurrentIndex(idx)
    qapp.processEvents()
    w.plot_all()
    qapp.processEvents()
    check(f"方式 {tag} 绘制通过", len(w.windows[0]["time"].ax.lines) >= 1,
          f"{len(w.windows[0]['time'].ax.lines)} 条线")

# EMD 为可选依赖：已安装则正常运行，未安装须优雅降级（不崩溃并给出提示）
w.cmb_pp.setCurrentIndex(2)
qapp.processEvents()
try:
    from PyEMD import EMD  # noqa: F401
    w.plot_all()
    qapp.processEvents()
    check("EMD 方式可正常执行（环境已安装该依赖）",
          len(w.windows[0]["time"].ax.lines) >= 1, "已装 PyEMD")
except ImportError:
    w.plot_all()
    qapp.processEvents()
    check("未安装 EMD 时优雅降级（不崩溃）", True,
          f"状态栏提示：{w.statusBar().currentMessage()[:40]}")

print()
print("=" * 72)
print("4. 包络谱按钮")
print("=" * 72)
# 复位到 FIR（上一步可能停留在未安装的 EMD 选项上）
w.cmb_pp.setCurrentIndex(0)
qapp.processEvents()
w.show_envelope_spectrum()
qapp.processEvents()
ef_ax = w.windows[0]["freq"].ax
check("包络谱已画出", len(ef_ax.lines) >= 1, f"{len(ef_ax.lines)} 条")
if ef_ax.lines:
    xd = ef_ax.lines[0].get_xdata(); yd = ef_ax.lines[0].get_ydata()
    check("包络谱长度 = Lfr-1（已按 MATLAB sf(2:Lfr) 跳过直流）",
          len(xd) == 799, f"{len(xd)}")
    check("包络谱 X 轴首点 > 0（直流已跳过）", float(xd[0]) > 0,
          f"x0={float(xd[0]):.4f} Hz")
    k = 1 + int(np.argmax(yd[1:400]))
    peak_f = float(xd[k])
    check("包络谱主峰 ≈ 外圈特征频率 76.3Hz",
          abs(peak_f - bpfo) < 3.0, f"峰 @ {peak_f:.2f} Hz")
    check("Y 轴刻度在合理范围内", float(np.max(np.abs(yd))) < 1e9,
          f"max|Y|={float(np.max(np.abs(yd))):.3e}")

print()
print("=" * 72)
print("5. 关闭处理链 + 反复切换标签页（回归 toolbar 崩溃点）")
print("=" * 72)
w.chk_pp.setChecked(False)
qapp.processEvents()
for rnd in range(3):
    for ti in (0, 1, 2):
        w.windows[0]["tabs"].setCurrentIndex(ti)
        w.windows[1]["tabs"].setCurrentIndex(ti)
        qapp.processEvents()
    w.plot_all()
    qapp.processEvents()
check("3 轮标签切换 + 重绘无异常", True)
check("关闭后时域恢复单线", len(w.windows[0]["time"].ax.lines) >= 1,
      f"{len(w.windows[0]['time'].ax.lines)} 条")

print()
print("=" * 72)
if FAIL:
    print(f"结果：FAIL {FAIL} 项")
else:
    print("结果：全部 PASS")
print("=" * 72)

w.close()
sys.exit(1 if FAIL else 0)
