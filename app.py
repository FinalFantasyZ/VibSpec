# -*- coding: utf-8 -*-
"""
app.py —— VibSpec 振动信号分析器（PyQt5 主界面）

功能
----
- 导入单个文件 / 整个文件夹（递归）
- 左侧文件列表，勾选要绘制的文件
- 右侧通道勾选 + 采样率 + 窗函数 + 参数设置
- 中间三个标签页：时域 / 频域(幅值谱) / dB功率谱(Welch PSD)
- 导出当前图（PNG）、导出当前数据（CSV）

界面风格参照 MATLAB：浅灰背景、细网格、多色曲线、中文标注。
"""

from __future__ import annotations

import os
import sys
import traceback
import warnings
from typing import Dict, List, Optional

import numpy as np

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 中文字体配置（避免中文显示为方块）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import loader
import analysis
import i18n
import qt_localize


# MATLAB 配色（经典 line color order 前 7 色）
MATLAB_COLORS = [
    "#0072BD", "#D95319", "#EDB120", "#7E2F8E",
    "#77AC30", "#4DBEEE", "#A2142F",
]


# ----------------------------------------------------------------------------
# 绘图画布
# ----------------------------------------------------------------------------

class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 5), dpi=100, facecolor="#f5f5f5")
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()

    def _style_axes(self, ax=None):
        ax = ax or self.ax
        ax.set_facecolor("white")
        ax.grid(True, which="major", color="#d0d0d0", linewidth=0.6)
        ax.grid(True, which="minor", color="#ececec", linewidth=0.4)
        ax.minorticks_on()
        ax.tick_params(labelsize=9)
        for s in ax.spines.values():
            s.set_color("#666666")
            s.set_linewidth(0.8)

    def clear(self):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self._style_axes()

    def redraw(self):
        # 小窗口下 tight_layout 可能无法满足边距要求而告警；
        # 用受控的 subplots_adjust 兜底，避免重复告警，同时避免布局被挤压。
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                self.fig.tight_layout()
        except Exception:
            self.fig.subplots_adjust(left=0.12, right=0.97, top=0.93, bottom=0.16)
        self.draw_idle()


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()

        # 界面语言：读取用户上次的选择，默认中文
        self._settings = QtCore.QSettings("VibSpec", "VibSpec")
        saved = self._settings.value("language", i18n.DEFAULT_LANG)
        self.lang = saved if saved in (i18n.LANG_ZH, i18n.LANG_EN) else i18n.DEFAULT_LANG

        self.setWindowTitle(i18n.app_title(self.lang))

        # 状态
        self.signals: Dict[str, loader.SignalSet] = {}   # path -> SignalSet
        self.file_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self.win_assign: Dict[str, int] = {}   # "文件名 :: 通道" -> 0=上窗口 1=下窗口

        # matplotlib 的对话框与工具栏需在创建之前接入本地化
        qt_localize.install(self.lang)

        self._build_ui()
        self._connect()
        self._build_menubar()
        # 上次若选择的是英文，启动时把界面整体切过去
        if self.lang != i18n.LANG_ZH:
            self.apply_language(self.lang, persist=False)
        self._fit_to_screen()
        # 支持将文件或文件夹直接拖入窗口导入
        self.setAcceptDrops(True)

    # ---------------- 拖拽导入 ----------------

    DATA_EXT = (".csv", ".mat")

    def _paths_from_mime(self, mime) -> List[str]:
        """从拖拽的 MIME 数据里取出可导入的文件路径。

        - 拖入**文件夹**会自动递归展开（复用 loader.list_data_files）。
        - 只接受 .csv / .mat（大小写不敏感），其余忽略。
        """
        if not mime.hasUrls():
            return []
        files: List[str] = []
        for url in mime.urls():
            p = url.toLocalFile()
            if not p:
                continue
            p = os.path.normpath(p)
            if os.path.isdir(p):
                files.extend(loader.list_data_files(p))
            elif p.lower().endswith(self.DATA_EXT):
                files.append(p)
        seen, out = set(), []
        for p in files:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def dragEnterEvent(self, e):
        if self._paths_from_mime(e.mimeData()):
            e.acceptProposedAction()
            self._set_drop_hint(True)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._paths_from_mime(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._set_drop_hint(False)

    def dropEvent(self, e):
        paths = self._paths_from_mime(e.mimeData())
        self._set_drop_hint(False)
        if not paths:
            e.ignore()
            return
        e.acceptProposedAction()
        self._add_paths(paths)

    def _set_drop_hint(self, on: bool):
        """拖拽过程中在中央区域显示虚线边框，作为拖放目标的视觉反馈。"""
        cw = self.centralWidget()
        if cw is None:
            return
        if on:
            cw.setStyleSheet(
                "#dropZone{border:3px dashed #0072BD;border-radius:6px;}")
            self.statusBar().showMessage("松开鼠标即可导入这些文件 / 文件夹…")
        else:
            cw.setStyleSheet("")
            self.statusBar().showMessage("就绪")

    def _fit_to_screen(self):
        """按屏幕可用区域自适应开窗，避免在低分辨率屏幕下出现控件重叠。

        此前采用固定尺寸 resize(1500, 900)，在 1512x700 一类屏幕上，
        右侧参数面板会被压缩至最小高度以下，导致控件重叠、文字互相覆盖。
        """
        scr = QtWidgets.QApplication.primaryScreen()
        if scr is None:
            self.resize(1360, 820)
            return
        avail = scr.availableGeometry()
        # 目标尺寸：不超过屏幕可用区域；小屏时同步缩小，不保留固定下限
        w = min(1500, max(820, int(avail.width() * 0.96)))
        h = min(900, max(560, int(avail.height() * 0.94)))
        w = min(w, avail.width())
        h = min(h, avail.height())
        self.resize(w, h)
        # 最小尺寸同样随屏幕调整，避免超出可用区域
        self.setMinimumSize(min(820, avail.width()), min(560, avail.height()))
        self.move(avail.x() + max(0, (avail.width() - w) // 2),
                  avail.y() + max(0, (avail.height() - h) // 2))

    # ---------------- UI 搭建 ----------------

    def _build_ui(self):
        central = QtWidgets.QWidget()
        central.setObjectName("dropZone")      # 拖拽时高亮这个框
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- 左：文件列表 ----
        left = QtWidgets.QWidget()
        left.setFixedWidth(320)
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        bar = QtWidgets.QHBoxLayout()
        self.btn_file = QtWidgets.QPushButton("导入文件")
        self.btn_file.setToolTip(
            "打开文件对话框，可一次选择多个 .csv / .mat 数据文件。\n"
            "也可以直接把文件或整个文件夹**拖进窗口**任意位置导入。")
        self.btn_folder = QtWidgets.QPushButton("导入文件夹")
        self.btn_folder.setToolTip(
            "选择一个文件夹，递归扫描其中所有 .csv / .mat 文件并全部导入。")
        bar.addWidget(self.btn_file)
        bar.addWidget(self.btn_folder)
        lv.addLayout(bar)

        bar2 = QtWidgets.QHBoxLayout()
        self.btn_all = QtWidgets.QPushButton("全选")
        self.btn_all.setToolTip("勾选列表中的所有文件与通道（用于同时绘图）。")
        self.btn_none = QtWidgets.QPushButton("全不选")
        self.btn_none.setToolTip("取消勾选所有文件与通道，但保留在列表中。")
        self.btn_del = QtWidgets.QPushButton("删除选中")
        self.btn_del.setToolTip(
            "从列表中移除选中的文件（快捷键 Delete）。\n"
            "只从软件里移出，**不会删除磁盘上的原始数据文件**。")
        self.btn_clear = QtWidgets.QPushButton("清空")
        self.btn_clear.setToolTip("移除列表中的全部文件，并清空所有绘图区。")
        for b in (self.btn_all, self.btn_none, self.btn_del, self.btn_clear):
            bar2.addWidget(b)
        lv.addLayout(bar2)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["文件 / 通道", "信息"])
        self.tree.setColumnWidth(0, 190)
        self.tree.setAlternatingRowColors(True)
        self.tree.setToolTip(
            "勾选文件/通道决定画什么。\n"
            "单选一行后按 Delete 可删除该文件；右键可批量删除。\n"
            "鼠标悬停在文件名上会显示工况信息与提示。")
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        lv.addWidget(self.tree, 1)

        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(150)
        self.info.setPlaceholderText("选中文件后在此显示工况与提示")
        self.info.setToolTip("显示当前选中文件的类型、采样率、点数、时长、通道与工况。")
        lv.addWidget(self.info)

        root.addWidget(left)

        # ---- 中：双窗口，每个窗口内各带三个标签页 ----
        mid = QtWidgets.QWidget()
        mv = QtWidgets.QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)

        self.splitter = QtWidgets.QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)

        # 每个窗口 = 一个 TabWidget(时域/频域/PSD) + 每画布各自的工具条
        self.windows = []
        for wi in range(2):
            holder = QtWidgets.QWidget()
            hv = QtWidgets.QVBoxLayout(holder)
            hv.setContentsMargins(0, 0, 0, 0)
            hv.setSpacing(2)

            tabs = QtWidgets.QTabWidget()
            c_time = PlotCanvas()
            c_freq = PlotCanvas()
            c_psd = PlotCanvas()
            tabs.addTab(c_time, "时域波形")
            tabs.addTab(c_freq, "频域（幅值谱）")
            tabs.addTab(c_psd, "dB 功率谱（PSD）")

            # 关键：每个画布配一个**常驻**工具条，切换标签页时只 show/hide，
            # 不可使用 setParent(None)/deleteLater，否则会使 matplotlib 的
            # NavigationToolbar2 内部 actions 变成悬空指针，下次 fig.clear()
            # 触发 QAction 访问已析构对象，抛出
            # "wrapped C/C++ object of type QAction has been deleted"。
            toolbars = []
            for c in (c_time, c_freq, c_psd):
                tb = NavigationToolbar(c, self)
                hv.addWidget(tb)
                tb.hide()
                toolbars.append(tb)
            toolbars[0].show()

            hv.addWidget(tabs, 1)

            self.splitter.addWidget(holder)
            self.windows.append({
                "holder": holder, "tabs": tabs, "toolbars": toolbars,
                "time": c_time, "freq": c_freq, "psd": c_psd,
            })

        # 兼容旧属性名（导出等逻辑仍按当前窗口取）
        self.tabs = self.windows[0]["tabs"]
        self.canvas_time = self.windows[0]["time"]
        self.canvas_freq = self.windows[0]["freq"]
        self.canvas_psd = self.windows[0]["psd"]
        self.toolbar = self.windows[0]["toolbars"][0]

        mv.addWidget(self.splitter, 1)

        root.addWidget(mid, 1)

        # ---- 右：参数面板（放进滚动区，防止小屏把控件压重叠）----
        right = QtWidgets.QScrollArea()
        right.setWidgetResizable(True)
        right.setFixedWidth(320)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right.setFrameShape(QtWidgets.QFrame.NoFrame)

        right_inner = QtWidgets.QWidget()
        # 关键：给内容设一个**小于视口**的最小宽度，否则 QGroupBox 里最长标题
        # （"信号预处理链（MATLAB 算法）"）会使 minimumWidth 超过 viewport，
        # 在 widgetResizable 且无横向滚动条时导致右侧内容被裁剪。
        right_inner.setMinimumWidth(260)
        right.setWidget(right_inner)
        rv = QtWidgets.QVBoxLayout(right_inner)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.setSpacing(6)

        # 通道 + 窗口分配
        gb_ch = QtWidgets.QGroupBox("通道与窗口分配")
        gc = QtWidgets.QVBoxLayout(gb_ch)

        hint = QtWidgets.QLabel("双击通道行即可在上/下窗口间切换（右键可批量）")
        hint.setStyleSheet("color:#666;font-size:11px;")
        hint.setWordWrap(True)
        gc.addWidget(hint)

        self.ch_list = QtWidgets.QListWidget()
        self.ch_list.setMinimumHeight(88)
        self.ch_list.setMaximumHeight(140)
        self.ch_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.ch_list.setToolTip(
            "双击一行 → 在上/下窗口之间切换；\n"
            "右键 → 批量分配，或一键反转全部上/下；\n"
            "行首 [上]/[下] 表示当前所在窗口，蓝色=上窗口、橙色=下窗口。")
        gc.addWidget(self.ch_list)

        row_win2 = QtWidgets.QHBoxLayout()
        self.btn_win1_all = QtWidgets.QPushButton("全部→上")
        self.btn_win1_all.setToolTip("把所有通道一次性分配到上窗口。")
        self.btn_win2_all = QtWidgets.QPushButton("全部→下")
        self.btn_win2_all.setToolTip("把所有通道一次性分配到下窗口。")
        row_win2.addWidget(self.btn_win1_all)
        row_win2.addWidget(self.btn_win2_all)
        gc.addLayout(row_win2)

        self.chk_all_ch = QtWidgets.QCheckBox("显示全部通道")
        self.chk_all_ch.setChecked(True)
        self.chk_all_ch.setToolTip(
            "勾选：把所有导入通道都显示在右侧列表中；\n"
            "取消：只列出当前在文件树里勾选了的通道。")
        gc.addWidget(self.chk_all_ch)
        gb_ch.setToolTip(
            "决定每个通道画到哪个窗口。\n"
            "双击列表行即可切换；右键可批量分配或一键反转。\n"
            "[上]=蓝色 画到上窗口，[下]=橙色 画到下窗口。")
        rv.addWidget(gb_ch)

        # 归一化
        gb_n = QtWidgets.QGroupBox("归一化")
        gb_n.setToolTip(
            "不同采集链路的增益可能相差几十~上千倍，不归一化时小信号会被压成直线。\n"
            "归一化**只影响绘图显示**，导出的图片与 CSV 始终是原始物理量。")
        gn = QtWidgets.QVBoxLayout(gb_n)
        self.cmb_norm = QtWidgets.QComboBox()
        self.cmb_norm.addItems([
            "不归一化（原始物理量）",
            "除以各自 RMS（按有效值归一）",
            "除以各自峰值（按峰值归一）",
            "Z-score（去均值后除标准差）",
        ])
        self.cmb_norm.setCurrentIndex(0)
        self.cmb_norm.setToolTip(
            "不同采集链路增益差几十~上千倍时，打开归一化才能在同一窗口看清各自形状。\n"
            "归一化只影响绘图显示，不改变导出的物理量数据。")
        gn.addWidget(self.cmb_norm)
        rv.addWidget(gb_n)

        # 信号预处理链（包络分析的前置处理）—— 可折叠，以减少纵向占用
        gb_pp = QtWidgets.QGroupBox("信号预处理链")
        gb_pp.setMinimumWidth(250)
        gb_pp.setCheckable(True)
        gb_pp.setChecked(False)          # 默认折叠：未启用时不占用纵向空间
        outer_pp = QtWidgets.QVBoxLayout(gb_pp)
        outer_pp.setContentsMargins(8, 4, 8, 4)

        pp_body = QtWidgets.QWidget()
        gpp = QtWidgets.QVBoxLayout(pp_body)
        gpp.setContentsMargins(0, 0, 0, 0)
        gpp.setSpacing(4)

        self.chk_pp = QtWidgets.QCheckBox("启用处理链")
        self.chk_pp.setToolTip(
            "启用包络分析链路：信号先按所选方式预处理，再取包络做谱分析。\n"
            "时域图会同时画出处理后的信号（实线）与它的包络（虚线）。")
        gpp.addWidget(self.chk_pp)

        row_pp = QtWidgets.QHBoxLayout()
        lab_pp = QtWidgets.QLabel("方式")
        lab_pp.setToolTip("选择包络分析的前置处理方式，见下拉框各项说明。")
        row_pp.addWidget(lab_pp)
        self.cmb_pp = QtWidgets.QComboBox()
        self.cmb_pp.addItems([
            "高通滤波",
            "SVD 重构",
            "EMD 首个 IMF",
            "直接取包络（不滤波）",
        ])
        self.cmb_pp.setToolTip(
            "包络分析的前置处理方式，作用是抑制低频干扰、突出高频冲击成分：\n"
            "• 高通滤波 —— 滤掉截止频率以下的低频分量，保留高频冲击（最常用）；\n"
            "• SVD 重构 —— 用奇异值分解重构信号的主要成分，抑制宽带噪声；\n"
            "• EMD 首个 IMF —— 经验模态分解取最高频的本征模态，分离冲击与趋势；\n"
            "   该方式需额外安装 EMD-signal（pip install EMD-signal）；\n"
            "• 直接取包络 —— 不做前置处理，作为对照基准。\n"
            "选择建议：一般先用高通滤波；若噪声明显，再与 SVD 的结果比较。")
        row_pp.addWidget(self.cmb_pp, 1)
        gpp.addLayout(row_pp)

        row_f = QtWidgets.QHBoxLayout()
        lab_f = QtWidgets.QLabel("FIR 截止")
        lab_f.setToolTip("高通滤波器把该频率以下的成分滤掉。")
        row_f.addWidget(lab_f)
        self.spin_pp_fc = QtWidgets.QDoubleSpinBox()
        self.spin_pp_fc.setRange(1, 1_000_000)
        self.spin_pp_fc.setDecimals(1)
        self.spin_pp_fc.setValue(500.0)
        self.spin_pp_fc.setSuffix(" Hz")
        self.spin_pp_fc.setToolTip(
            "高通滤波的截止频率（默认 500 Hz），截止点为 -6 dB：\n"
            "低于该频率的分量被衰减，高于该频率的分量基本原样通过。\n"
            "取值应高于转频与常见低频干扰、低于待分析的冲击频段；\n"
            "必须小于采样率的一半（Nyquist）。")
        row_f.addWidget(self.spin_pp_fc, 1)
        gpp.addLayout(row_f)

        row_n = QtWidgets.QHBoxLayout()
        lab_n = QtWidgets.QLabel("FIR 阶数")
        lab_n.setToolTip("滤波器阶数越大，过渡带越窄但边界效应也越长。")
        row_n.addWidget(lab_n)
        self.spin_pp_n = QtWidgets.QSpinBox()
        self.spin_pp_n.setRange(4, 4000)
        self.spin_pp_n.setValue(180)
        self.spin_pp_n.setToolTip(
            "滤波器阶数（默认 180）。阶数越高，过渡带越窄、阻带衰减越好，\n"
            "但边界效应也越长；零相位滤波要求信号长度 > 3×阶数，否则报错。")
        row_n.addWidget(self.spin_pp_n, 1)
        gpp.addLayout(row_n)

        self.chk_pp_also = QtWidgets.QCheckBox("傅里叶谱也用处理后的信号")
        self.chk_pp_also.setChecked(True)
        self.chk_pp_also.setToolTip(
            "勾选：幅值谱/PSD 基于处理后信号；\n"
            "不勾选：只把处理结果画在时域，频域仍用原始信号。")
        gpp.addWidget(self.chk_pp_also)

        lab_env = QtWidgets.QLabel("包络谱")
        lab_env.setToolTip(
            "对信号包络做 FFT，得到包络谱。\n"
            "轴承的冲击会调制出高频载波，其包络谱在故障特征频率处出现峰值，\n"
            "因此包络谱是定位轴承故障特征频率的常用手段。\n"
            "横轴为 0 ~ fs 的完整谱，纵轴为幅值。")
        gpp.addWidget(lab_env)
        row_lfr = QtWidgets.QHBoxLayout()
        self.spin_pp_num = QtWidgets.QSpinBox()
        self.spin_pp_num.setRange(0, 1 << 22)
        self.spin_pp_num.setValue(16384)
        self.spin_pp_num.setToolTip(
            "参与分析的样本数（默认 16384），取信号前 Num 个点做包络谱，\n"
            "0 表示使用全部样本。段越长频率分辨率越高，计算量也越大。")
        lab_num = QtWidgets.QLabel("Num")
        lab_num.setToolTip(self.spin_pp_num.toolTip())
        row_lfr.addWidget(lab_num)
        row_lfr.addWidget(self.spin_pp_num, 1)
        self.spin_pp_lfr = QtWidgets.QSpinBox()
        self.spin_pp_lfr.setRange(0, 1 << 22)
        self.spin_pp_lfr.setValue(800)
        self.spin_pp_lfr.setToolTip(
            "包络谱显示的上限频点 Lfr（默认 800）。\n"
            "频率上限 = (Lfr-1)×fs/Num；以 fs=20000、Num=16384 计，800 点约到 975 Hz。\n"
            "轴承故障特征频率通常集中在低频段，800 左右即可覆盖；0 表示显示全频段。")
        lab_lfr = QtWidgets.QLabel("Lfr")
        lab_lfr.setToolTip(self.spin_pp_lfr.toolTip())
        row_lfr.addWidget(lab_lfr)
        row_lfr.addWidget(self.spin_pp_lfr, 1)
        gpp.addLayout(row_lfr)

        self.btn_pp_show = QtWidgets.QPushButton("显示包络谱")
        self.btn_pp_show.setToolTip("把当前勾选信号的包络谱画到上窗口的频域页")
        gpp.addWidget(self.btn_pp_show)

        outer_pp.addWidget(pp_body)
        pp_body.setVisible(False)        # 折叠状态：仅保留标题栏
        gb_pp.toggled.connect(pp_body.setVisible)
        self._pp_body = pp_body

        rv.addWidget(gb_pp)

        # 采样与显示 —— 可折叠，默认展开（采样率等常用项需直接可见）
        gb_p = QtWidgets.QGroupBox("参数")
        gb_p.setCheckable(True)
        gb_p.setChecked(True)
        outer_p = QtWidgets.QVBoxLayout(gb_p)
        outer_p.setContentsMargins(8, 4, 8, 4)
        p_body = QtWidgets.QWidget()
        gp = QtWidgets.QFormLayout(p_body)
        gp.setContentsMargins(0, 0, 0, 0)
        gp.setSpacing(4)

        self.spin_fs = QtWidgets.QDoubleSpinBox()
        self.spin_fs.setRange(1, 10_000_000)
        self.spin_fs.setDecimals(3)
        self.spin_fs.setValue(20000)
        self.spin_fs.setSuffix(" Hz")
        self.spin_fs.setToolTip(
            "采样率 fs（Hz）。时间轴换算关系为：时间 = 点数 / fs。\n"
            "• 软件 CSV / 黑盒 MAT：自动读取文件记录的真实值；黑盒文件在采样率\n"
            "   自洽（偏差 ≤1%）时锁定，偏差较大时自动解锁，便于手动标定；\n"
            "• 示波器 MAT：文件里不含该字段，默认 20000 只是占位，需人工确认。\n"
            "注意：修改前需先在左侧列表选中目标文件（Ctrl/Shift 可多选），\n"
            "   只会改选中的文件，不会影响其它文件。")
        gp.addRow("采样率 fs", self.spin_fs)

        self.cmb_window = QtWidgets.QComboBox()
        self.cmb_window.addItems(list(analysis.WINDOWS.keys()))
        self.cmb_window.setCurrentText("汉宁 (hann)")
        self.cmb_window.setToolTip(
            "FFT / Welch 使用的窗函数。\n"
            "• 汉宁(hann)：通用首选，旁瓣低，适合看连续谱；\n"
            "• 矩形(boxcar)：等于不加窗，主瓣最窄但泄漏大；\n"
            "• 平顶(flattop)：幅值读数最准（测幅值优先），但主瓣最宽；\n"
            "• 汉明/布莱克曼：旁瓣更低，代价是主瓣更宽。")
        gp.addRow("窗函数", self.cmb_window)

        self.spin_nperseg = QtWidgets.QSpinBox()
        self.spin_nperseg.setRange(0, 1 << 20)
        self.spin_nperseg.setValue(4096)
        self.spin_nperseg.setToolTip(
            "Welch 功率谱的分段长度（每个子段的点数），0 表示自动。\n"
            "分段越短 → 频率分辨率越低、平均次数越多、谱线越平滑；\n"
            "分段越长 → 分辨率越高，但方差增大（谱线起伏更明显）。")
        gp.addRow("PSD 分段 nperseg", self.spin_nperseg)

        self.spin_nfft = QtWidgets.QSpinBox()
        self.spin_nfft.setRange(0, 1 << 21)
        self.spin_nfft.setValue(0)
        self.spin_nfft.setToolTip(
            "FFT 点数。0 表示自动取「数据长度」（幅值谱）或「分段长度」（PSD）。\n"
            "补零点（nfft > 数据长度）能让谱峰更平滑、峰值位置看得更细，\n"
            "但不会真正提高频率分辨率。")
        gp.addRow("FFT 点数 nfft", self.spin_nfft)

        self.cmb_overlap = QtWidgets.QComboBox()
        self.cmb_overlap.addItems(["0", "25", "50", "75"])
        self.cmb_overlap.setCurrentText("50")
        self.cmb_overlap.setToolTip(
            "Welch 相邻分段的交叠比例。50% 是常用折中：\n"
            "交叠越大，参与平均的段数越多、谱越平滑，但计算量越大。")
        gp.addRow("PSD 重叠 %", self.cmb_overlap)

        self.spin_t0 = QtWidgets.QDoubleSpinBox()
        self.spin_t0.setRange(0, 1e9)
        self.spin_t0.setDecimals(4)
        self.spin_t0.setValue(0.0)
        self.spin_t0.setSuffix(" s")
        self.spin_t0.setToolTip(
            "时域波形从第几秒开始画（对应样本索引 = t0 × fs）。\n"
            "用于跳过开头的过渡段或冲击段。0 表示从起点开始。")
        gp.addRow("时域起点 t0", self.spin_t0)

        self.spin_tspan = QtWidgets.QDoubleSpinBox()
        self.spin_tspan.setRange(0, 1e9)
        self.spin_tspan.setDecimals(4)
        self.spin_tspan.setValue(0.05)
        self.spin_tspan.setSuffix(" s")
        self.spin_tspan.setToolTip(
            "时域波形显示多长时间。默认 0.05 s，避免整段波形重叠难以分辨。\n"
            "填 0 表示显示全程。")
        gp.addRow("时域时长", self.spin_tspan)

        self.spin_fmax = QtWidgets.QDoubleSpinBox()
        self.spin_fmax.setRange(0, 10_000_000)
        self.spin_fmax.setDecimals(1)
        self.spin_fmax.setValue(0)
        self.spin_fmax.setSuffix(" Hz")
        self.spin_fmax.setToolTip(
            "频域两张图的横轴上限。0 表示自动（取 fs/2，即 Nyquist）。\n"
            "如需放大低频段（观察轴承故障特征频率），填入较小值。")
        gp.addRow("频率上限", self.spin_fmax)

        self.spin_ylim = QtWidgets.QDoubleSpinBox()
        self.spin_ylim.setRange(-300, 0)
        self.spin_ylim.setDecimals(1)
        self.spin_ylim.setValue(-120)
        self.spin_ylim.setSuffix(" dB")
        self.spin_ylim.setToolTip(
            "dB 功率谱纵轴的下限（dB/Hz）。\n"
            "调高（如 -80）可截去噪声基线，仅保留强峰；调低（如 -160）可观察弱成分。")
        gp.addRow("dB 下限", self.spin_ylim)

        self.chk_detrend = QtWidgets.QCheckBox("去均值")
        self.chk_detrend.setChecked(True)
        self.chk_detrend.setToolTip(
            "做谱分析前先减去直流分量。\n"
            "黑盒数据带 ~0.7 V 直流偏置，不去除会在 0 Hz 处产生极大的直流峰，\n"
            "将有用的交流成分压制，因此默认勾选。")
        gp.addRow(self.chk_detrend)

        self.chk_logx = QtWidgets.QCheckBox("频率轴对数坐标")
        self.chk_logx.setToolTip(
            "频域横轴改用对数刻度，便于同时看清低频细节和高频成分。")
        gp.addRow(self.chk_logx)

        outer_p.addWidget(p_body)
        gb_p.toggled.connect(p_body.setVisible)

        rv.addWidget(gb_p)

        # 操作
        gb_a = QtWidgets.QGroupBox("操作")
        ga = QtWidgets.QVBoxLayout(gb_a)
        self.btn_plot = QtWidgets.QPushButton("绘制 / 刷新")
        self.btn_plot.setStyleSheet(
            "QPushButton{background:#0072BD;color:white;font-weight:bold;padding:6px;}"
            "QPushButton:hover{background:#005a96;}")
        self.btn_plot.setToolTip(
            "按当前所有参数重新计算并绘制上/下两个窗口。\n"
            "（改动归一化、处理链、通道归属时通常会自动重绘，\n"
            " 修改窗函数 / nperseg / 重叠等参数后需手动触发。）")
        ga.addWidget(self.btn_plot)
        row = QtWidgets.QHBoxLayout()
        self.btn_png = QtWidgets.QPushButton("导出图片")
        self.btn_png.setToolTip(
            "把**当前活动窗口的当前标签页**导出为 PNG / PDF / SVG（200 dpi）。")
        self.btn_csv = QtWidgets.QPushButton("导出数据")
        self.btn_csv.setToolTip(
            "把当前图的谱线数据导出为 CSV，内容为**原始物理量**，不受归一化影响。")
        row.addWidget(self.btn_png)
        row.addWidget(self.btn_csv)
        ga.addLayout(row)
        self.btn_export_all = QtWidgets.QPushButton("批量导出全部图片")
        self.btn_export_all.setToolTip(
            "对每个通道各导出一张三联图（时域 + 幅值谱 + PSD），方便归档。")
        ga.addWidget(self.btn_export_all)
        rv.addWidget(gb_a)

        # 统计
        gb_s = QtWidgets.QGroupBox("时域指标")
        gs = QtWidgets.QVBoxLayout(gb_s)
        self.stats = QtWidgets.QPlainTextEdit()
        self.stats.setReadOnly(True)
        self.stats.setPlaceholderText("绘制后显示")
        self.stats.setMinimumHeight(140)
        self.stats.setToolTip(
            "前几条曲线的时域统计量（按窗口分别列出）。\n"
            "峰值/峰峰值按**原始信号（含直流）**计算；\n"
            "RMS、方差、峭度、峰值因子等在**去均值后**计算 —— 否则直流分量\n"
            "会使 RMS 显著偏高、峭度严重失真。\n"
            "统计量始终基于完整信号，与归一化开关无关。")
        gs.addWidget(self.stats)
        rv.addWidget(gb_s)

        # 底部留白：内容不足一屏时不被拉伸撑开
        rv.addStretch(1)

        root.addWidget(right)

        self.statusBar().showMessage("就绪：请导入数据文件或文件夹")

    # ---------------- 事件绑定 ----------------

    # ---------------- 菜单栏 / 语言 / 关于 ----------------

    # 归一化下拉项的中文原文（顺序与 _norm_mode() 的键一一对应）
    NORM_TEXTS = ["不归一化（原始物理量）", "除以各自 RMS（按有效值归一）",
                  "除以各自峰值（按峰值归一）", "Z-score（去均值后除标准差）"]

    def _t(self, zh_text: str) -> str:
        """把运行时拼接的界面文案翻到当前语言。"""
        return i18n.translate(zh_text, self.lang)

    def _norm_text(self) -> str:
        idx = max(0, min(self.cmb_norm.currentIndex(), len(self.NORM_TEXTS) - 1))
        return self._t(self.NORM_TEXTS[idx])

    def _build_menubar(self):
        """顶部菜单栏：关于 + 语言切换。"""
        mb = self.menuBar()

        self.menu_about = mb.addMenu(self._t("关于"))
        self.act_about = self.menu_about.addAction(self._t("关于 VibSpec"))
        self.act_about.triggered.connect(self.show_about)
        self.act_home = self.menu_about.addAction(self._t("打开项目主页"))
        self.act_home.triggered.connect(self.open_homepage)

        self.menu_lang = mb.addMenu(self._t("语言 / Language"))
        self.lang_actions = {}
        for code in (i18n.LANG_ZH, i18n.LANG_EN):
            act = self.menu_lang.addAction(i18n.LANG_NAMES[code])
            act.setCheckable(True)
            act.setChecked(code == self.lang)
            act.triggered.connect(lambda _checked=False, k=code: self.set_language(k))
            self.lang_actions[code] = act

    def set_language(self, code: str):
        if code in (i18n.LANG_ZH, i18n.LANG_EN):
            self.apply_language(code, persist=True)

    def apply_language(self, code: str, persist: bool = True):
        """切换界面语言。

        分三类处理：
          1. 静态文本 / tooltip / 下拉项 —— 由 i18n.retranslate_widgets 遍历刷新；
          2. 菜单项（QMenu / QAction 不在控件树遍历范围内）—— 单独刷新；
          3. 依赖语言的动态内容（信息面板、通道列表、图表标题）—— 重新生成或重绘。
        """
        self.lang = code
        if persist:
            self._settings.setValue("language", code)

        # matplotlib 侧的对话框与工具栏提示（立即刷新已存在的工具栏）
        qt_localize.set_language(code)
        qt_localize.apply_toolbar_language(self, code)

        self.setWindowTitle(i18n.app_title(code))
        i18n.retranslate_widgets(self, code)

        # 菜单栏单独刷新
        self.menu_about.setTitle(self._t("关于"))
        self.act_about.setText(self._t("关于 VibSpec"))
        self.act_home.setText(self._t("打开项目主页"))
        self.menu_lang.setTitle(self._t("语言 / Language"))
        for c, act in self.lang_actions.items():
            act.setChecked(c == code)

        # 动态内容
        self.on_selection_changed()
        self._refresh_channel_list()
        if self.signals:
            self.plot_all()
        self.statusBar().showMessage(self._t("就绪"))

    def show_about(self):
        """「关于」对话框：软件名、版本、作者与项目主页。"""
        zh = self.lang == i18n.LANG_ZH
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        if zh:
            box.setWindowTitle("关于 VibSpec")
            body = (
                f"<p style='font-size:14px'><b>{i18n.APP_TITLE_ZH}</b></p>"
                f"<p>版本：{i18n.APP_VERSION}<br>"
                f"作者：{i18n.PROJECT_AUTHOR}</p>"
                f"<p>项目主页：<br>"
                f"<a href='{i18n.PROJECT_HOMEPAGE}'>{i18n.PROJECT_HOMEPAGE}</a></p>"
                f"<p>本软件用于振动采样信号的时域与频域分析，"
                f"支持软件 CSV、黑盒 MAT、示波器 MAT 三种数据来源。</p>"
            )
            ok_text = "确定"
        else:
            box.setWindowTitle("About VibSpec")
            body = (
                f"<p style='font-size:14px'><b>{i18n.APP_TITLE_EN}</b></p>"
                f"<p>Version: {i18n.APP_VERSION}<br>"
                f"Author: {i18n.PROJECT_AUTHOR}</p>"
                f"<p>Project homepage:<br>"
                f"<a href='{i18n.PROJECT_HOMEPAGE}'>{i18n.PROJECT_HOMEPAGE}</a></p>"
                f"<p>A desktop tool for time- and frequency-domain analysis of vibration "
                f"records, supporting software CSV, black-box MAT and oscilloscope MAT "
                f"sources.</p>"
            )
            ok_text = "OK"
        box.setTextFormat(Qt.RichText)
        box.setText(body)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.button(QtWidgets.QMessageBox.Ok).setText(ok_text)
        box.exec_()

    def open_homepage(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(i18n.PROJECT_HOMEPAGE))

    def _connect(self):
        self.btn_file.clicked.connect(self.on_import_files)
        self.btn_folder.clicked.connect(self.on_import_folder)
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_all.clicked.connect(lambda: self._check_all(True))
        self.btn_none.clicked.connect(lambda: self._check_all(False))
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemSelectionChanged.connect(self.on_selection_changed)
        self.tree.customContextMenuRequested.connect(self.on_tree_context_menu)
        self.chk_all_ch.stateChanged.connect(self.on_ch_all_channels)
        self.ch_list.itemDoubleClicked.connect(self.on_ch_double_clicked)
        self.ch_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ch_list.customContextMenuRequested.connect(self.on_ch_context_menu)
        self.btn_win1_all.clicked.connect(lambda: self._assign_all(0))
        self.btn_win2_all.clicked.connect(lambda: self._assign_all(1))
        self.btn_del.clicked.connect(self.on_delete_selected)
        self.cmb_norm.currentIndexChanged.connect(self.plot_all)
        self.chk_pp.stateChanged.connect(self.plot_all)
        self.cmb_pp.currentIndexChanged.connect(self.plot_all)
        self.chk_pp_also.stateChanged.connect(self.plot_all)
        self.btn_pp_show.clicked.connect(self.show_envelope_spectrum)
        self.spin_pp_fc.valueChanged.connect(self._on_pp_param_changed)
        self.spin_pp_n.valueChanged.connect(self._on_pp_param_changed)
        self.btn_plot.clicked.connect(self.plot_all)
        self.btn_png.clicked.connect(self.export_png)
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_export_all.clicked.connect(self.export_all_images)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.spin_fs.valueChanged.connect(self.on_fs_changed)

        # 文件树中按 Delete 键删除选中的文件
        sc = QtWidgets.QShortcut(QtGui.QKeySequence("Delete"), self.tree)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.on_delete_selected)

    # ---------------- 导入 ----------------

    def on_import_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择数据文件", "",
            "数据文件 (*.csv *.mat *.MAT);;CSV (*.csv);;MAT (*.mat *.MAT);;所有文件 (*)")
        if paths:
            self._add_paths(paths)

    def on_import_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择数据文件夹")
        if d:
            self._add_paths(loader.list_data_files(d))

    def _add_paths(self, paths: List[str]):
        ok, fail = 0, []
        for p in paths:
            if p in self.signals:
                continue
            try:
                s = loader.load_any(p)
            except Exception as e:
                fail.append(f"{os.path.basename(p)}: {e}")
                continue
            self.signals[p] = s
            self._add_tree_item(s)
            ok += 1

        msg = f"已导入 {ok} 个文件"
        if fail:
            msg += f"，失败 {len(fail)} 个"
            QtWidgets.QMessageBox.warning(self, "部分文件导入失败",
                                          "\n".join(fail[:12]))
        self.statusBar().showMessage(msg)
        if ok:
            self.plot_all()

    def _add_tree_item(self, s: loader.SignalSet):
        item = QtWidgets.QTreeWidgetItem([s.name, s.summary_line()])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        item.setCheckState(0, Qt.Checked)
        item.setData(0, Qt.UserRole, s.path)
        # 工具提示：工况信息
        tip = "\n".join(f"{k}: {v}" for k, v in s.meta.items() if v)
        if tip:
            item.setToolTip(0, tip)
        for w in s.warnings:
            item.setToolTip(1, (item.toolTip(1) + "\n" + w).strip())

        for cname in s.channels:
            ch = QtWidgets.QTreeWidgetItem([f"    {cname}", ""])
            ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
            ch.setCheckState(0, Qt.Checked)
            ch.setData(0, Qt.UserRole, (s.path, cname))
            item.addChild(ch)

        self.tree.addTopLevelItem(item)
        self.file_items[s.path] = item
        item.setExpanded(True)

    def on_clear(self):
        self.tree.clear()
        self.signals.clear()
        self.file_items.clear()
        self.win_assign.clear()
        for wd in self.windows:
            for kind in ("time", "freq", "psd"):
                wd[kind].clear()
                wd[kind].redraw()
        self.stats.clear()
        self.info.clear()
        self._refresh_channel_list()
        self.statusBar().showMessage("已清空")

    # ---------------- 删除文件 ----------------

    def _paths_from_items(self, items) -> List[str]:
        """从树节点取出去重后的文件路径（子通道节点也能解析到父文件路径）。"""
        out = []
        for it in items:
            key = it.data(0, Qt.UserRole)
            path = key[0] if isinstance(key, tuple) else key
            if path and path not in out:
                out.append(path)
        return out

    def on_delete_selected(self):
        """删除文件树里选中的文件（快捷键 Delete）。**不动磁盘原文件**。"""
        paths = self._paths_from_items(self.tree.selectedItems())
        if not paths:
            QtWidgets.QMessageBox.information(
                self, "提示",
                "请先在左上角文件列表里选中要删除的文件（Ctrl/Shift 可多选），\n"
                "再按「删除选中」或 Delete 键。")
            return
        self._remove_paths(paths)

    def on_tree_context_menu(self, pos):
        """文件树右键菜单：删除 / 只保留选中 / 展开折叠。"""
        it = self.tree.itemAt(pos)
        if it is not None and not it.isSelected():
            self.tree.clearSelection()
            it.setSelected(True)
        paths = self._paths_from_items(self.tree.selectedItems())
        m = QtWidgets.QMenu(self)
        a_del = m.addAction(
            f"删除选中的 {len(paths)} 个文件" if paths else "删除选中文件（未选中）")
        a_del.setEnabled(bool(paths))
        a_only = m.addAction("只保留选中，删除其余")
        a_only.setEnabled(bool(paths) and len(paths) < len(self.signals))
        m.addSeparator()
        a_exp = m.addAction("展开全部通道")
        a_col = m.addAction("折叠全部通道")
        act = m.exec_(self.tree.mapToGlobal(pos))
        if act == a_del:
            self._remove_paths(paths)
        elif act == a_only:
            keep = set(paths)
            self._remove_paths([p for p in list(self.signals) if p not in keep])
        elif act == a_exp:
            self.tree.expandAll()
        elif act == a_col:
            self.tree.collapseAll()

    def _remove_paths(self, paths: List[str]):
        """把指定文件从软件中移除。仅从内存/列表移出，**不删除磁盘文件**。"""
        paths = [p for p in paths if p in self.signals]
        if not paths:
            return
        names = [os.path.basename(p) for p in paths]
        for p in paths:
            s = self.signals.pop(p, None)
            if s is not None:
                # 一并清除这些通道的窗口分配，避免残留指向已删除文件的记录
                for ch in s.channels:
                    self.win_assign.pop(self._ch_key(s, ch), None)
            item = self.file_items.pop(p, None)
            if item is not None:
                idx = self.tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)
        self._refresh_channel_list()
        self.plot_all()
        shown = "、".join(names[:5]) + ("…" if len(names) > 5 else "")
        self.statusBar().showMessage(
            f"已从列表移除 {len(paths)} 个文件（原文件仍在磁盘上）：{shown}")

    def _check_all(self, state: bool):
        st = Qt.Checked if state else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setCheckState(0, st)
            for j in range(it.childCount()):
                it.child(j).setCheckState(0, st)

    def on_item_changed(self, item, col):
        """父节点勾选联动子节点，子节点变化反映到父节点。"""
        if col != 0:
            return
        self.tree.blockSignals(True)
        if item.parent() is None:
            st = item.checkState(0)
            for j in range(item.childCount()):
                item.child(j).setCheckState(0, st)
        else:
            parent = item.parent()
            states = [parent.child(j).checkState(0) for j in range(parent.childCount())]
            parent.setCheckState(0, Qt.Checked if all(s == Qt.Checked for s in states)
                                 else (Qt.Unchecked if all(s == Qt.Unchecked for s in states)
                                       else Qt.PartiallyChecked))
        self.tree.blockSignals(False)
        self._refresh_channel_list()

    def on_selection_changed(self):
        items = self.tree.selectedItems()
        if not items:
            return
        it = items[0]
        key = it.data(0, Qt.UserRole)
        path = key[0] if isinstance(key, tuple) else key
        s = self.signals.get(path)
        if not s:
            return
        lines = [f"文件: {s.name}", f"类型: {s.source_type}",
                 f"采样率: {s.fs:g} Hz", f"点数: {s.n_samples}",
                 f"时长: {s.duration:.4f} s", f"通道: {', '.join(s.channels)}"]
        if s.meta:
            lines.append("--- 工况 ---")
            lines += [f"{k}: {v}" for k, v in s.meta.items() if v]
        if s.warnings:
            lines.append("--- 提示 ---")
            lines += s.warnings
        self.info.setPlainText("\n".join(lines))

        # 同步采样率输入框（不触发重绘）
        self.spin_fs.blockSignals(True)
        self.spin_fs.setValue(s.fs)
        self.spin_fs.blockSignals(False)

    # ---------------- 通道列表 ----------------

    def _checked_files(self) -> List[loader.SignalSet]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) in (Qt.Checked, Qt.PartiallyChecked):
                p = it.data(0, Qt.UserRole)
                if p in self.signals:
                    out.append(self.signals[p])
        return out

    def _selected_channels(self, s: loader.SignalSet) -> List[str]:
        it = self.file_items.get(s.path)
        if it is None:
            return list(s.channels.keys())
        keep = []
        for j in range(it.childCount()):
            ch = it.child(j)
            if ch.checkState(0) == Qt.Checked:
                keep.append(ch.text(0).strip())
        return keep

    def on_ch_all_channels(self, state):
        st = Qt.Checked if state else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            for j in range(it.childCount()):
                it.child(j).setCheckState(0, st)
        self._refresh_channel_list()

    def _refresh_channel_list(self):
        """刷新通道列表，并标注每个通道被分配到哪个窗口。

        设计说明（针对"窗口切换操作繁琐"的改进）：
        - 每行末尾用醒目的 [上] / [下] 标签，而不是被截断的长文本；
        - 文件名与通道名分开显示，长名也能看清；
        - 支持双击行直接切换窗口（见 self.ch_list.itemDoubleClicked）。
        新出现的通道默认归入「上窗口」，不弹窗、不递归。
        """
        prev = {it.data(Qt.UserRole) for it in self.ch_list.selectedItems()}

        # 补齐默认分配
        for key, _s, _c in self._all_ch_keys():
            self.win_assign.setdefault(key, 0)

        self.ch_list.blockSignals(True)
        self.ch_list.clear()
        for key, s, ch in self._all_ch_keys():
            wi = self.win_assign.get(key, 0)
            tag = "上" if wi == 0 else "下"
            item = QtWidgets.QListWidgetItem(f"[{tag}]  {ch}   —   {s.name}")
            item.setData(Qt.UserRole, key)
            # 上窗口蓝色、下窗口橙色，便于区分
            item.setForeground(QtGui.QColor("#0072BD" if wi == 0 else "#D95319"))
            item.setToolTip(
                f"文件：{s.name}\n通道：{ch}\n当前：{'上' if wi == 0 else '下'}窗口\n"
                "双击可切换到另一窗口；右键可批量分配。")
            self.ch_list.addItem(item)
            if key in prev:
                item.setSelected(True)
        self.ch_list.blockSignals(False)

    def _item_key_at(self, item):
        return item.data(Qt.UserRole) if item is not None else None

    def on_ch_double_clicked(self, item):
        """双击通道行：在 上/下 窗口之间切换。"""
        key = self._item_key_at(item)
        if not key:
            return
        cur = self.win_assign.get(key, 0)
        new = 1 - cur
        self.win_assign[key] = new
        self._refresh_channel_list()
        # 保持该行选中状态，便于连续操作
        for i in range(self.ch_list.count()):
            it = self.ch_list.item(i)
            if it.data(Qt.UserRole) == key:
                it.setSelected(True)
                break
        self.plot_all()
        self.statusBar().showMessage(
            f"{key}  →  {'上' if new == 0 else '下'}窗口（已重绘）")

    def on_ch_context_menu(self, pos):
        """通道列表右键菜单：批量分配。"""
        item = self.ch_list.itemAt(pos)
        if item is not None and not item.isSelected():
            self.ch_list.clearSelection()
            item.setSelected(True)
        keys = [self._item_key_at(it) for it in self.ch_list.selectedItems()]
        keys = [k for k in keys if k]
        if not keys:
            return

        m = QtWidgets.QMenu(self)
        a_up = m.addAction(f"选中的 {len(keys)} 个 → 上窗口")
        a_dn = m.addAction(f"选中的 {len(keys)} 个 → 下窗口")
        m.addSeparator()
        a_swap = m.addAction("全部反转上/下")
        act = m.exec_(self.ch_list.mapToGlobal(pos))
        if act == a_up:
            self._assign_keys(keys, 0)
        elif act == a_dn:
            self._assign_keys(keys, 1)
        elif act == a_swap:
            for k, _s, _c in self._all_ch_keys():
                self.win_assign[k] = 1 - self.win_assign.get(k, 0)
            self._refresh_channel_list()
            self.plot_all()
            self.statusBar().showMessage("已反转全部通道的上/下窗口归属")
        else:
            return

    # ---------------- 参数变化 ----------------

    def on_fs_changed(self, val):
        """修改采样率：**只作用于左侧选中的文件**，并立即重绘。

        问题背景（"时域时间轴偶发异常"的主要原因）：
        此前在**未选中任何文件**时，会将新采样率应用到**全部未锁定文件**。
        示波器 MAT 的采样率默认处于未锁定状态，因此调整该数值框时，
        所有示波器文件的采样率会被一并修改，时域横轴随之整体错位；
        同时因当时修改后**未触发重绘**，需等待下一次操作才显现，表现为"偶发异常"。
        现改为：仅修改选中项；未选中时给出明确提示，不进行静默批量修改。
        """
        paths = self._paths_from_items(self.tree.selectedItems())
        if not paths:
            self.statusBar().showMessage(
                "请先在左侧「文件/通道」列表里选中要改采样率的文件，再改这个值"
                "（Ctrl/Shift 可多选）")
            return
        changed = [p for p in paths
                   if p in self.signals and not self.signals[p].fs_locked]
        if not changed:
            self.statusBar().showMessage("选中的文件采样率已锁定或未导入，未做修改")
            return
        for p in changed:
            self.signals[p].fs = float(val)
        self.plot_all()
        self.statusBar().showMessage(
            f"已把 {len(changed)} 个文件的采样率改为 {val:g} Hz（已重绘）")

    def on_tab_changed(self, idx):
        """切换标签页时，只显示对应画布的工具条（不销毁、不重建）。

        注意事项：此前曾用 setParent(None)+deleteLater 重建工具条，导致
        NavigationToolbar2 的 actions 变为悬空指针，下次 fig.clear() 时抛出
        RuntimeError: wrapped C/C++ object of type QAction has been deleted。
        """
        sender = self.sender()
        for wd in self.windows:
            if wd["tabs"] is not sender:
                continue
            for i, tb in enumerate(wd["toolbars"]):
                tb.setVisible(i == idx)
            if wd is self.windows[0]:
                self.toolbar = wd["toolbars"][idx]
            return

    # ---------------- 绘制 ----------------

    def _window_key(self) -> str:
        # 下拉项的显示文本会随语言切换，故按索引映射到内部键，
        # 不能用 currentText()（切到英文后会 KeyError）。
        keys = list(analysis.WINDOWS.keys())
        idx = max(0, min(self.cmb_window.currentIndex(), len(keys) - 1))
        return analysis.WINDOWS[keys[idx]]

    def _fmax(self, fs) -> float:
        v = self.spin_fmax.value()
        return v if v > 0 else fs / 2.0

    def _norm_mode(self) -> str:
        """返回归一化模式键: none / rms / peak / zscore"""
        idx = self.cmb_norm.currentIndex()
        return ["none", "rms", "peak", "zscore"][idx]

    @staticmethod
    def _apply_norm(seg: np.ndarray, mode: str) -> np.ndarray:
        """时域归一化。仅用于绘图显示，不改动原始数据。

        注意：全部模式都会**去均值**后再缩放。
        原因是黑盒数据含约 0.7V 直流偏置，若仅作除法运算，曲线整体被抬至
        较高位置，波形被压缩成一条粗线，反而更难分辨。
        去均值使零点回到中线，是归一化显示的正确做法。
        （如需查看原始直流分量，请选择「不归一化」。）
        """
        if mode == "none" or seg.size == 0:
            return seg
        c = seg - float(np.mean(seg))
        if mode == "zscore":
            s = float(np.std(c))
            return c / s if s > 0 else c
        if mode == "rms":
            r = float(np.sqrt(np.mean(c ** 2)))
            return c / r if r > 0 else c
        if mode == "peak":
            p = float(np.max(np.abs(c)))
            return c / p if p > 0 else c
        return seg

    def _amp_axis_label(self, mode: str, unit: str) -> str:
        """纵轴标签：幅值（单位）。随语言切换。"""
        return f"{self._t('幅值 (')}{self._unit_label(mode, unit)})"

    def _unit_label(self, mode: str, unit: str) -> str:
        if mode == "none":
            return f"{unit}{self._t('（原始）')}"
        return self._t({"rms": "× RMS（已去均值）", "peak": "× 峰值（已去均值）",
                        "zscore": "σ（已去均值）"}.get(mode, unit))

    @staticmethod
    def _norm_factor(x: np.ndarray, mode: str) -> float:
        """频域缩放因子。谱本身就是交流量，这里只取尺度、不再去均值。"""
        if mode == "none" or x.size == 0:
            return 1.0
        if mode == "zscore":
            s = float(np.std(x))
            return s if s > 0 else 1.0
        if mode == "rms":
            r = float(np.sqrt(np.mean((x - np.mean(x)) ** 2)))
            return r if r > 0 else 1.0
        if mode == "peak":
            p = float(np.max(np.abs(x - np.mean(x))))
            return p if p > 0 else 1.0
        return 1.0

    # ---------------- 预处理链（MATLAB 算法） ----------------

    def _pp_enabled(self) -> bool:
        return self.chk_pp.isChecked()

    def _on_pp_param_changed(self, *_):
        """FIR 参数变化：只在处理链已启用时重绘，避免无谓计算。"""
        if self._pp_enabled():
            self.plot_all()

    def _pp_method(self) -> str:
        """返回 fir / svd / emd / raw，对应 analysis.envelope_spectrum_pipeline。"""
        return ["fir", "svd", "emd", "raw"][self.cmb_pp.currentIndex()]

    def _apply_chain(self, x: np.ndarray, fs: float) -> Optional[dict]:
        """按当前面板设置执行一次处理链，返回 pipeline 结果字典；失败时返回 None。

        对应参考 MATLAB 脚本的处理链路：
            高通FIR(500Hz,180阶) -> envelopeLiao -> abs(fft(up))
        或  SVDLiao(28,[1,2,3]) -> envelopeLiao -> abs(fft(up))
        """
        method = self._pp_method()
        fc = float(self.spin_pp_fc.value())
        n_fir = int(self.spin_pp_n.value())
        num = int(self.spin_pp_num.value()) or None
        try:
            return analysis.envelope_spectrum_pipeline(
                x, fs, fc=fc, n_fir=n_fir, num=num, lfr=None,
                method=method, first_bin=1)
        except ImportError as e:
            # EMD 等可选依赖缺失：给出明确指引，避免整条链路静默失败
            self.statusBar().showMessage(f"处理链不可用：{e}")
            return None
        except Exception as e:
            self.statusBar().showMessage(f"处理链失败（{method}）：{e}")
            return None

    def _pp_label(self) -> str:
        m = self._pp_method()
        if m == "fir":
            return f"高通{self.spin_pp_fc.value():g}Hz/{self.spin_pp_n.value()}阶"
        if m == "svd":
            return "SVD(28,[1,2,3])"
        if m == "emd":
            return "EMD IMF1"
        return "仅包络"

    # ---------------- 窗口分配 ----------------

    def _ch_key(self, s, ch):
        return f"{s.name} :: {ch}"

    def _all_ch_keys(self):
        """返回 [(key, SignalSet, ch), ...]，顺序与 ch_list 一致。"""
        out = []
        for s in self._checked_files():
            for ch in self._selected_channels(s):
                out.append((self._ch_key(s, ch), s, ch))
        return out

    def _window_for(self, key: str) -> int:
        return self.win_assign.get(key, 0)

    def _assign_keys(self, keys, w: int):
        """把给定的一组通道 key 分配到窗口 w，然后刷新列表并重绘。

        注意：key 必须从 item 的 ``Qt.UserRole`` 取，**不能**用 ``item.text()``
        —— 列表显示文本是 ``[上] CH03 — 文件名``，早已不等于 key 本身
        （此前 `_assign_selection` 即因此缺陷导致窗口分配错位）。
        """
        keys = [k for k in keys if k]
        for k in keys:
            self.win_assign[k] = w
        self._refresh_channel_list()
        self.plot_all()
        self.statusBar().showMessage(
            f"已把 {len(keys)} 个通道分配到{'上' if w == 0 else '下'}窗口")

    def _assign_all(self, w: int):
        self._assign_keys([k for k, _s, _c in self._all_ch_keys()], w)

    # ---------------- 绘制 ----------------

    def plot_all(self):
        files = self._checked_files()
        if not files:
            self.statusBar().showMessage("没有勾选任何文件")
            return

        win = self._window_key()
        detrend = self.chk_detrend.isChecked()
        nfft = self.spin_nfft.value() or None
        nperseg = self.spin_nperseg.value() or None
        overlap = float(self.cmb_overlap.currentText())
        logx = self.chk_logx.isChecked()
        norm_mode = self._norm_mode()
        pp_on = self._pp_enabled()

        try:
            # 先把所有窗口的三个画布清空
            for wd in self.windows:
                for key in ("time", "freq", "psd"):
                    wd[key].clear()

            drawn = 0
            stats_pool = []          # (label, stats, window_idx)
            # 每个窗口独立配色计数，避免两窗口颜色互相错位
            color_i = [0, 0]
            # 每个窗口实际绘制数据的坐标范围（收尾时统一设轴）。
            # 不可"每绘制一条即设置一次 xlim"，否则**最后一条曲线**会决定整个窗口的
            # 坐标轴；当多条曲线的采样率/长度不同时，横轴会随绘制顺序变化，
            # 表现为"时间轴偶发异常"。此处改为取实际数据的并集。
            t_rng = {0: [], 1: []}      # (t_min, t_max)
            f_top = {0: [], 1: []}      # 各曲线的频率上限
            fs_seen = {0: set(), 1: set()}

            for s in files:
                fmax = self._fmax(s.fs)
                for ch in self._selected_channels(s):
                    if ch not in s.channels:
                        continue
                    x = s.channels[ch]
                    key = self._ch_key(s, ch)
                    wi = self._window_for(key)
                    # 窗口内该通道若被手动覆盖过 fs，用它自己的
                    fs = s.fs
                    color = MATLAB_COLORS[color_i[wi] % len(MATLAB_COLORS)]
                    color_i[wi] += 1
                    label = f"{os.path.splitext(s.name)[0]} · {ch}"
                    drawn += 1

                    # ---- 预处理链（可选）----
                    pipe = self._apply_chain(x, fs) if pp_on else None
                    # 谱计算用的信号：勾选"傅里叶谱也用处理后的信号"则替换
                    x_spec = x
                    if pipe is not None and self.chk_pp_also.isChecked():
                        x_spec = pipe["filtered"]

                    # ---- 时域 ----
                    ax = self.windows[wi]["time"].ax
                    # 参与绘制的数组长度：处理链会把信号截断到 Num，
                    # 必须以其作为边界，否则 t0 超过 Num 时会切出空数组，
                    # 时间轴会退化为 0~1 s，这是"时间轴偶发异常"的成因之一。
                    if pipe is not None:
                        y_pp = pipe["filtered"]
                        up, down = pipe["up"], pipe["down"]
                        n_tot = min(len(x), len(y_pp))
                    else:
                        n_tot = len(x)
                    n_tot = max(1, n_tot)

                    span = self.spin_tspan.value()
                    n_span = int(round(span * fs)) if (span and span > 0) else n_tot
                    n_span = max(1, min(n_span, n_tot))
                    n0 = int(round(self.spin_t0.value() * fs))
                    # 将起点限制在"仍可取得完整显示窗口"的范围内。
                    # 若 t0 超出可用数据范围（典型情形：处理链将信号截断至 Num 后，
                    # 仅剩 0.82 s，而 t0 仍为 1.0 s），则显示**最后一段**，
                    # 而非退化为单个样点，否则横轴将塌缩为一点
                    # （matplotlib 会报出 "identical low and high xlims"）。
                    n0 = max(0, min(n0, n_tot - n_span))
                    n1 = min(n_tot, n0 + n_span)
                    t = np.arange(n0, n1) / fs          # 时间轴严格由实际样本索引换算

                    if pipe is not None:
                        # 处理链开启：画滤波/重构后的信号 + 上下包络
                        seg = self._apply_norm(y_pp[n0:n1], norm_mode)
                        ax.plot(t, seg, color=color, linewidth=0.8,
                                label=f"{label} [{self._pp_label()}]")
                        u = self._apply_norm(up[n0:n1], norm_mode)
                        d = self._apply_norm(down[n0:n1], norm_mode)
                        ax.plot(t, u, color=color, linewidth=0.6, linestyle="--",
                                alpha=0.65, label=f"{self._t('包络up')} · {ch}")
                        ax.plot(t, -np.abs(d), color=color, linewidth=0.5,
                                linestyle=":", alpha=0.5)
                    else:
                        seg = self._apply_norm(x[n0:n1], norm_mode)
                        ax.plot(t, seg, color=color, linewidth=0.7, label=label)
                    ax.set_xlabel(self._t("时间 (s)"))
                    ax.set_ylabel(self._amp_axis_label(norm_mode, s.unit))
                    if len(t):
                        t_rng[wi].append((float(t[0]), float(t[-1])))
                    fs_seen[wi].add(float(fs))
                    if len(stats_pool) < 4:
                        # 统计量基于完整信号计算，与归一化设置无关
                        stats_pool.append((label, analysis.time_stats(x, fs), wi))

                    # ---- 频域幅值谱 ----
                    ax = self.windows[wi]["freq"].ax
                    f, a = analysis.amplitude_spectrum(x_spec, fs, win, nfft=nfft,
                                                       detrend=detrend)
                    if f.size:
                        a = a / self._norm_factor(x, norm_mode)
                        ax.plot(f, a, color=color, linewidth=0.7, label=label)
                    ax.set_xlabel(self._t("频率 (Hz)"))
                    ax.set_ylabel(self._amp_axis_label(norm_mode, s.unit))
                    f_top[wi].append(float(fmax))

                    # ---- dB 功率谱 ----
                    ax = self.windows[wi]["psd"].ax
                    fp, p = analysis.psd_welch(
                        x_spec, fs, win, nperseg=nperseg, overlap_pct=overlap,
                        nfft=nfft, detrend="constant" if detrend else "linear")
                    if fp.size:
                        if norm_mode != "none":
                            # 归一化后能量尺度变化：除以因子的平方，保持形状可比
                            kf = self._norm_factor(x, norm_mode)
                            p = p / (kf ** 2)
                        ax.plot(fp, analysis.psd_to_db(p), color=color,
                                linewidth=0.7, label=label)
                    ax.set_xlabel(self._t("频率 (Hz)"))
                    ax.set_ylabel(self._t("功率谱密度 (dB/Hz)"))
                    ax.set_ylim(self.spin_ylim.value(), None)

            # 统一收尾：坐标范围、标题、对数轴、图例
            for wi, wd in enumerate(self.windows):
                # 时域横轴 = 本窗口实际绘制数据的并集范围
                if t_rng[wi]:
                    lo = min(a for a, _b in t_rng[wi])
                    hi = max(b for _a, b in t_rng[wi])
                    if hi <= lo:
                        # 单点或零跨度会使坐标变换奇异，此处略微扩展区间
                        hi = lo + max(1e-6, 1.0 / 1000.0)
                    wd["time"].ax.set_xlim(lo, hi)
                # 频域横轴 = 本窗口所有曲线的最大上限
                fmax_w = max(f_top[wi]) if f_top[wi] else None
                # 标题里的 fs 如实反映本窗口实际绘制的数据（可能多文件混画）
                fss = sorted(fs_seen[wi])
                fs_txt = ("  fs=" + " / ".join(format(v, "g") for v in fss) + " Hz"
                          if fss else "")
                win_txt = self._t("上" if wi == 0 else "下")
                for kind, title in (("time", "时域波形"),
                                    ("freq", "频域幅值谱（单边 FFT）"),
                                    ("psd", "功率谱密度 Welch PSD")):
                    ax = wd[kind].ax
                    head = (f"[{win_txt} window] {self._t(title)}"
                            if self.lang == i18n.LANG_EN
                            else f"[{win_txt}窗口] {self._t(title)}")
                    ax.set_title(f"{head}{fs_txt if kind == 'time' else ''}",
                                 fontsize=10)
                    if kind != "time" and fmax_w:
                        if logx:
                            ax.set_xscale("log")
                            ax.set_xlim(1.0, fmax_w)
                        else:
                            ax.set_xlim(0, fmax_w)
                    if ax.get_legend_handles_labels()[0]:
                        ax.legend(loc="upper right", fontsize=7, ncol=1, framealpha=0.85)
                    wd[kind].redraw()

            # 统计表：同时列上下两个窗口的首个通道
            if stats_pool:
                blocks = []
                for lb, st, wi in stats_pool:
                    txt = [f"[{self._t('上' if wi == 0 else '下')}] {lb}"]
                    txt += [f"{k}: {v:.6g}" if isinstance(v, float) else f"{k}: {v}"
                            for k, v in st.items()]
                    blocks.append("\n".join(txt))
                self.stats.setPlainText("\n\n".join(blocks))

            self._refresh_channel_list()
            ok_msg = (f"已绘制 {drawn} 条曲线（上窗口 "
                      f"{sum(1 for k, _s, _c in self._all_ch_keys() if self._window_for(k) == 0)} 条"
                      f" / 下窗口 "
                      f"{sum(1 for k, _s, _c in self._all_ch_keys() if self._window_for(k) == 1)} 条）"
                      f" · {self._t('归一化')}={self._norm_text()}"
                      + (f" · 处理链={self._pp_label()}" if pp_on else ""))
            warn = self._unit_mismatch_msg(files)
            if warn and norm_mode == "none":
                warn += "（可开启归一化解决重叠）"
            self.statusBar().showMessage(f"{ok_msg}   |   {warn}" if warn else ok_msg)

        except Exception as e:
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "绘图失败",
                                           f"{e}\n\n{traceback.format_exc()}")

    def show_envelope_spectrum(self):
        """把勾选信号的包络谱 abs(fft(up)) 画到上窗口的「频域」页。

        对应 MATLAB 脚本里的
            ODaF2 = abs(fft(up)); plot(sf(2:Lfr), ODaF2(2:Lfr))
        横轴与 MATLAB 的 sf 完全一致（0~fs，未归一化的双边 |FFT|）。
        """
        files = self._checked_files()
        if not files:
            QtWidgets.QMessageBox.information(self, "提示", "请先勾选文件")
            return
        num = int(self.spin_pp_num.value()) or None
        lfr = int(self.spin_pp_lfr.value()) or None
        ax = self.windows[0]["freq"].ax
        ax.clear()
        self.windows[0]["freq"]._style_axes(ax)
        drawn = 0
        env_fmax = 0.0
        for i, s in enumerate(files):
            for ch in self._selected_channels(s):
                if ch not in s.channels:
                    continue
                x = s.channels[ch]
                try:
                    pipe = self._apply_chain(x, s.fs)
                except Exception as e:
                    self.statusBar().showMessage(f"包络谱失败：{e}")
                    continue
                if pipe is None:
                    continue
                # first_bin=1 跳过直流，对应 MATLAB 的 sf(2:Lfr)：
                # 包络恒为正、直流分量极大，不跳过会使低频故障峰被压制。
                ef, ea = analysis.envelope_spectrum(
                    pipe["up"], s.fs, num=num, lfr=lfr, first_bin=1)
                if ef.size == 0:
                    continue
                color = MATLAB_COLORS[i % len(MATLAB_COLORS)]
                ax.plot(ef, ea, color=color, linewidth=0.8,
                        label=f"{os.path.splitext(s.name)[0]} · {ch}")
                env_fmax = max(env_fmax, float(ef[-1]))
                drawn += 1
        if not drawn:
            self.statusBar().showMessage("没有可绘制的包络谱")
            return
        ax.set_xlabel(self._t("频率 (Hz)"))
        ax.set_ylabel(self._t("幅值 |FFT(包络)|（未归一化，已跳过直流）"))
        ax.set_title(self._t("[上窗口] 包络谱 Envelope Spectrum · ")
                     + self._pp_label(),
                     fontsize=10)
        ax.set_xlim(0, env_fmax if env_fmax > 0 else 1)
        ax.legend(loc="upper right", fontsize=7, framealpha=0.85)
        self.windows[0]["freq"].redraw()
        self.windows[0]["tabs"].setCurrentIndex(1)
        self.statusBar().showMessage(
            f"已绘制 {drawn} 条包络谱 · {self._pp_label()} · "
            f"Num={num or '全部'} Lfr={lfr or '全部'}")

    def _unit_mismatch_msg(self, files):
        """检测不同来源之间的量级差异，返回提示文本（不自动缩放，保持物理量真实）。"""
        if len(files) < 2:
            return ""
        rms = {}
        for s in files:
            chans = self._selected_channels(s)
            vals = [float(np.std(s.channels[c])) for c in chans if c in s.channels]
            if vals:
                rms[s.source_type] = max(rms.get(s.source_type, 0.0), max(vals))
        if len(rms) < 2:
            return ""
        lo, hi = min(rms.values()), max(rms.values())
        if lo <= 0 or hi / lo < 10:
            return ""
        detail = ", ".join(f"{k}={v:.5g}V" for k, v in sorted(rms.items()))
        return (f"注意：不同来源信号量级相差 {hi/lo:.0f} 倍（{detail}），"
                f"属真实差异，未做归一化")

    # ---------------- 导出 ----------------

    def _current_canvas(self) -> PlotCanvas:
        """取当前「有焦点」窗口的当前标签页画布；优先上窗口。"""
        wd = self.windows[0]
        for w in self.windows:
            if w["tabs"].hasFocus() or w["tabs"] is self.tabs:
                wd = w
                break
        return [wd["time"], wd["freq"], wd["psd"]][wd["tabs"].currentIndex()]

    def export_png(self):
        c = self._current_canvas()
        if not c.ax.get_legend_handles_labels()[0]:
            QtWidgets.QMessageBox.information(self, "提示", "当前图没有内容，请先绘制")
            return
        d, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出图像", "spectrum.png", "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not d:
            return
        c.fig.savefig(d, dpi=200, facecolor=c.fig.get_facecolor())
        self.statusBar().showMessage(f"已导出 {d}")

    def export_csv(self):
        files = self._checked_files()
        if not files:
            return
        d, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出谱数据", "spectrum.csv", "CSV (*.csv)")
        if not d:
            return
        win = self._window_key()
        nfft = self.spin_nfft.value() or None
        nperseg = self.spin_nperseg.value() or None
        overlap = float(self.cmb_overlap.currentText())
        detrend = self.chk_detrend.isChecked()

        with open(d, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("# 导出: 频率(Hz), 幅值谱(V), PSD(dB/Hz) —— 每通道一组\n")
            for s in files:
                for ch in self._selected_channels(s):
                    f, a = analysis.amplitude_spectrum(s.channels[ch], s.fs, win,
                                                       nfft=nfft, detrend=detrend)
                    fp, p = analysis.psd_welch(s.channels[ch], s.fs, win,
                                               nperseg=nperseg, overlap_pct=overlap,
                                               nfft=nfft)
                    db = analysis.psd_to_db(p)
                    fh.write(f"# {s.name} :: {ch}\n")
                    fh.write("freq_amp_Hz,amp_V,freq_psd_Hz,psd_dB_per_Hz\n")
                    m = max(len(f), len(fp))
                    for i in range(m):
                        c1 = f"{f[i]:.6f},{a[i]:.10g}" if i < len(f) else ","
                        c2 = f"{fp[i]:.6f},{db[i]:.6f}" if i < len(fp) else ","
                        fh.write(f"{c1},{c2}\n")
        self.statusBar().showMessage(f"已导出 {d}")

    def export_all_images(self):
        files = self._checked_files()
        if not files:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not d:
            return
        n = 0
        try:
            for idx, s in enumerate(files):
                for ch in self._selected_channels(s):
                    fig = Figure(figsize=(11, 9), dpi=110, facecolor="white")
                    axes = [fig.add_subplot(3, 1, i + 1) for i in range(3)]
                    for ax in axes:
                        ax.grid(True, color="#d0d0d0", linewidth=0.6)
                        ax.minorticks_on()
                        ax.tick_params(labelsize=9)
                    x = s.channels[ch]
                    win = self._window_key()
                    nfft = self.spin_nfft.value() or None

                    t = np.arange(len(x)) / s.fs
                    axes[0].plot(t, x, color=MATLAB_COLORS[0], linewidth=0.7)
                    axes[0].set_title(f"{s.name} · {ch} — {self._t('时域')}  "
                                      f"(fs={s.fs:g} Hz, "
                                      f"N={len(x)}, T={s.duration:.3f}s)", fontsize=10)
                    axes[0].set_xlabel(self._t("时间 (s)"))
                    axes[0].set_ylabel(self._amp_axis_label("none", s.unit))

                    f, a = analysis.amplitude_spectrum(x, s.fs, win, nfft=nfft)
                    axes[1].plot(f, a, color=MATLAB_COLORS[0], linewidth=0.7)
                    axes[1].set_title(self._t("频域幅值谱"), fontsize=10)
                    axes[1].set_xlabel(self._t("频率 (Hz)"))
                    axes[1].set_ylabel(self._amp_axis_label("none", s.unit))

                    fp, p = analysis.psd_welch(x, s.fs, win,
                                               nperseg=self.spin_nperseg.value() or None,
                                               overlap_pct=float(self.cmb_overlap.currentText()),
                                               nfft=nfft)
                    axes[2].plot(fp, analysis.psd_to_db(p),
                                 color=MATLAB_COLORS[0], linewidth=0.7)
                    axes[2].set_title(self._t("功率谱密度 PSD (dB/Hz)"), fontsize=10)
                    axes[2].set_xlabel(self._t("频率 (Hz)"))
                    axes[2].set_ylabel("dB/Hz")
                    axes[2].set_ylim(self.spin_ylim.value(), None)

                    fig.tight_layout()
                    out = os.path.join(d, f"{os.path.splitext(s.name)[0]}_{ch}.png")
                    fig.savefig(out, dpi=150)
                    n += 1
            self.statusBar().showMessage(f"批量导出完成，共 {n} 张")
            QtWidgets.QMessageBox.information(self, "完成", f"已导出 {n} 张图片到\n{d}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "导出失败", str(e))


# ----------------------------------------------------------------------------

def _base_dir() -> str:
    """返回程序所在目录：打包成 exe 后是 exe 所在目录，否则是脚本目录。

    PyInstaller 单文件模式下 sys._MEIPASS 是临时解包目录，
    **不能**用来放日志或读写用户文件（退出即删），所以这里用 exe 所在目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _install_crash_log():
    """把未捕获异常写进日志文件。

    打包为 --windowed 后没有控制台，崩溃信息将完全丢失，仅表现为进程直接退出。
    这里把完整 traceback 追加到 VibSpec_error.log，方便定位。
    """
    log_path = os.path.join(_base_dir(), "VibSpec_error.log")

    def _hook(exc_type, exc, tb):
        try:
            import datetime
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 64 + "\n")
                f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def _selftest() -> int:
    """内置自检：不弹出窗口，执行一次核心功能检查，结果写入 VibSpec_selftest.log。

    用途：打包为 exe 后无法查看控制台输出，可执行
        VibSpec.exe --selftest
    以验证该可执行文件在当前机器上能否正常运行，并将结果写入同目录日志。
    退出码 0 = 全部通过，1 = 有失败项。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    log_path = os.path.join(_base_dir(), "VibSpec_selftest.log")
    lines: List[str] = []
    state = {"ok": True}

    def rec(name, cond, detail=""):
        state["ok"] = state["ok"] and bool(cond)
        lines.append(f"[{'PASS' if cond else 'FAIL'}] {name}"
                     + (f"  |  {detail}" if detail else ""))

    def run():
        import tempfile
        import sys as _s
        lines.append(f"Python {_s.version.split()[0]}  /  {_s.executable}")
        lines.append(f"frozen={getattr(_s, 'frozen', False)}  平台={_s.platform}")
        for mod in ("numpy", "scipy", "matplotlib", "PyQt5"):
            try:
                m = __import__(mod)
                rec(f"依赖 {mod}", True, getattr(m, "__version__", "ok"))
            except Exception as e:
                rec(f"依赖 {mod}", False, str(e))
        try:
            from PyEMD import EMD  # noqa: F401
            rec("可选依赖 PyEMD（EMD 链路）", True, "已安装")
            has_emd = True
        except Exception:
            rec("可选依赖 PyEMD（EMD 链路）", True, "未安装（选择该方式时会给出提示，不影响其他功能）")
            has_emd = False

        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        try:
            w = MainWindow()
            w.resize(1200, 700)
            w.show()
            qapp.processEvents()
            rec("主窗口创建", True, w.windowTitle())
        except Exception as e:
            rec("主窗口创建", False, repr(e))
            return

        # 构造双通道临时文件，覆盖导入 -> 绘图 -> 处理链完整流程
        tmpd = tempfile.mkdtemp(prefix="vibspec_selftest_")
        try:
            FS, N = 20000.0, 40000
            t = np.arange(N) / FS
            sig = (1 + 0.8 * np.sin(2 * np.pi * 76.3 * t)) * np.sin(2 * np.pi * 2000 * t)
            p = os.path.join(tmpd, "selftest.mat")
            from scipy.io import savemat
            savemat(p, {"CH03": sig.reshape(-1, 1),
                        "CH04": (0.5 * sig).reshape(-1, 1)})
            w._add_paths([p])
            qapp.processEvents()
            rec("导入 .mat（双通道）", len(w.signals) == 1 and
                len(list(w.signals.values())[0].channels) == 2,
                f"{len(w.signals)} 文件")

            # 拖拽路径解析
            from PyQt5.QtCore import QMimeData, QUrl
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(p)])
            rec("拖拽路径解析", w._paths_from_mime(mime) == [os.path.normpath(p)])

            w.plot_all()
            qapp.processEvents()
            rec("绘图（无处理链）",
                len(w.windows[0]["time"].ax.lines) >= 1,
                f"{len(w.windows[0]['time'].ax.lines)} 条曲线")

            # 三种处理链
            w.chk_pp.setChecked(True)
            qapp.processEvents()
            methods = [(0, "fir"), (1, "svd"), (3, "raw")] + ([(2, "emd")] if has_emd else [])
            for idx, tag in methods:
                w.cmb_pp.setCurrentIndex(idx)
                qapp.processEvents()
                try:
                    pipe = w._apply_chain(
                        list(w.signals.values())[0].channels["CH03"], FS)
                    rec(f"处理链 {tag}", pipe is not None and pipe["up"].size > 0,
                        f"包络 {0 if pipe is None else pipe['up'].size} 点")
                except Exception as e:
                    rec(f"处理链 {tag}", False, repr(e))

            # 包络谱按钮
            w.cmb_pp.setCurrentIndex(0)
            qapp.processEvents()
            try:
                w.show_envelope_spectrum()
                qapp.processEvents()
                rec("包络谱", len(w.windows[0]["freq"].ax.lines) >= 1,
                    f"{len(w.windows[0]['freq'].ax.lines)} 条")
            except Exception as e:
                rec("包络谱", False, repr(e))

            # 时域横轴合理性
            w.chk_pp.setChecked(False)
            qapp.processEvents()
            w.plot_all()
            qapp.processEvents()
            lo, hi = w.windows[0]["time"].ax.get_xlim()
            rec("时域横轴范围合理", 0 <= lo < hi <= 5.0, f"xlim=({lo:.3f}, {hi:.3f})")

            # 删除文件
            w.tree.topLevelItem(0).setSelected(True)
            qapp.processEvents()
            w.on_delete_selected()
            qapp.processEvents()
            rec("删除文件（不动磁盘）",
                len(w.signals) == 0 and os.path.exists(p),
                f"列表 {len(w.signals)} 个，磁盘文件仍在")

            # 黑盒 MAT 判别回归：schema>=3 起波形变量名为 CH01，与示波器通道同名，
            # 类型判别必须依据 capture_* 元数据字段，且采样率取有效值而非默认 20000。
            bb_path = os.path.join(tmpd, "selftest_blackbox.mat")
            eff_fs, cfg_fs = 31039.0, 31580.0
            savemat(bb_path, {
                "CH01": sig.reshape(-1, 1).astype("float32"),
                "capture_fs": np.array([[cfg_fs]]),
                "capture_effective_fs": np.array([[eff_fs]]),
                "capture_rate_warning": "有效采样率 31039.0 Hz 与配置 31580 Hz 偏差 1.71%",
                "rpm": np.array([[1480.0]]),
                "signal_unit": "V",
            })
            bb_type = loader.sniff_type(bb_path)
            rec("黑盒 MAT（变量 CH01）判别", bb_type == "blackbox_mat", bb_type)
            bb = loader.load_any(bb_path)
            rec("黑盒 MAT 采样率取有效值", abs(bb.fs - eff_fs) < 1e-6, f"fs={bb.fs:g}")
            rec("黑盒 MAT 波形/工况解析",
                "CH1" in bb.channels and bb.n_samples == N
                and bb.meta.get("转速(rpm)") == "1480.0",
                f"ch={list(bb.channels)} n={bb.n_samples}")
            rec("黑盒 MAT 采样率偏差提示", any("1.71" in x for x in bb.warnings),
                f"{len(bb.warnings)} 条提示")
            rec("黑盒 MAT 偏差>1% 时解除采样率锁定", bb.fs_locked is False,
                f"fs_locked={bb.fs_locked}")
            rec("示波器 MAT（变量 CH03）未被误判", loader.sniff_type(p) == "scope_mat",
                loader.sniff_type(p))

            # 采样率自洽的黑盒文件应保持锁定，避免误改
            bb2_path = os.path.join(tmpd, "selftest_blackbox_ok.mat")
            savemat(bb2_path, {
                "CH01": sig.reshape(-1, 1).astype("float32"),
                "capture_fs": np.array([[25600.0]]),
                "capture_effective_fs": np.array([[25600.0]]),
            })
            bb2 = loader.load_any(bb2_path)
            rec("黑盒 MAT 采样率自洽时保持锁定",
                bb2.fs_locked is True and abs(bb2.fs - 25600.0) < 1e-6,
                f"fs={bb2.fs:g} locked={bb2.fs_locked}")
        except Exception as e:
            rec("自检过程异常", False, traceback.format_exc())
        finally:
            try:
                import shutil
                shutil.rmtree(tmpd, ignore_errors=True)
            except Exception:
                pass

    try:
        run()
    except Exception:
        state["ok"] = False
        lines.append("自检崩溃：\n" + traceback.format_exc())

    summary = ("全部通过" if state["ok"]
               else f"存在失败项（{sum(1 for x in lines if x.startswith('[FAIL]'))} 项）")
    lines.append("")
    lines.append(f"结论：{summary}")
    text = "\n".join(lines)
    try:
        import datetime
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"VibSpec 自检报告  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write("=" * 60 + "\n" + text + "\n")
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass
    return 0 if state["ok"] else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # 高 DPI 缩放必须在 QApplication 之前设置
    try:
        QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    os.chdir(_base_dir())          # 让文件对话框的默认位置稳定
    _install_crash_log()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("VibSpec")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
