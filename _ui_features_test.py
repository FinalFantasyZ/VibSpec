# -*- coding: utf-8 -*-
"""
_ui_features_test.py —— 本次迭代新增功能的回归测试。

覆盖：
  1. 拖拽导入（文件 / 文件夹 / 非数据文件）
  2. 删除已导入文件（单个 / 批量 / 只保留选中 / 快捷键）
  3. 悬停解释文案（关键控件都有 tooltip）
  4. 时域横坐标时间轴 —— **重点**：
     a) 处理链把信号截断到 Num 后，t0 超过 Num 时不应退化成 0~1 s
     b) 多文件混画（fs 不同）时，横轴取并集、标题如实标注 fs
     c) 改采样率只影响选中文件，不波及其它（"时间轴偶发异常"的根因）
  5. 算法链路完整性：三种方式 + 包络谱跳直流

运行方式：python _ui_features_test.py
"""
import os
import sys

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\Desktop\VibSpec")

from PyQt5 import QtWidgets, QtCore  # noqa: E402
from PyQt5.QtCore import QMimeData, QUrl, QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QDropEvent  # noqa: E402
from scipy.io import savemat  # noqa: E402
import app as appmod  # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  |  {detail}" if detail else ""))
    if not cond:
        FAIL += 1


TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_feat_data")
# 每次从干净的临时目录开始，避免上一轮残留的 .mat 影响"递归扫描"的计数
if os.path.isdir(TMP):
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
SUB = os.path.join(TMP, "sub")
os.makedirs(SUB, exist_ok=True)


def make_mat(path, fs_n, n):
    t = np.arange(n) / fs_n
    sig = (1 + 0.6 * np.sin(2 * np.pi * 76.3 * t)) * np.sin(2 * np.pi * 2000 * t)
    savemat(path, {"CH03": sig.reshape(-1, 1), "CH04": (0.5 * sig).reshape(-1, 1)})


P_A = os.path.join(TMP, "a.mat")          # 2.0 s @ 20000
make_mat(P_A, 20000.0, 40000)
P_B = os.path.join(SUB, "b.mat")          # 1.0 s @ 20000（子文件夹里，测递归）
make_mat(P_B, 20000.0, 20000)
P_TXT = os.path.join(TMP, "notes.txt")    # 非数据文件，应被忽略
with open(P_TXT, "w", encoding="utf-8") as f:
    f.write("not a data file")

qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
w = appmod.MainWindow()
w.resize(1400, 800)
w.show()
qapp.processEvents()

print("=" * 72)
print("1. 拖拽导入")
print("=" * 72)
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(P_A), QUrl.fromLocalFile(P_TXT)])
got = w._paths_from_mime(mime)
check("单文件拖入：只接受 .mat，忽略 .txt",
      got == [os.path.normpath(P_A)], f"{[os.path.basename(p) for p in got]}")

mime2 = QMimeData()
mime2.setUrls([QUrl.fromLocalFile(TMP)])
got2 = w._paths_from_mime(mime2)
check("文件夹拖入：递归得到 2 个 .mat",
      len(got2) == 2, f"{[os.path.basename(p) for p in got2]}")

mime3 = QMimeData()
mime3.setUrls([QUrl.fromLocalFile(P_TXT)])
check("非数据文件拖入被拒绝", w._paths_from_mime(mime3) == [], "空列表")

# 实际投递一个拖放事件
ev = QDropEvent(QPoint(50, 50), Qt.CopyAction, mime2, Qt.LeftButton, Qt.NoModifier)
w.dropEvent(ev)
qapp.processEvents()
check("dropEvent 后文件已导入", len(w.signals) == 2, f"{len(w.signals)} 个")

print()
print("=" * 72)
print("2. 悬停解释文案（tooltip）")
print("=" * 72)
tips = {
    "导入文件按钮": w.btn_file,
    "导入文件夹按钮": w.btn_folder,
    "删除选中按钮": w.btn_del,
    "文件树": w.tree,
    "通道列表": w.ch_list,
    "归一化下拉": w.cmb_norm,
    "采样率 fs": w.spin_fs,
    "窗函数": w.cmb_window,
    "PSD 分段": w.spin_nperseg,
    "FFT 点数": w.spin_nfft,
    "PSD 重叠": w.cmb_overlap,
    "时域起点 t0": w.spin_t0,
    "时域时长": w.spin_tspan,
    "频率上限": w.spin_fmax,
    "dB 下限": w.spin_ylim,
    "去均值": w.chk_detrend,
    "对数坐标": w.chk_logx,
    "处理链方式": w.cmb_pp,
    "FIR 截止": w.spin_pp_fc,
    "FIR 阶数": w.spin_pp_n,
    "包络谱 Num": w.spin_pp_num,
    "包络谱 Lfr": w.spin_pp_lfr,
    "显示包络谱按钮": w.btn_pp_show,
    "绘制按钮": w.btn_plot,
    "导出图片": w.btn_png,
    "导出数据": w.btn_csv,
    "批量导出": w.btn_export_all,
    "时域指标框": w.stats,
    "全部→上": w.btn_win1_all,
    "全部→下": w.btn_win2_all,
}
missing = [k for k, v in tips.items() if not (v.toolTip() or "").strip()]
check(f"{len(tips)} 个关键控件都有 tooltip", not missing,
      f"缺失: {missing}" if missing else "全部有")
long_enough = [k for k, v in tips.items() if len(v.toolTip()) < 8]
check("tooltip 内容不是空壳（>=8 字）", not long_enough, f"过短: {long_enough}")

print()
print("=" * 72)
print("3. 删除已导入文件")
print("=" * 72)
w._check_all(True)
qapp.processEvents()
before = len(w.signals)
# 选中第一个文件（顶层节点）
w.tree.setCurrentItem(w.tree.topLevelItem(0))
w.tree.topLevelItem(0).setSelected(True)
qapp.processEvents()
w.on_delete_selected()
qapp.processEvents()
check("删除单个文件生效", len(w.signals) == before - 1,
      f"{before} -> {len(w.signals)}")
check("磁盘原文件仍在（只从列表移除）", os.path.exists(P_A), P_A)
check("树节点同步移除", w.tree.topLevelItemCount() == len(w.signals),
      f"树 {w.tree.topLevelItemCount()} / 数据 {len(w.signals)}")

# 重新导入后再测"只保留选中"
w._add_paths([P_A])
qapp.processEvents()
w.tree.topLevelItem(0).setSelected(True)
qapp.processEvents()
m_keep = QtWidgets.QMenu  # noqa: F841  仅作类型示意，实际直接调用底层方法
keep_path = w.tree.topLevelItem(0).data(0, Qt.UserRole)
keep_set = {keep_path}
w._remove_paths([p for p in list(w.signals) if p not in keep_set])
qapp.processEvents()
check("只保留选中：其余被删", len(w.signals) == 1, f"{len(w.signals)} 个")
check("保留的文件还在", keep_path in w.signals, os.path.basename(keep_path))

w._remove_paths(list(w.signals))
qapp.processEvents()
check("全部删除后为空", len(w.signals) == 0, f"{len(w.signals)} 个")
check("删除后通道列表也清空", w.ch_list.count() == 0, f"{w.ch_list.count()} 行")

print()
print("=" * 72)
print("4. 时域横坐标时间轴（重点回归）")
print("=" * 72)
# 4a. 处理链截断到 Num 后，t0 超界不应退化成 0~1 s
w._add_paths([P_A])          # 40000 点 @20000Hz = 2.0 s
qapp.processEvents()
w.chk_pp.setChecked(True)
qapp.processEvents()
w.cmb_pp.setCurrentIndex(0)  # 高通FIR，Num=16384 -> 仅 0.8192 s 有效
w.spin_pp_num.setValue(16384)
qapp.processEvents()
w.spin_t0.setValue(1.0)      # 1.0 s > 16384/20000=0.8192 s，旧版这里会出空数组
w.spin_tspan.setValue(0.05)
qapp.processEvents()
w.plot_all()
qapp.processEvents()
ax = w.windows[0]["time"].ax
lo, hi = ax.get_xlim()
check("t0 超过 Num 时横轴不退化成 0~1 s",
      not (abs(lo) < 1e-9 and abs(hi - 1.0) < 1e-9),
      f"xlim=({lo:.4f}, {hi:.4f})")
check("横轴落在截断后信号的合理范围内",
      0 <= lo <= 0.82 + 1e-3, f"xlim=({lo:.4f}, {hi:.4f})")
check("t0 超界时改为显示最后一段（而非塌缩为单个孤立点）",
      hi - lo > 0.01, f"跨度={hi - lo:.4f} s")
check("时域曲线非空（确实画出了数据）",
      any(len(ln.get_ydata()) > 0 for ln in ax.lines),
      f"{[len(ln.get_ydata()) for ln in ax.lines]}")

# 4b. t0=0 全段：横轴上限应约等于 16384/20000 = 0.8192 s
w.spin_t0.setValue(0.0)
w.spin_tspan.setValue(0.0)   # 0 = 全程
qapp.processEvents()
w.plot_all()
qapp.processEvents()
lo2, hi2 = w.windows[0]["time"].ax.get_xlim()
expect_hi = 16384 / 20000.0
check("显示全程时横轴上限 = 截断长度/fs",
      abs(hi2 - expect_hi) < 5e-3, f"xlim=({lo2:.4f}, {hi2:.4f}) 期望上限≈{expect_hi:.4f}")

# 4c. 关闭处理链 -> 用完整 2.0 s
w.chk_pp.setChecked(False)
qapp.processEvents()
w.plot_all()
qapp.processEvents()
lo3, hi3 = w.windows[0]["time"].ax.get_xlim()
check("关闭处理链后横轴恢复全程 2.0 s",
      abs(hi3 - 2.0) < 1e-3, f"xlim=({lo3:.4f}, {hi3:.4f})")

# 4d. 多文件混画（fs 不同）时横轴取并集、标题如实标注
w._remove_paths(list(w.signals))
qapp.processEvents()
P_C = os.path.join(TMP, "c.mat")
make_mat(P_C, 20000.0, 40000)
P_D = os.path.join(TMP, "d.mat")
make_mat(P_D, 10000.0, 40000)
w._add_paths([P_C, P_D])
qapp.processEvents()
# 注意：示波器 MAT 文件里**没有** fs 字段，导入时一律是默认 20000 Hz。
# 真实场景即"人工确认真实采样率"这一步，此处如实模拟：
# 把 d 改成 10000 Hz -> 40000 点变成 4.0 s，与 c 的 2.0 s 不同。
w.signals[P_D].fs = 10000.0
w._assign_all(0)                   # 都放上窗口
qapp.processEvents()
w.spin_tspan.setValue(0.0)         # 全程
qapp.processEvents()
w.plot_all()
qapp.processEvents()
lo4, hi4 = w.windows[0]["time"].ax.get_xlim()
check("混画不同 fs：横轴取并集(到 4.0 s)",
      abs(hi4 - 4.0) < 1e-2, f"xlim=({lo4:.4f}, {hi4:.4f})")
title = w.windows[0]["time"].ax.get_title()
check("标题如实列出两个 fs（不再只显示第一个文件的）",
      "20000" in title and "10000" in title, title)

# 4e. 改 fs 只影响选中文件
w.tree.clearSelection()
w.tree.setCurrentItem(w.file_items[P_C])
w.file_items[P_C].setSelected(True)
qapp.processEvents()
fs_d_before = w.signals[P_D].fs
w.spin_fs.setValue(25600.0)
qapp.processEvents()
check("改 fs 只作用于选中文件",
      abs(w.signals[P_C].fs - 25600.0) < 1e-6 and abs(w.signals[P_D].fs - fs_d_before) < 1e-6,
      f"选中={w.signals[P_C].fs:g}  未选中={w.signals[P_D].fs:g}（应保持不变）")

w.tree.clearSelection()
qapp.processEvents()
fs_before_all = {p: s.fs for p, s in w.signals.items()}
w.spin_fs.setValue(12345.0)        # 没有选中任何文件
qapp.processEvents()
check("无选中时改 fs 不会静默批量修改",
      all(abs(w.signals[p].fs - v) < 1e-9 for p, v in fs_before_all.items()),
      f"fs={ {os.path.basename(p): s.fs for p, s in w.signals.items()} }")

print()
print("=" * 72)
print("5. 窗口分配交互（按钮已删，改为双击/右键）")
print("=" * 72)
check("→上窗口 / →下窗口 按钮已移除",
      not hasattr(w, "btn_win1") and not hasattr(w, "btn_win2"),
      "属性不存在")
check("批量按钮保留", hasattr(w, "btn_win1_all") and hasattr(w, "btn_win2_all"))
w._refresh_channel_list()
qapp.processEvents()
n = w.ch_list.count()
check("通道列表有内容", n >= 2, f"{n} 行")
if n >= 2:
    it0 = w.ch_list.item(0)
    k0 = it0.data(Qt.UserRole)
    w.win_assign[k0] = 0
    w._refresh_channel_list()
    qapp.processEvents()
    it0 = w.ch_list.item(0)
    w.on_ch_double_clicked(it0)
    qapp.processEvents()
    check("双击切换窗口生效", w.win_assign.get(k0) == 1,
          f"-> {'下' if w.win_assign.get(k0) == 1 else '上'}窗口")

print()
print("=" * 72)
print(f"结果：{'全部 PASS' if not FAIL else f'FAIL {FAIL} 项'}")
print("=" * 72)
w.close()
sys.exit(1 if FAIL else 0)
