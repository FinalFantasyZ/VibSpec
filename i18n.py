# -*- coding: utf-8 -*-
"""
i18n.py —— VibSpec 界面文案的中英文对照与运行时切换。

设计要点
--------
1. **以中文原文作为键**，英文为其译文。中文界面的成本为零（直接返回原文），
   只有切换到英文时才需要查表。
2. `translate()` 是**幂等**的：传入中文或英文都能得到目标语言的文本，
   因此可以在任意时刻反复切换，不会出现"越切越乱"。
3. 静态文本（控件文字、tooltip、下拉项、菜单）由 `retranslate_widgets()`
   遍历控件树统一替换；动态拼接消息在 app.py 中通过 `MainWindow._t()` 构造。
4. **注意**：凡按 `currentText()` 取值参与计算的控件，不得直接改其显示文本，
   必须改为按索引 / UserRole 取值（见 app.py 中 cmb_window、cmb_norm 的处理）。
"""

from typing import Dict

LANG_ZH = "zh"
LANG_EN = "en"
DEFAULT_LANG = LANG_ZH
LANG_NAMES = {LANG_ZH: "简体中文", LANG_EN: "English"}

# 项目主页（「关于」对话框与英文界面中展示）
PROJECT_HOMEPAGE = "https://github.com/FinalFantasyZ/VibSpec"
PROJECT_AUTHOR = "yang"
APP_TITLE = "VibSpec"
APP_TITLE_ZH = "VibSpec —— 振动信号分析器"
APP_TITLE_EN = "VibSpec — Vibration Signal Analyzer"
APP_VERSION = "1.1.1"


# ---------------------------------------------------------------------------
# 中文 → 英文对照表
# ---------------------------------------------------------------------------
ZH2EN: Dict[str, str] = {
    # ---- 文件操作 ----
    "导入文件": "Import Files",
    "导入文件夹": "Import Folder",
    "全选": "Select All",
    "全不选": "Deselect All",
    "删除选中": "Remove Selected",
    "清空": "Clear All",
    "文件 / 通道": "File / Channel",
    "信息": "Info",
    "选中文件后在此显示工况与提示": "Select a file to view its details",
    "打开文件对话框，可一次选择多个 .csv / .mat 数据文件。\n"
    "也可以直接把文件或整个文件夹**拖进窗口**任意位置导入。":
        "Open a file dialog; multiple .csv / .mat files can be selected at once.\n"
        "You can also drag files or a whole folder anywhere onto the window.",
    "选择一个文件夹，递归扫描其中所有 .csv / .mat 文件并全部导入。":
        "Pick a folder; every .csv / .mat file inside (recursively) is imported.",
    "勾选列表中的所有文件与通道（用于同时绘图）。":
        "Check every file and channel in the list (for plotting them together).",
    "取消勾选所有文件与通道，但保留在列表中。":
        "Uncheck all files and channels but keep them in the list.",
    "从列表中移除选中的文件（快捷键 Delete）。\n只从软件里移出，**不会删除磁盘上的原始数据文件**。":
        "Remove the selected files from the list (shortcut: Delete).\n"
        "This only unloads them from the app; **the files on disk are kept**.",
    "移除列表中的全部文件，并清空所有绘图区。":
        "Remove all files from the list and clear every plot.",
    "勾选文件/通道决定画什么。\n单选一行后按 Delete 可删除该文件；右键可批量删除。\n"
    "鼠标悬停在文件名上会显示工况信息与提示。":
        "Check files/channels to plot them.\n"
        "Select a row and press Delete to unload that file; right-click for batch actions.\n"
        "Hover over a file name to see its condition metadata and warnings.",
    "显示当前选中文件的类型、采样率、点数、时长、通道与工况。":
        "Shows type, sample rate, sample count, duration, channels and condition "
        "of the selected file.",

    # ---- 绘图标签页 ----
    "时域波形": "Time Waveform",
    "频域（幅值谱）": "Frequency (Amplitude)",
    "dB 功率谱（PSD）": "dB Power Spectrum (PSD)",

    # ---- 通道与窗口 ----
    "通道与窗口分配": "Channels & Windows",
    "双击通道行即可在上/下窗口间切换（右键可批量）":
        "Double-click a channel row to move it between windows (right-click to batch).",
    "双击一行 → 在上/下窗口之间切换；\n右键 → 批量分配，或一键反转全部上/下；\n"
    "行首 [上]/[下] 表示当前所在窗口，蓝色=上窗口、橙色=下窗口。":
        "Double-click a row to switch its window;\n"
        "right-click to assign in batch or reverse all assignments;\n"
        "the [上]/[下] prefix shows the current window — blue = upper, orange = lower.",
    "全部→上": "All → Upper",
    "全部→下": "All → Lower",
    "把所有通道一次性分配到上窗口。": "Assign every channel to the upper window.",
    "把所有通道一次性分配到下窗口。": "Assign every channel to the lower window.",
    "显示全部通道": "Show All Channels",
    "勾选：把所有导入通道都显示在右侧列表中；\n取消：只列出当前在文件树里勾选了的通道。":
        "Checked: list every imported channel.\n"
        "Unchecked: only list channels currently checked in the file tree.",
    "决定每个通道画到哪个窗口。\n双击列表行即可切换；右键可批量分配或一键反转。\n"
    "[上]=蓝色 画到上窗口，[下]=橙色 画到下窗口。":
        "Decides which window each channel is drawn in.\n"
        "Double-click to switch; right-click to batch-assign or reverse.\n"
        "[上] = blue → upper window, [下] = orange → lower window.",

    # ---- 归一化 ----
    "归一化": "Normalization",
    "不归一化（原始物理量）": "None (raw physical units)",
    "除以各自 RMS（按有效值归一）": "Divide by RMS",
    "除以各自峰值（按峰值归一）": "Divide by peak",
    "Z-score（去均值后除标准差）": "Z-score (mean-removed, ÷ std)",
    "不同采集链路的增益可能相差几十~上千倍，不归一化时小信号会被压成直线。\n"
    "归一化**只影响绘图显示**，导出的图片与 CSV 始终是原始物理量。":
        "Gain may differ by orders of magnitude across acquisition chains; without "
        "normalization a weak signal flattens to a line.\n"
        "Normalization **affects the display only** — exported images and CSVs always "
        "carry the raw physical quantities.",
    "不同采集链路增益差几十~上千倍时，打开归一化才能在同一窗口看清各自形状。\n"
    "归一化只影响绘图显示，不改变导出的物理量数据。":
        "When gains differ greatly, normalization is what lets you compare shapes in one "
        "window.\nIt affects the display only and never changes exported data.",

    # ---- 预处理链 ----
    "信号预处理链": "Signal Preprocessing Chain",
    "启用处理链": "Enable Chain",
    "启用包络分析链路：信号先按所选方式预处理，再取包络做谱分析。\n"
    "时域图会同时画出处理后的信号（实线）与它的包络（虚线）。":
        "Enables the envelope-analysis chain: the signal is preprocessed first, then its "
        "envelope is spectrum-analyzed.\nThe time plot draws both the processed signal "
        "(solid) and its envelope (dashed).",
    "方式": "Method",
    "选择包络分析的前置处理方式，见下拉框各项说明。":
        "Choose the preprocessing method for envelope analysis; see the dropdown details.",
    "高通滤波": "High-pass filter",
    "SVD 重构": "SVD reconstruction",
    "EMD 首个 IMF": "EMD first IMF",
    "直接取包络（不滤波）": "Envelope only (no filter)",
    "包络分析的前置处理方式，作用是抑制低频干扰、突出高频冲击成分：\n"
    "• 高通滤波 —— 滤掉截止频率以下的低频分量，保留高频冲击（最常用）；\n"
    "• SVD 重构 —— 用奇异值分解重构信号的主要成分，抑制宽带噪声；\n"
    "• EMD 首个 IMF —— 经验模态分解取最高频的本征模态，分离冲击与趋势；\n"
    "   该方式需额外安装 EMD-signal（pip install EMD-signal）；\n"
    "• 直接取包络 —— 不做前置处理，作为对照基准。\n"
    "选择建议：一般先用高通滤波；若噪声明显，再与 SVD 的结果比较。":
        "Preprocessing suppresses low-frequency interference and highlights high-frequency "
        "impacts:\n"
        "• High-pass — removes components below the cutoff, keeps impacts (most common);\n"
        "• SVD — reconstructs the dominant components via SVD to suppress broadband noise;\n"
        "• EMD first IMF — takes the highest-frequency intrinsic mode, separating impacts "
        "from trend;\n   requires the extra package EMD-signal (pip install EMD-signal);\n"
        "• Envelope only — no preprocessing, for reference.\n"
        "Suggestion: start with high-pass; if noise is strong, compare against SVD.",
    "FIR 截止": "FIR cutoff",
    "高通滤波器把该频率以下的成分滤掉。":
        "The high-pass filter removes components below this frequency.",
    "FIR 阶数": "FIR order",
    "滤波器阶数越大，过渡带越窄但边界效应也越长。":
        "A higher order narrows the transition band but lengthens edge effects.",
    "高通滤波的截止频率（默认 500 Hz），截止点为 -6 dB：\n"
    "低于该频率的分量被衰减，高于该频率的分量基本原样通过。\n"
    "取值应高于转频与常见低频干扰、低于待分析的冲击频段；\n"
    "必须小于采样率的一半（Nyquist）。":
        "High-pass cutoff (default 500 Hz), a -6 dB point:\n"
        "components below it are attenuated, above it pass essentially unchanged.\n"
        "Pick a value above the shaft rate and common low-frequency interference, and "
        "below the impact band of interest;\nit must stay under half the sample rate "
        "(Nyquist).",
    "滤波器阶数（默认 180）。阶数越高，过渡带越窄、阻带衰减越好，\n"
    "但边界效应也越长；零相位滤波要求信号长度 > 3×阶数，否则报错。":
        "Filter order (default 180). Higher order = narrower transition band and better "
        "stop-band attenuation,\nbut longer edge effects; zero-phase filtering requires "
        "signal length > 3×order, else it errors out.",
    "傅里叶谱也用处理后的信号": "Apply chain to Fourier spectra too",
    "勾选：幅值谱/PSD 基于处理后信号；\n不勾选：只把处理结果画在时域，频域仍用原始信号。":
        "Checked: amplitude spectrum / PSD are computed from the processed signal.\n"
        "Unchecked: the chain is shown in the time domain only; the frequency domain "
        "still uses the raw signal.",
    "包络谱": "Envelope spectrum",
    "对信号包络做 FFT，得到包络谱。\n"
    "轴承的冲击会调制出高频载波，其包络谱在故障特征频率处出现峰值，\n"
    "因此包络谱是定位轴承故障特征频率的常用手段。\n"
    "横轴为 0 ~ fs 的完整谱，纵轴为幅值。":
        "FFT of the signal envelope.\n"
        "Bearing impacts modulate a high-frequency carrier, so the envelope spectrum "
        "peaks at the fault characteristic frequencies —\nthe standard way to locate "
        "bearing faults.\nThe horizontal axis spans the full 0 ~ fs range; vertical is "
        "amplitude.",
    "参与分析的样本数（默认 16384），取信号前 Num 个点做包络谱，\n"
    "0 表示使用全部样本。段越长频率分辨率越高，计算量也越大。":
        "Number of samples used (default 16384): the first Num points go into the envelope "
        "spectrum;\n0 means use all samples. Longer segments give finer frequency "
        "resolution at a higher cost.",
    "包络谱显示的上限频点 Lfr（默认 800）。\n"
    "频率上限 = (Lfr-1)×fs/Num；以 fs=20000、Num=16384 计，800 点约到 975 Hz。\n"
    "轴承故障特征频率通常集中在低频段，800 左右即可覆盖；0 表示显示全频段。":
        "Upper frequency bin Lfr for the envelope spectrum (default 800).\n"
        "Frequency limit = (Lfr-1)×fs/Num; with fs=20000 and Num=16384, bin 800 ≈ 975 Hz.\n"
        "Bearing fault frequencies usually sit low, so ~800 covers them; 0 shows the full "
        "band.",
    "显示包络谱": "Show Envelope Spectrum",
    "把当前勾选信号的包络谱画到上窗口的频域页":
        "Plot the envelope spectrum of the checked signals in the upper window's "
        "frequency tab",

    # ---- 参数面板 ----
    "参数": "Parameters",
    "采样率 fs": "Sample rate fs",
    "采样率 fs（Hz）。时间轴换算关系为：时间 = 点数 / fs。\n"
    "• 带采样率元数据的 CSV / MAT：直接读取文件记录的真实值；\n"
    "   记录值与配置值偏差 ≤1% 时锁定，偏差较大时自动解锁，便于手动标定；\n"
    "• 不含采样率字段的 MAT：默认 20000 仅为占位，需人工确认。\n"
    "注意：修改前需先在左侧列表选中目标文件（Ctrl/Shift 可多选），\n"
    "   只会改选中的文件，不会影响其它文件。":
        "Sample rate fs (Hz). Time axis: time = samples / fs.\n"
        "• CSV / MAT carrying a sample-rate field: the recorded value is read directly; "
        "it stays locked while within 1% of the configured value and unlocks otherwise, "
        "so you can calibrate it manually;\n"
        "• MAT without a sample-rate field: 20000 is only a placeholder and must be "
        "confirmed by hand.\n"
        "Note: select the target file(s) in the list first (Ctrl/Shift for multiple); "
        "only the selection is changed.",
    "窗函数": "Window function",
    "汉宁 (hann)": "Hann",
    "矩形 (boxcar)": "Boxcar",
    "汉明 (hamming)": "Hamming",
    "布莱克曼 (blackman)": "Blackman",
    "平顶 (flattop)": "Flattop",
    "FFT / Welch 使用的窗函数。\n"
    "• 汉宁(hann)：通用首选，旁瓣低，适合看连续谱；\n"
    "• 矩形(boxcar)：等于不加窗，主瓣最窄但泄漏大；\n"
    "• 平顶(flattop)：幅值读数最准（测幅值优先），但主瓣最宽；\n"
    "• 汉明/布莱克曼：旁瓣更低，代价是主瓣更宽。":
        "Window used by FFT / Welch.\n"
        "• Hann: general-purpose default, low sidelobes, good for continuous spectra;\n"
        "• Boxcar: no window — narrowest main lobe, but heavy leakage;\n"
        "• Flat-top: most accurate amplitude readings, widest main lobe;\n"
        "• Hamming / Blackman: even lower sidelobes at the cost of a wider main lobe.",
    "PSD 分段 nperseg": "PSD segment nperseg",
    "Welch 功率谱的分段长度（每个子段的点数），0 表示自动。\n"
    "分段越短 → 频率分辨率越低、平均次数越多、谱线越平滑；\n"
    "分段越长 → 分辨率越高，但方差增大（谱线起伏更明显）。":
          "Welch segment length in samples; 0 = automatic.\n"
        "Shorter segments → coarser resolution but more averages and a smoother curve;\n"
        "longer segments → finer resolution with more variance (more visible ripple).",
    "FFT 点数 nfft": "FFT size nfft",
    "FFT 点数。0 表示自动取「数据长度」（幅值谱）或「分段长度」（PSD）。\n"
    "补零点（nfft > 数据长度）能让谱峰更平滑、峰值位置看得更细，\n"
    "但不会真正提高频率分辨率。":
        "FFT size. 0 = automatic (data length for the amplitude spectrum, segment length "
        "for PSD).\nZero-padding (nfft > data length) smooths peaks and shows their position "
        "more finely,\nbut does not truly improve frequency resolution.",
    "PSD 重叠 %": "PSD overlap %",
    "Welch 相邻分段的交叠比例。50% 是常用折中：\n"
    "交叠越大，参与平均的段数越多、谱越平滑，但计算量越大。":
        "Overlap between adjacent Welch segments. 50% is the usual compromise:\n"
        "more overlap means more segments averaged and a smoother spectrum, at higher "
        "cost.",
    "时域起点 t0": "Time start t0",
    "时域波形从第几秒开始画（对应样本索引 = t0 × fs）。\n"
    "用于跳过开头的过渡段或冲击段。0 表示从起点开始。":
        "Start time of the time-domain plot (sample index = t0 × fs).\n"
        "Use it to skip an initial transient or impact. 0 starts at the beginning.",
    "时域时长": "Time span",
    "时域波形显示多长时间。默认 0.05 s，避免整段波形重叠难以分辨。\n"
    "填 0 表示显示全程。":
        "How much of the waveform to show. Default 0.05 s keeps the trace readable.\n"
        "0 shows the full record.",
    "频率上限": "Max frequency",
    "频域两张图的横轴上限。0 表示自动（取 fs/2，即 Nyquist）。\n"
    "如需放大低频段（观察轴承故障特征频率），填入较小值。":
        "Upper limit of both frequency plots. 0 = automatic (fs/2, i.e. Nyquist).\n"
        "Enter a smaller value to zoom into the low band where bearing faults live.",
    "dB 下限": "dB floor",
    "dB 功率谱纵轴的下限（dB/Hz）。\n"
    "调高（如 -80）可截去噪声基线，仅保留强峰；调低（如 -160）可观察弱成分。":
        "Lower limit of the dB power spectrum (dB/Hz).\n"
        "Raising it (e.g. -80) trims the noise floor and keeps strong peaks; lowering it "
        "(e.g. -160) reveals weak components.",
    "去均值": "Remove DC",
    "做谱分析前先减去直流分量。\n"
    "带直流偏置的信号（IEPE 类常约 0.7 V）若不去除，会在 0 Hz 处产生极大的直流峰，\n"
    "将有用的交流成分压制，因此默认勾选。":
        "Subtract the DC component before spectral analysis.\n"
        "A DC-biased signal (typically ~0.7 V for IEPE) would otherwise produce a huge "
        "peak at 0 Hz that swamps the useful AC content, hence it is on by default.",
    "频率轴对数坐标": "Log frequency axis",
    "频域横轴改用对数刻度，便于同时看清低频细节和高频成分。":
        "Use a logarithmic frequency axis to see low-frequency detail and high-frequency "
        "content at once.",

    # ---- 操作 ----
    "操作": "Actions",
    "绘制 / 刷新": "Plot / Refresh",
    "按当前所有参数重新计算并绘制上/下两个窗口。\n"
    "（改动归一化、处理链、通道归属时通常会自动重绘，\n"
    " 修改窗函数 / nperseg / 重叠等参数后需手动触发。）":
        "Recompute and redraw both windows with the current settings.\n"
        "(Changing normalization, the chain or channel assignment usually redraws "
        "automatically;\nafter editing window / nperseg / overlap, trigger it manually.)",
    "导出图片": "Export Image",
    "把**当前活动窗口的当前标签页**导出为 PNG / PDF / SVG（200 dpi）。":
        "Export the **current tab of the active window** as PNG / PDF / SVG (200 dpi).",
    "导出数据": "Export Data",
    "把当前图的谱线数据导出为 CSV，内容为**原始物理量**，不受归一化影响。":
        "Export the current plot's spectral data to CSV — **raw physical quantities**, "
        "unaffected by normalization.",
    "批量导出全部图片": "Export All Images",
    "对每个通道各导出一张三联图（时域 + 幅值谱 + PSD），方便归档。":
        "Export a three-panel figure (time + amplitude + PSD) for every channel, handy "
        "for archiving.",

    # ---- 时域指标 ----
    "时域指标": "Time-domain Metrics",
    "绘制后显示": "Shown after plotting",
    "前几条曲线的时域统计量（按窗口分别列出）。\n"
    "峰值/峰峰值按**原始信号（含直流）**计算；\n"
    "RMS、方差、峭度、峰值因子等在**去均值后**计算 —— 否则直流分量\n"
    "会使 RMS 显著偏高、峭度严重失真。\n"
    "统计量始终基于完整信号，与归一化开关无关。":
        "Time-domain statistics of the leading curves, listed per window.\n"
        "Peak/peak-to-peak use the **raw signal including DC**;\n"
        "RMS, variance, kurtosis and crest factor are computed **after removing the "
        "mean** — otherwise DC\ninflates RMS and badly distorts kurtosis.\n"
        "Statistics always come from the full signal and ignore the normalization switch.",

    # ---- 运行时消息 ----
    "就绪": "Ready",
    "就绪：请导入数据文件或文件夹": "Ready — import a data file or folder",
    "松开鼠标即可导入这些文件 / 文件夹…": "Release to import these files / folders…",
    "选择数据文件": "Select data files",
    "选择数据文件夹": "Select a data folder",
    "选择导出目录": "Select export folder",
    "部分文件导入失败": "Some files failed to import",
    "已清空": "Cleared",
    "提示": "Notice",
    "没有勾选任何文件": "No file is checked",
    "没有可绘制的包络谱": "No envelope spectrum to plot",
    "绘图失败": "Plotting failed",
    "请先勾选文件": "Please check a file first",
    "当前图没有内容，请先绘制": "The current plot is empty; plot something first",
    "导出图像": "Export image",
    "导出谱数据": "Export spectrum data",
    "导出失败": "Export failed",
    "完成": "Done",
    "请先在左上角文件列表里选中要删除的文件（Ctrl/Shift 可多选），\n"
    "再按「删除选中」或 Delete 键。":
        "Select the file(s) to remove in the upper-left list first (Ctrl/Shift for "
        "multiple),\nthen click \"Remove Selected\" or press Delete.",
    "请先在左侧「文件/通道」列表里选中要改采样率的文件，再改这个值（Ctrl/Shift 可多选）":
        "Select the target file(s) in the left \"File / Channel\" list before changing "
        "this value (Ctrl/Shift for multiple).",
    "选中的文件采样率已锁定或未导入，未做修改":
        "The selected file's sample rate is locked or not loaded; nothing was changed.",
    "已反转全部通道的上/下窗口归属":
        "Reversed the window assignment of every channel.",
    "只保留选中，删除其余": "Keep selected, remove the rest",
    "展开全部通道": "Expand all channels",
    "折叠全部通道": "Collapse all channels",
    "全部反转上/下": "Reverse all assignments",

    # ---- 关于 / 语言 ----
    "关于": "About",
    "关于 VibSpec": "About VibSpec",
    "项目主页": "Project homepage",
    "语言 / Language": "Language",
    "打开项目主页": "Open project homepage",
    "作者": "Author",
    "版本": "Version",
    "项目主页：": "Homepage:  ",
    "振动信号分析器": "Vibration Signal Analyzer",
    "本软件用于振动采样信号的时域与频域分析，兼容 CSV 与 MATLAB MAT 两类数据文件。":
        "A desktop tool for time- and frequency-domain analysis of vibration records. "
        "It reads CSV and MATLAB MAT data files.",

    # ---- 图表 ----
    "时间 (s)": "Time (s)",
    "频率 (Hz)": "Frequency (Hz)",
    "幅值 (": "Amplitude (",
    "功率谱密度 (dB/Hz)": "PSD (dB/Hz)",
    "频域幅值谱（单边 FFT）": "Amplitude spectrum (one-sided FFT)",
    "功率谱密度 Welch PSD": "Power spectral density (Welch PSD)",
    "频域幅值谱": "Amplitude spectrum",
    "CSV（表头格式）": "CSV (header)",
    "MAT（含元数据）": "MAT (with metadata)",
    "MAT（纯通道）": "MAT (channels only)",
    "（原始）": " (raw)",
    "包络up": "Env(up)",
    "时域": "Time",
    "功率谱密度 PSD (dB/Hz)": "Power spectrum (Welch PSD)",
    "幅值 |FFT(包络)|（未归一化，已跳过直流）":
        "Amplitude |FFT(envelope)| (unnormalized, DC skipped)",
    "[上窗口] 包络谱 Envelope Spectrum · ": "[Upper] Envelope Spectrum · ",
    "（可开启归一化解决重叠）": " (enable normalization to separate overlaps)",
    "· 归一化=": " · norm=",
    "· 处理链=": " · chain=",
    "上": "Upper",
    "下": "Lower",
}

EN2ZH: Dict[str, str] = {v: k for k, v in ZH2EN.items()}


def translate(text: str, lang: str) -> str:
    """把界面文案翻到目标语言。

    幂等：无论输入是中文还是英文，只要表中有对应项，都会得到目标语言的文本；
    查不到时原样返回（通常是用户数据或尚未纳入翻译的字符串）。
    """
    if not text:
        return text
    if lang == LANG_EN:
        return ZH2EN.get(text, text)
    return EN2ZH.get(text, text)


def app_title(lang: str) -> str:
    return APP_TITLE_EN if lang == LANG_EN else APP_TITLE_ZH


def retranslate_widgets(root, lang: str) -> int:
    """遍历控件树，把静态文本、tooltip、下拉项、菜单项切到目标语言。

    返回被改写的项数（便于自检与排查）。只处理"文本"类属性，
    不触碰任何按索引 / UserRole 取值的逻辑，因此对计算链路无影响。
    """
    from PyQt5 import QtWidgets

    changed = 0

    def _set_text(w):
        nonlocal changed
        try:
            txt = w.text()
        except Exception:
            return
        new = translate(txt, lang)
        if new != txt:
            w.setText(new)
            changed += 1

    widgets = [root] + root.findChildren(QtWidgets.QWidget)
    for w in widgets:
        if isinstance(w, (QtWidgets.QLabel, QtWidgets.QPushButton,
                          QtWidgets.QCheckBox, QtWidgets.QGroupBox)):
            _set_text(w)
        elif isinstance(w, QtWidgets.QComboBox):
            for i in range(w.count()):
                txt = w.itemText(i)
                new = translate(txt, lang)
                if new != txt:
                    w.setItemText(i, new)
                    changed += 1
        elif isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit,
                            QtWidgets.QTextEdit)):
            ph = w.placeholderText()
            new = translate(ph, lang)
            if new != ph:
                w.setPlaceholderText(new)
                changed += 1

        # tooltip（所有控件都可能带）
        try:
            tt = w.toolTip()
        except Exception:
            continue
        if tt:
            new = translate(tt, lang)
            if new != tt:
                w.setToolTip(new)
                changed += 1

    return changed
