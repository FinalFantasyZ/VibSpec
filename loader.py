# -*- coding: utf-8 -*-
"""
loader.py —— 振动数据文件解析模块

支持三种来源（格式依据实际采集文件确定）：

1. CSV（带表头的文本格式，如 "sample.csv"）
     第 1 行:  fs, fs, n_cols, ?, ?
     第 2 行:  ch0_ymax, ch1_ymax, ...      通道显示上限（V）
     第 3 行:  ch0_y0,   ch1_y0,   ...      通道基线显示值
     其后为数据行，逗号分隔。
     注意：数据区的第 1 行（全 0）与第 2 行是导出器写入的哨兵行，须予以剔除。

2. MAT（含采集参数元数据，如 "record.mat"，MATLAB v5 格式）
     关键变量 signal (1xN float64) 或 CH01 (Nx1 single)，单位为 V。
     变量名随导出 schema 变化：schema<=2 为 signal，schema>=3 改为 CH01
     （与纯通道 MAT 的 CHxx 同形，便于 MATLAB 侧统一 plot），本模块两者都识别。
     capture_fs / capture_effective_fs 给采样率；
     rpm / fault_type_cn / severity_cn / label_cn 给工况与标签。

3. MAT（仅含通道变量，如 "scope.mat"，MATLAB v5 格式）
     变量 CH03 / CH04，各 (N x 1) float32，单位 V。
     文件内不含采样率字段，需界面上手动指定（默认 20000 Hz）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.io as sio


# ----------------------------------------------------------------------------
# 数据模型
# ----------------------------------------------------------------------------

@dataclass
class SignalSet:
    """一个文件解析后得到的多通道信号集合。"""

    path: str
    name: str                      # 文件基名（用于列表显示）
    source_type: str               # 'csv' | 'blackbox_mat' | 'scope_mat'
    channels: Dict[str, np.ndarray] = field(default_factory=dict)  # 通道名 -> 时域数组(V)
    fs: float = 20000.0            # 采样率 Hz
    fs_locked: bool = False        # True 表示采样率取自文件本身，不建议修改
    unit: str = "V"
    meta: Dict[str, str] = field(default_factory=dict)   # 工况/标签等元信息
    warnings: List[str] = field(default_factory=list)    # 解析过程中的提示

    @property
    def n_samples(self) -> int:
        if not self.channels:
            return 0
        return min(len(v) for v in self.channels.values())

    @property
    def duration(self) -> float:
        return self.n_samples / self.fs if self.fs else 0.0

    def summary_line(self) -> str:
        return (f"{self.source_type} | fs={self.fs:g}Hz | "
                f"{len(self.channels)}ch | N={self.n_samples} | "
                f"T={self.duration:.3f}s")


# ----------------------------------------------------------------------------
# 格式判别常量
# ----------------------------------------------------------------------------

# 通道变量名模式（CH01 / CH03 / CH04 …）
_SCOPE_CH = re.compile(r"^CH\d+$", re.IGNORECASE)

# 含元数据 MAT 的专属字段：任一存在即按「含元数据」解析。
# 说明：schema<=2 的波形变量名为 signal；schema>=3 起改为 CH01，
# 与纯通道 MAT 的通道同名，因此类型判别不能再依赖波形变量名，改以这些元数据字段为准。
_BLACKBOX_MARKERS = (
    "capture_effective_fs",
    "capture_fs",
    "capture_sample_rate",
    "capture_timestamp_model",
    "history_payload_json",
    "signal",                       # 旧 schema 的波形变量名，保留兼容
)

# 波形变量候选名（按优先级）。
_BLACKBOX_SIGNAL_VARS = ("signal", "CH01", "CH1")

# 采样率字段的取值顺序：有效采样率对应波形实际所在的时间网格，优先采用。
_FS_FIELD_ORDER = ("capture_effective_fs", "capture_fs", "capture_sample_rate")

_FS_SOURCE_LABEL = {
    "capture_effective_fs": "有效采样率（实测）",
    "capture_fs": "配置采样率",
    "capture_sample_rate": "配置采样率",
}


# ----------------------------------------------------------------------------
# 1. 软件 CSV
# ----------------------------------------------------------------------------

def load_software_csv(path: str, fs_override: Optional[float] = None) -> SignalSet:
    """解析带表头的 CSV。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        lines = fh.read().splitlines()

    # 剔除空行
    lines = [ln for ln in lines if ln.strip()]
    if len(lines) < 4:
        raise ValueError("CSV 行数不足，无法按表头格式解析")

    def parse_num_line(ln: str) -> List[float]:
        out = []
        for tok in ln.split(","):
            tok = tok.strip()
            if tok == "":
                out.append(float("nan"))
                continue
            try:
                out.append(float(tok))
            except ValueError:
                out.append(float("nan"))
        return out

    h1 = parse_num_line(lines[0])
    h2 = parse_num_line(lines[1])
    h3 = parse_num_line(lines[2])

    # 第 1 行的前两个字段通常为采样率
    fs = float(h1[0]) if h1 and not np.isnan(h1[0]) else 20000.0
    n_cols = int(h1[2]) if len(h1) > 2 and not np.isnan(h1[2]) else len(h2)

    data = np.array([[float(x) for x in ln.split(",")] for ln in lines[3:]],
                    dtype=np.float64)
    if data.ndim != 2 or data.shape[0] < 3:
        raise ValueError("CSV 数据区解析失败")

    # --- 剔除导出器写入的哨兵行 ---
    # 实测：第 1 条全 0，第 2 条为「满量程标记」（等于各通道 ymax 对应的 raw 值）。
    # 判据：第二行的每个通道值若与后续数据的绝对最大值同量级（>0.5*maxabs），
    # 且该行明显高于数据本身的典型幅度，则视为哨兵行。
    skip = 0
    if np.allclose(data[0], 0.0, atol=1e-12):
        skip += 1
        nxt = data[1]
        rest = data[2:]
        if len(rest):
            maxabs = np.max(np.abs(rest), axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(maxabs > 0, nxt / maxabs, 0.0)
            if np.all(ratio > 0.5):
                skip += 1

    data = data[skip:]
    n_cols = min(n_cols, data.shape[1])

    # --- 物理标定 ---
    # 实测：逗号列里存的是「raw 值」，第 2 行 header 是该通道的量程上限(V)。
    # 每个通道的 raw 满量程 FS_raw 由第 2 行的满量程标记值反推：
    #     raw_fullscale ≈ 哨兵行的值（若被剔除则用数据自身最大值近似）
    # 标定系数 k = ymax / FS_raw
    channels: Dict[str, np.ndarray] = {}
    warnings: List[str] = []
    for ci in range(n_cols):
        raw = data[:, ci]
        ymax = h2[ci] if ci < len(h2) and np.isfinite(h2[ci]) and h2[ci] != 0 else None
        # 满量程 raw 值：优先取自哨兵行
        if skip >= 2:
            fs_raw = abs(parse_num_line(lines[3])[ci])
        else:
            fs_raw = float(np.max(np.abs(raw)))
        if fs_raw <= 0:
            fs_raw = float(np.max(np.abs(raw))) or 1.0
        if ymax is None:
            k = 1.0
            warnings.append(f"通道{ci} 未读到量程，按 1:1 比例处理")
        else:
            k = ymax / fs_raw
        volt = raw * k
        channels[f"CH{ci + 1}"] = volt

    if fs_override:
        fs = float(fs_override)

    meta = {
        "header_raw": lines[0],
        "ymax": ", ".join(f"{v:g}" for v in h2),
        "y0": ", ".join(f"{v:g}" for v in h3),
    }
    if len(channels) == 3:
        warnings.append("第 3 列为低分辨率辅助通道（量化步长为 CH1 的 4 倍），"
                        "默认不勾选显示")

    return SignalSet(
        path=path,
        name=os.path.basename(path),
        source_type="csv",
        channels=channels,
        fs=fs,
        fs_locked=not bool(fs_override),
        unit="V",
        meta=meta,
        warnings=warnings,
    )


# ----------------------------------------------------------------------------
# 2. MAT（含元数据）
# ----------------------------------------------------------------------------

def _pick_blackbox_waveform(mat: Dict[str, np.ndarray]) -> Tuple[np.ndarray, str]:
    """取出 MAT 的主波形，返回 ``(一维数组, 变量名)``。

    变量名随导出 schema 变化：schema<=2 为 ``signal``(1xN float64)，
    schema>=3 为 ``CH01``(Nx1 single)。两者语义相同，取值后统一拉平为一维。
    """
    for key in _BLACKBOX_SIGNAL_VARS:
        if key in mat:
            arr = np.asarray(mat[key], dtype=np.float64).ravel()
            if arr.size:
                return arr, key
    # 回退：文件中仅有一个 CHxx 变量时，视为波形通道
    chans = [k for k in mat if _SCOPE_CH.match(k)]
    if len(chans) == 1:
        arr = np.asarray(mat[chans[0]], dtype=np.float64).ravel()
        if arr.size:
            return arr, chans[0]
    raise ValueError(
        "MAT 中未找到波形变量（候选名：signal / CH01）"
    )


def load_blackbox_mat(path: str, fs_override: Optional[float] = None) -> SignalSet:
    """解析含采集参数元数据的 .mat。"""
    mat = sio.loadmat(path, squeeze_me=False)

    sig, sig_key = _pick_blackbox_waveform(mat)

    def _scalar(key, default=""):
        if key not in mat:
            return default
        arr = np.asarray(mat[key]).ravel()
        if arr.size == 0:
            return default
        v = arr[0]
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        return str(v)

    def _num(key):
        if key not in mat:
            return None
        try:
            v = float(np.asarray(mat[key]).ravel()[0])
        except (TypeError, ValueError, IndexError):
            return None
        return v if np.isfinite(v) and v > 0 else None

    # 采样率：优先取有效采样率——它对应波形实际所在的时间网格。
    fs = 20000.0
    fs_source = "默认值（文件内无采样率字段）"
    for key in _FS_FIELD_ORDER:
        v = _num(key)
        if v:
            fs = v
            fs_source = _FS_SOURCE_LABEL.get(key, key)
            break
    if fs_override:
        fs = float(fs_override)
        fs_source = "手动指定"

    meta = {
        "工况": _scalar("label_cn"),
        "故障类型": _scalar("fault_type_cn"),
        "严重度": _scalar("severity_cn"),
        "转速(rpm)": _scalar("rpm"),
        "采集时间": _scalar("created_at"),
        "波形变量": sig_key,
        "采样率依据": fs_source,
    }

    warnings: List[str] = []

    # 采样率自洽性：有效值与配置值不一致时，频率轴存在同量级的系统偏差。
    # 采集端若已自行给出说明（capture_rate_warning），则以其为准，不再重复提示。
    eff = _num("capture_effective_fs")
    cfg = _num("capture_fs")
    rate_warning = _scalar("capture_rate_warning")
    fs_dev_pct = None
    if eff and cfg:
        fs_dev_pct = abs(eff - cfg) / cfg * 100.0
        meta["配置/有效采样率"] = f"{cfg:g} / {eff:g} Hz"
        if fs_dev_pct > 1.0 and not rate_warning:
            warnings.append(
                f"文件记录的有效采样率 {eff:g} Hz 与配置值 {cfg:g} Hz 相差 "
                f"{fs_dev_pct:.2f}%，频率轴存在同量级系统偏差；该文件已解除采样率锁定，"
                f"如需以已知频率量重新标定，可直接修改右侧「采样率 fs」框。"
            )

    discont = _scalar("capture_discontinuities", "0")
    try:
        if int(float(discont)) > 0:
            warnings.append(f"采集存在 {discont} 次数据不连续（丢帧）")
    except Exception:
        pass

    if rate_warning:
        warnings.append(rate_warning)

    # 采样率锁定策略：文件自带值可信时锁定，避免误改；当有效值与配置值偏差超过 1%
    # 时，说明该值本身存疑，解除锁定以保留"按已知频率源修正"的通道。
    fs_locked = (not bool(fs_override)) and not (fs_dev_pct is not None and fs_dev_pct > 1.0)

    return SignalSet(
        path=path,
        name=os.path.basename(path),
        source_type="blackbox_mat",
        channels={"CH1": sig},
        fs=fs,
        fs_locked=fs_locked,
        unit=str(_scalar("signal_unit", "V")),
        meta=meta,
        warnings=warnings,
    )


# ----------------------------------------------------------------------------
# 3. MAT（纯通道）
# ----------------------------------------------------------------------------

def load_scope_mat(path: str, fs_override: Optional[float] = None) -> SignalSet:
    """解析仅含通道变量的 .mat。"""
    mat = sio.loadmat(path, squeeze_me=False)

    chans: Dict[str, np.ndarray] = {}
    for key in mat:
        if key.startswith("__"):
            continue
        if _SCOPE_CH.match(key):
            chans[key.upper()] = np.asarray(mat[key], dtype=np.float64).ravel()

    if not chans:
        raise ValueError("MAT 中未找到 CHxx 通道变量")

    # 文件内无采样率字段，默认 20000 Hz（与采集链路一致）
    fs = float(fs_override) if fs_override else 20000.0
    warnings = [] if fs_override else [
        "该 MAT 不含采样率字段，已按默认 20000 Hz 处理，请在右侧面板手动确认真实采样率"
    ]

    return SignalSet(
        path=path,
        name=os.path.basename(path),
        source_type="scope_mat",
        channels=chans,
        fs=fs,
        fs_locked=False,
        unit="V",
        meta={},
        warnings=warnings,
    )


# ----------------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------------

def sniff_type(path: str) -> str:
    """根据扩展名与文件内容判断来源类型。

    两类 MAT 都以 .mat 保存，含元数据者在 schema>=3 起主波形变量名也叫 ``CH01``，
    因此不能再用波形变量名区分二者。判据顺序：

    1. 含 ``capture_*`` / ``history_payload_json`` 元数据字段 → 含元数据；
    2. 含旧 schema 的 ``signal`` 变量 → 含元数据；
    3. 其余含 ``CHxx`` 变量的文件 → 纯通道。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return "csv"
    if ext in (".mat", ".MAT"):
        try:
            mat = sio.loadmat(path, squeeze_me=False)
            if any(marker in mat for marker in _BLACKBOX_MARKERS):
                return "blackbox_mat"
            if any(_SCOPE_CH.match(k) for k in mat):
                return "scope_mat"
        except Exception:
            pass
        return "scope_mat"
    raise ValueError(f"不支持的文件类型: {ext}")


def load_any(path: str, fs_override: Optional[float] = None) -> SignalSet:
    """按类型分派到对应解析器。"""
    t = sniff_type(path)
    if t == "csv":
        return load_software_csv(path, fs_override)
    if t == "blackbox_mat":
        return load_blackbox_mat(path, fs_override)
    return load_scope_mat(path, fs_override)


SUPPORTED_EXTS = (".csv", ".mat")


def list_data_files(folder: str) -> List[str]:
    """递归列出文件夹下所有支持的数据文件。"""
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in SUPPORTED_EXTS:
                out.append(os.path.join(root, fn))
    return sorted(out)
