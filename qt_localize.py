# -*- coding: utf-8 -*-
"""
qt_localize.py —— 把 matplotlib 内置对话框的英文界面本地化为中文。

涉及两个对话框（均由 matplotlib 提供，文案硬编码为英文，QTranslator 无法覆盖）：

  1. 图形参数（Figure options）—— 工具栏「编辑坐标轴 / 曲线参数」按钮；
  2. 子图调整（Subplot tool）  —— 工具栏「调整子图」按钮。

做法：对二者做**猴子补丁**，在对话框构造完成后按其控件文本做一次映射替换。
同时移除标题栏上的「?」（上下文帮助）按钮 —— matplotlib 未实现该帮助内容，
点击无任何反应，保留只会造成误导。

语言状态由 app.py 通过 `set_language()` 同步；仅当语言为中文时才做替换。
"""

from typing import Dict

_current_lang = "zh"

# 英文 → 中文。键为控件上出现的**原文**（含 HTML 标记者原样保留）
DIALOG_ZH: Dict[str, str] = {
    # 图形参数 —— 窗口与分组
    "Figure options": "图形参数",
    "Axes": "坐标轴",
    "Curves": "曲线",
    "Images, etc.": "图像等",
    # 图形参数 —— 坐标轴字段
    "Title": "标题",
    "Min": "最小值",
    "Max": "最大值",
    "Label": "标签",
    "Scale": "刻度",
    "(Re-)Generate automatic legend": "（重新）生成自动图例",
    # 图形参数 —— 曲线字段
    "Line style": "线型",
    "Draw style": "绘制样式",
    "Width": "线宽",
    "Color (RGBA)": "颜色 (RGBA)",
    "Style": "样式",
    "Size": "大小",
    "Face color (RGBA)": "填充色 (RGBA)",
    "Edge color (RGBA)": "边线色 (RGBA)",
    "<b>Line</b>": "<b>线条</b>",
    "<b>Marker</b>": "<b>标记</b>",
    # 图形参数 —— 图像 / 色彩映射字段
    "Colormap": "色图",
    "Min. value": "最小值",
    "Max. value": "最大值",
    "Interpolation": "插值方式",
    "Interpolation stage": "插值阶段",
    # 子图调整
    "SubplotTool": "子图调整",
    "Borders": "边距",
    "Spacings": "间距",
    "top": "上",
    "bottom": "下",
    "left": "左",
    "right": "右",
    "hspace": "水平间距",
    "wspace": "垂直间距",
    "Export values": "导出数值",
    "Tight layout": "紧凑布局",
    "Reset": "重置",
    "Close": "关闭",
    # 通用按钮
    "OK": "确定",
    "Cancel": "取消",
    "Apply": "应用",
    "&OK": "确定",
    "&Cancel": "取消",
}


# ---------------------------------------------------------------------------
# 工具栏按钮
# ---------------------------------------------------------------------------
# 结构为 (按钮文字, 提示, 图标名, 回调方法名)，顺序必须与 matplotlib 一致
# （基类 toolitems 再插入 Customize）。图标名与回调名不可翻译。
#
# 注意：这里**故意去掉了 Home / Back / Forward 三个按钮**。
# VibSpec 每次绘图都会 fig.clear() 重建坐标轴，而 matplotlib 的导航历史
# (NavigationToolbar2._nav_stack) 里保存的是重建前的坐标轴对象，
# 因此这三个按钮点下去不会产生任何效果（已实测）。保留只会误导用户；
# 缩放后如需复原，重新点「绘制 / 刷新」即可。
TOOLITEMS_EN = (
    ('Pan', 'Left button pans, Right button zooms\n'
            'x/y fixes axis, CTRL fixes aspect', 'move', 'pan'),
    ('Zoom', 'Zoom to rectangle\nx/y fixes axis', 'zoom_to_rect', 'zoom'),
    ('Subplots', 'Configure subplots', 'subplots', 'configure_subplots'),
    ('Customize', 'Edit axis, curve and image parameters',
     'qt4_editor_options', 'edit_parameters'),
    (None, None, None, None),
    ('Save', 'Save the figure', 'filesave', 'save_figure'),
)

TOOLITEMS_ZH = (
    ('平移', '左键平移，右键缩放\nx/y 固定单轴，CTRL 固定纵横比', 'move', 'pan'),
    ('缩放', '缩放到矩形区域\nx/y 固定单轴', 'zoom_to_rect', 'zoom'),
    ('子图', '调整子图参数', 'subplots', 'configure_subplots'),
    ('自定义', '编辑坐标轴、曲线与图像参数',
     'qt4_editor_options', 'edit_parameters'),
    (None, None, None, None),
    ('保存', '保存当前图形', 'filesave', 'save_figure'),
)

# 需要从工具栏中剔除的失效按钮（按 tooltip 首行识别，兼容中英文两种状态）
DEAD_TOOL_TIPS = {
    "Reset original view", "Back to previous view", "Forward to next view",
    "恢复原始视图", "后退到上一个视图", "前进到下一个视图",
}


def strip_dead_nav_buttons(root) -> int:
    """移除工具栏中失效的 Home / Back / Forward 按钮。

    这三个按钮在 VibSpec 中不起作用（坐标轴每次绘图都会重建，导航历史随之失效），
    对**已创建**的工具栏也做一次清理。返回移除的按钮数。
    """
    try:
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
    except Exception:
        return 0

    removed = 0
    for tb in root.findChildren(NavigationToolbar2QT):
        for act in list(tb.actions()):
            if act.isSeparator():
                continue
            tip = (act.toolTip() or "").split("\n")[0].strip()
            if tip in DEAD_TOOL_TIPS:
                tb.removeAction(act)
                removed += 1
    return removed


def toolitems_for(lang: str):
    return TOOLITEMS_ZH if lang == "zh" else TOOLITEMS_EN


def apply_toolbar_language(root, lang: str) -> int:
    """就地更新已存在的 matplotlib 工具栏按钮文字与提示（语言切换即时生效）。"""
    try:
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
    except Exception:
        return 0

    items = [it for it in toolitems_for(lang) if it[0] is not None]
    changed = 0
    for tb in root.findChildren(NavigationToolbar2QT):
        acts = [a for a in tb.actions() if not a.isSeparator()]
        for act, item in zip(acts, items):
            if act.text() != item[0] or act.toolTip() != item[1]:
                act.setText(item[0])
                act.setToolTip(item[1])
                changed += 1
    return changed


def set_language(code: str):
    """由主窗口在语言切换时调用。"""
    global _current_lang
    _current_lang = code


def localize_dialog(dlg) -> int:
    """把对话框上的英文文案换成中文，并移除标题栏的「?」按钮。

    只在当前语言为中文时生效；返回被改写的项数（便于自检）。
    """
    if _current_lang != "zh" or dlg is None:
        return 0

    from PyQt5 import QtCore, QtWidgets

    changed = 0

    # 「?」是 QDialog 默认带入的上下文帮助按钮，matplotlib 并未实现其内容，
    # 点击无反应，故显式关闭。
    # 注意：setWindowFlag 会**隐藏已显示的窗口**，因此本函数应在对话框
    # show() 之前调用（见 install() 中挂在 FormDialog.__init__ 上的做法）；
    # 万一在显示后调用，这里负责把窗口重新显示出来，避免"闪一下就消失"。
    was_visible = False
    try:
        was_visible = dlg.isVisible()
    except Exception:
        pass
    try:
        dlg.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
    except Exception:
        pass
    if was_visible:
        try:
            if not dlg.isVisible():
                dlg.show()
        except Exception:
            pass

    # 子图调整对话框未设置标题，会沿用应用名，这里补一个明确的中文标题
    try:
        if dlg.objectName() == "SubplotTool" and dlg.windowTitle() != DIALOG_ZH["SubplotTool"]:
            dlg.setWindowTitle(DIALOG_ZH["SubplotTool"])
            changed += 1
    except Exception:
        pass

    title = dlg.windowTitle()
    if title in DIALOG_ZH:
        dlg.setWindowTitle(DIALOG_ZH[title])
        changed += 1

    for w in dlg.findChildren(QtWidgets.QWidget):
        if isinstance(w, QtWidgets.QGroupBox):
            # 分组框用 title() / setTitle()，不是 text()
            txt = w.title()
            if txt in DIALOG_ZH:
                w.setTitle(DIALOG_ZH[txt])
                changed += 1
        elif isinstance(w, (QtWidgets.QLabel, QtWidgets.QPushButton,
                            QtWidgets.QCheckBox)):
            txt = w.text()
            if txt in DIALOG_ZH:
                w.setText(DIALOG_ZH[txt])
                changed += 1
        elif isinstance(w, QtWidgets.QDialogButtonBox):
            for std, key in ((QtWidgets.QDialogButtonBox.Ok, "OK"),
                             (QtWidgets.QDialogButtonBox.Cancel, "Cancel"),
                             (QtWidgets.QDialogButtonBox.Apply, "Apply")):
                btn = w.button(std)
                if btn is not None:
                    btn.setText(DIALOG_ZH[key])
                    changed += 1

    return changed


def install(lang: str = None):
    """接入猴子补丁：此后再打开 matplotlib 对话框即自动中文化，
    并按语言设置工具栏按钮文字。

    幂等 —— 重复调用不会叠加补丁；重复设置 toolitems 无副作用。
    """
    global _current_lang
    if lang:
        _current_lang = lang

    from matplotlib.backends.qt_editor import _formlayout
    from matplotlib.backends.backend_qt import SubplotToolQt

    try:
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        # 工具栏文字在工具栏**创建时**从类属性读取，必须在创建之前替换
        NavigationToolbar2QT.toolitems = toolitems_for(_current_lang)
    except Exception:
        pass

    if getattr(_formlayout.FormDialog.__init__, "_vibspec_patched", False):
        return

    # 关键：图形参数对话框必须在 show() **之前**完成本地化。
    # setWindowFlag 会隐藏已显示的窗口；若等 fedit() 返回后再改窗口标志，
    # 用户看到的就是"点一下闪一下就消失"。因此这里挂在 FormDialog.__init__
    # 上（fedit 内部的 dialog.show() 在其之后执行）。
    orig_form_init = _formlayout.FormDialog.__init__

    def form_init(self, *args, **kwargs):
        orig_form_init(self, *args, **kwargs)
        localize_dialog(self)

    form_init._vibspec_patched = True
    _formlayout.FormDialog.__init__ = form_init

    orig_init = SubplotToolQt.__init__

    def init(self, targetfig, parent):
        orig_init(self, targetfig, parent)
        localize_dialog(self)

    init._vibspec_patched = True
    SubplotToolQt.__init__ = init
