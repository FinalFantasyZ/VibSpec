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

2. MAT（含采集参数元数据，如 "record.mat"）
     关键变量 signal (1xN float64) 或 CH01 / CH02 … (Nx1 single)，单位为 V。
     变量名随导出 schema 变化：schema<=2 为单通道 signal，schema>=3 改为
     逐通道 CHxx（与纯通道 MAT 的 CHxx 同形，便于 MATLAB 侧统一 plot）。
     schema>=3 的文件可能同时写入多个通道，本模块全部导入，不做取舍。
     capture_fs / capture_effective_fs 给采样率；
     rpm / fault_type_cn / severity_cn / label_cn 给工况与标签。

3. MAT（仅含通道变量，如 "scope.mat"）
     变量 CH03 / CH04，各 (N x 1) float32，单位 V。
     文件内不含采样率字段，需界面上手动指定（默认 20000 Hz）。

MAT 的**容器格式**（v4 / v5 / v7.3 / 原生 HDF5）与**文件损坏的容错读取**
统一交给 :mod:`mat_reader`；本模块只负责「取到变量之后怎么解释」。
这样以后无论厂商换成 v7.3、把通道塞进结构体，还是某个变量写坏，
都只需改一处，不必再动业务逻辑。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import mat_reader


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

# 通道变量名模式（CH01 / CH03 / CH4 / Chan1 / Channel_2 / AI3 …），捕获组为通道序号。
# 厂商导出器的写法并不统一，这里集中登记；新增写法只需往这里加一条。
_SCOPE_CH = re.compile(r"^CH[_\-]?(\d+)$", re.IGNORECASE)
_EXTRA_CH_PATTERNS = (
    re.compile(r"^Chan(?:nel)?[_\-]?(\d+)$", re.IGNORECASE),
    re.compile(r"^AI(?:N)?[_\-]?(\d+)$", re.IGNORECASE),
)

# 无编号波形的常见叫法：文件里只有一个/少数几个这样的变量时按顺序编号。
_GENERIC_WAVE = re.compile(
    r"^(X|Y|Z|Signal|Data|DataValues|Values|Wave|Waveform|Trace|Sweep|"
    r"Block|Record|Voltage|Amplitude|Samples?|Buffer|WaveData)$", re.IGNORECASE)

# 明确的时间轴变量名：命中即不作为通道。
# 注意 x / y 不在其中——示波器常把电压信号直接叫 X 或 Y，是否时间轴要靠
# 下面的「单调等间距」判据现场判断，不能凭名字一票否决。
_METADATA_NAMES = re.compile(
    r"^(fs|f_s|sampling_?rate|sample_?rate|samplerate|dt|time_?step|"
    r"effective_fs|configured_fs|sample_rate_hz|sampling_rate|"
    r"rpm|speed|rotational_?speed|"
    r"label.*|fault.*|severity.*|created_at|timestamp.*|"
    r"channel_?ids?|capture_.*|history.*|signal_?unit|unit|units|"
    r"name|names|title|comment|comments|notes?|"
    r"t|time|times|time_?vector|time_?axis|timeaxis|x_?axis|xaxis|"
    r"n_?samples|samples_?count|length|len|count|num_?samples|"
    r"version|schema|device|model|serial.*|operator|date|datetime|"
    r"nyquist|resolution|#.*|__.*)$", re.IGNORECASE)

# 含元数据 MAT 的专属字段：任一存在即按「含元数据」解析。
# 说明：schema<=2 的波形变量名为 signal；schema>=3 起改为 CH01、CH02 …
# 与纯通道 MAT 的通道同名，因此类型判别不能再依赖波形变量名，改以这些元数据字段为准。
_BLACKBOX_MARKERS = (
    "capture_effective_fs",
    "capture_fs",
    "capture_sample_rate",
    "capture_timestamp_model",
    "history_payload_json",
    "signal",                       # 旧 schema 的波形变量名，保留兼容
)

# 旧 schema（<=2）的波形变量名。新 schema 用 CHxx，可含多个通道。
_LEGACY_SIGNAL_VAR = "signal"

# 采样率字段的取值顺序：有效采样率对应波形实际所在的时间网格，优先采用。
# 后几项为不同导出版本的等价字段，仅在 capture_* 缺失时兜底；
# v7.3 / HDF5 导出器常用 SamplingRate / Fs 这类大小写变体。
_FS_FIELD_ORDER = (
    "capture_effective_fs",
    "capture_fs",
    "capture_sample_rate",
    "effective_fs",
    "sample_rate_hz",
    "sampling_rate",
    "samplerate",
    "SamplingRate",
    "sampling_frequency",
    "fs_hz",
    "configured_fs",
    "fs",
    "Fs",
    "FS",
)

_FS_SOURCE_LABEL = {
    "capture_effective_fs": "有效采样率（实测）",
    "capture_fs": "配置采样率",
    "capture_sample_rate": "配置采样率",
    "effective_fs": "有效采样率（实测）",
    "sample_rate_hz": "文件记录采样率",
    "sampling_rate": "文件记录采样率",
    "samplerate": "文件记录采样率",
    "SamplingRate": "文件记录采样率",
    "sampling_frequency": "文件记录采样率",
    "fs_hz": "文件记录采样率",
    "configured_fs": "配置采样率",
    "fs": "文件记录采样率",
    "Fs": "文件记录采样率",
    "FS": "文件记录采样率",
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
# MAT：变量 → 通道
# ----------------------------------------------------------------------------

def _tail(name: str) -> str:
    """取 ``父名.子名`` 的最后一段——通道名通常写在最后一段。"""
    return name.rsplit(".", 1)[-1] if "." in name else name


def _channel_index(name: str) -> Optional[int]:
    """变量名中的通道编号（CH01→1、Chan3→3）；没有编号返回 None。"""
    base = _tail(name)
    for pat in (_SCOPE_CH,) + _EXTRA_CH_PATTERNS:
        m = pat.match(base)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _is_metadata_name(name: str) -> bool:
    base = _tail(name)
    return bool(_METADATA_NAMES.match(base) or _METADATA_NAMES.match(name))


def _as_signal(value: Any, min_len: int = 8) -> Optional[np.ndarray]:
    """把变量值转成 1 维波形；不像波形的一律返回 ``None``。

    - 结构体 / 组：取其中的波形字段（见 :func:`_from_container`）；
    - 字符串与单元格不算波形；
    - 一维直接接受；二维只接受「一维为 1」的 N×1 / 1×N ——
      真正的列式表格（N×M，M>1）不猜列语义，避免把时间轴、索引当通道；
    - 全等值（常量占位）与大量 NaN 的排除。
    """
    if _is_struct(value):
        return _from_container(value)
    try:
        arr = np.asarray(value)
    except Exception:                              # noqa: BLE001
        return None
    if arr.dtype.kind not in "iuf" or arr.ndim == 0 or arr.ndim > 2:
        return None

    arr = arr.astype(np.float64, copy=False)
    if arr.ndim == 2:
        if 1 not in arr.shape:
            return None
        arr = arr.reshape(-1)
    if arr.size < min_len:
        return None

    finite = np.isfinite(arr)
    if finite.sum() < max(min_len, arr.size // 2):
        return None
    if np.nanmax(arr) == np.nanmin(arr):
        return None
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _looks_like_time_axis(arr: np.ndarray) -> bool:
    """判断一段 1 维数据是否只是时间轴。

    判据（同时满足才算）：单调不减、步长处处相等且为正、首值接近 0 或 1/fs 量级。
    单调等间距的正弦/扫频信号步长不会处处相等，因此不会被误判。

    注意：本判据**只用于没有通道编号的普通变量**（``X`` / ``Data`` 之类）。
    带编号的变量（``CH01`` / ``Chan2``）是仪器明确声明的通道，哪怕恰好是
    一条直线也照常导入——丢一条通道比多画一条时间轴严重得多。
    """
    if arr.size < 4:
        return False
    d = np.diff(arr.astype(np.float64, copy=False))
    if not np.all(d > 0):
        return False
    step = float(np.median(d))
    if step <= 0 or not np.allclose(d, step, rtol=1e-3, atol=step * 1e-4):
        return False
    start = float(arr[0])
    return abs(start) <= max(step * 4.0, abs(float(arr[-1])) * 1e-3)


def _is_struct(value: Any) -> bool:
    """是否为结构体：dict（HDF5 组）或 numpy 记录数组（MATLAB struct）。"""
    if isinstance(value, dict):
        return True
    return isinstance(value, np.ndarray) and value.dtype.names is not None


def _struct_fields(value: Any) -> Dict[str, Any]:
    """把结构体展开成 ``字段名 -> 值``（仅取第一个元素，波形通常是 1x1 struct）。"""
    if isinstance(value, dict):
        return dict(value)
    out: Dict[str, Any] = {}
    if not _is_struct(value) or value.size == 0:
        return out
    flat = value.reshape(-1)[0]
    for name in value.dtype.names:
        out[str(name)] = flat[name]
    return out


def _from_container(value: Any) -> Optional[np.ndarray]:
    """结构体 / HDF5 组：取出其中代表波形本体的字段。

    容器里的二维数组常是「时间列 + 信号列」的紧凑写法（如 ``XY`` 为 N×2），
    此时按列拆开：丢掉单调等间距的时间列，取剩下的信号列。
    只有一列信号时不猜，直接按波形返回。
    """
    fields = _struct_fields(value)
    if not fields:
        return None
    for key, sub in fields.items():
        if _GENERIC_WAVE.match(_tail(str(key))):
            arr = _signal_from_maybe_table(sub)
            if arr is not None:
                return arr
    found = [a for a in (_signal_from_maybe_table(v) for v in fields.values())
             if a is not None]
    return found[0] if len(found) == 1 else None


def _signal_from_maybe_table(value: Any, min_len: int = 8) -> Optional[np.ndarray]:
    """容器内的数组可能是一列波形，也可能是「时间 + 多路信号」的二维表。

    多列表格的语义无法从数据本身确定（哪列是时间、哪列是电压、单位是什么），
    因此这里只做**保守**处理：恰好剩一列信号时取它；否则交给调用方忽略，
    避免把一堆通道悄悄合并成一条曲线。
    """
    if _is_struct(value):
        return _from_container(value)
    try:
        arr = np.asarray(value)
    except Exception:                              # noqa: BLE001
        return None
    if arr.dtype.kind not in "iuf" or arr.ndim != 2 or 1 in arr.shape:
        return _as_signal(value, min_len=min_len)
    if arr.shape[0] < min_len:
        return None

    waves = []
    for col in range(arr.shape[1]):
        cand = _as_signal(arr[:, col], min_len=min_len)
        if cand is not None and not _looks_like_time_axis(cand):
            waves.append(cand)
    if len(waves) == 1:
        return waves[0]
    return None


def _flatten(variables: Dict[str, Any]) -> Dict[str, Any]:
    """把结构体 / 组展开成 ``父_子`` 与 ``父.子`` 两种写法，便于按名匹配。"""
    pool: Dict[str, Any] = dict(variables)
    for key, value in variables.items():
        if not _is_struct(value):
            continue
        for sub_key, sub_val in _struct_fields(value).items():
            if str(sub_key).startswith("#"):
                continue
            pool.setdefault(f"{key}_{sub_key}", sub_val)
            pool.setdefault(f"{key}.{sub_key}", sub_val)
    return pool


def _collect_scope_channels(mat: Dict[str, Any], min_len: int = 8
                            ) -> Tuple[Dict[str, np.ndarray], List[str]]:
    """收集 MAT 中所有波形通道，按通道序号升序返回 ``(通道字典, 提示)``。

    通道名保留文件中的原始写法（``CH01`` / ``CH03`` …）：编号本身携带物理
    接线信息，导出时可能只启用部分通道（例如只存在 ``CH02``），改写成
    ``CH1`` 会掩盖这一点。同一编号出现多种写法（``CH1`` 与 ``CH01``）时，
    保留文件中先出现的那个，并记录一条提示。

    多通道支持到这里为止，但**不猜**：N×M 的列式表格（时间列 + 多路电压）
    不会被擅自拆成 M 个通道，避免把时间轴画成一条通道曲线。
    """
    pool = _flatten(mat)
    picked: Dict[int, Tuple[str, np.ndarray]] = {}
    generic: List[Tuple[str, np.ndarray]] = []
    # 记录「被识别为波形但最终没导入」的长度，用于等长性判定：
    # 只看导入结果的话，较短的那一路缺席时就发现不了长度不一致。
    lengths_seen: Dict[str, int] = {}
    notes: List[str] = []

    for key, value in pool.items():
        if str(key).startswith("__") or _is_metadata_name(key):
            continue
        arr = _as_signal(value, min_len=min_len)
        if arr is None:
            continue
        idx = _channel_index(key)
        if idx is None:
            # 无编号变量才需要排除时间轴：带编号的变量是仪器明确声明的通道
            if _looks_like_time_axis(arr):
                notes.append(f"变量 {key} 是单调等间距的时间轴，"
                             f"已作为时间基准、未当作通道")
                continue
            # 只有「像波形」的无编号变量才登记，避免把任何数组都当通道
            if _GENERIC_WAVE.match(_tail(key)) or isinstance(value, dict):
                generic.append((key, arr))
            continue
        if idx in picked:
            notes.append(f"变量 {key} 与 {picked[idx][0]} 的通道序号重复，保留前者")
            continue
        picked[idx] = (key, arr)

    channels = {picked[i][0]: picked[i][1] for i in sorted(picked)}
    if channels:
        lengths_seen = {n: len(a) for n, a in channels.items()}
        lengths_seen.update({n: len(a) for n, a in generic})
        if generic:
            notes.append("另发现未编号的波形变量："
                         + "、".join(n for n, _a in generic) + "（已忽略，避免重复导入）")
        notes += _length_notes(lengths_seen)
        return channels, notes

    # 没有任何带编号的通道：把无编号波形按出现顺序编号。
    # 单通道文件直接沿用它自己的变量名（如 signal / X），信息量比 CH1 更多。
    for i, (name, arr) in enumerate(generic, start=1):
        label = name if len(generic) == 1 and "." not in name and "_" not in name \
            else f"CH{i}"
        if label in channels:
            label = f"{name}"
        channels[label] = arr
    if len(generic) > 1:
        notes.append("文件中的波形变量未带通道编号，已按出现顺序编为 "
                     + "、".join(channels))
    notes += _length_notes({n: len(a) for n, a in channels.items()})
    return channels, notes


def _length_notes(lengths: Dict[str, int]) -> List[str]:
    """多通道本应等长；不等长时说明软件按最短通道对齐，避免用户误判数据缺失。"""
    if len(lengths) < 2 or len(set(lengths.values())) < 2:
        return []
    return ["各通道采样点数不一致（"
            + "、".join(f"{n}: {c}" for n, c in lengths.items())
            + "），软件按最短通道对齐显示"]


def _declared_channel_ids(mat: Dict[str, Any]) -> List[int]:
    """读取文件声明的通道编号列表（channel_ids / capture_channel_ids）。"""
    for key in ("channel_ids", "capture_channel_ids"):
        if key not in mat:
            continue
        try:
            arr = np.asarray(mat[key]).ravel()
            ids = [int(float(v)) for v in arr if np.isfinite(float(v))]
        except (TypeError, ValueError):
            continue
        if ids:
            return ids
    return []


def _collect_blackbox_channels(mat: Dict[str, Any]
                               ) -> Tuple[Dict[str, np.ndarray], List[str]]:
    """取出含元数据 MAT 的全部波形通道。

    新 schema（>=3）逐个通道保存为 ``CH01`` / ``CH02`` …，必须全部导入；
    旧 schema（<=2）只有单个 ``signal`` 变量，按单通道 ``CH1`` 处理。
    两者并存时以 ``CHxx`` 为准——那才是当前导出的完整波形。
    """
    chans, notes = _collect_scope_channels(mat)

    legacy = None
    if _LEGACY_SIGNAL_VAR in mat:
        legacy = _signal_from_maybe_table(mat[_LEGACY_SIGNAL_VAR])

    if chans:
        if legacy is not None:
            first = next(iter(chans.values()))
            same = (legacy.size == first.size
                    and np.allclose(legacy, first, equal_nan=True))
            if not same:
                notes.append(
                    "文件同时含 signal 与 CHxx 通道：已按 CHxx 导入全部通道，"
                    "signal 视为遗留副本，未重复导入")
        return chans, notes

    if legacy is not None:
        return {"CH1": legacy}, notes

    raise ValueError("MAT 中未找到波形变量（候选名：signal / CH01 / CH02 …）")


# ----------------------------------------------------------------------------
# MAT：变量取值小工具
# ----------------------------------------------------------------------------

def _first_scalar(mat: Dict[str, Any], key: str) -> Any:
    if key not in mat:
        return None
    value = mat[key]
    if isinstance(value, dict):
        return None
    try:
        arr = np.asarray(value).ravel()
    except Exception:                              # noqa: BLE001
        return None
    if arr.size == 0:
        return None
    return arr[0]


def _to_text(value: Any) -> str:
    """把一个标量 / 字符数组转成文本。"""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip("\x00").strip()
    if isinstance(value, str):
        return value.strip("\x00").strip()
    if isinstance(value, np.generic):
        return _to_text(value.item())
    # MATLAB v7.3 / HDF5 把字符串存成码点数组：单个 uint16 直接 chr 会得到数字，
    # 必须**整数组**一起解，标签才会是「外圈点蚀」而不是 '22806'。
    if isinstance(value, np.ndarray) and value.dtype.kind in "iu" and value.size:
        try:
            codes = [int(c) for c in value.ravel()]
        except (TypeError, ValueError):
            return ""
        if all(0 < c < 0x110000 for c in codes):
            return "".join(chr(c) for c in codes).strip("\x00").strip()
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _scalar_text(mat: Dict[str, Any], key: str, default: str = "") -> str:
    """取标量并转成可显示文本（兼容 UTF-16 码点、bytes、单元素数组）。"""
    if key not in mat:
        return default
    value = mat[key]
    if isinstance(value, dict):
        return default
    # 字符数组要整体解码，不能先取 [0] 再转文本（那样只剩第一个码点）
    text = _to_text(value)
    if text:
        return text
    first = _first_scalar(mat, key)
    if first is None:
        return default
    text = _to_text(first)
    return text if text else default


def _scalar_number(mat: Dict[str, Any], key: str) -> Optional[float]:
    value = _first_scalar(mat, key)
    if value is None or isinstance(value, dict):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) and v > 0 else None


# ----------------------------------------------------------------------------
# 2. MAT（含元数据）
# ----------------------------------------------------------------------------

def _classify_mat(mat: Dict[str, Any]) -> str:
    """按「变量内容」判定 MAT 属于含元数据还是纯通道（不读文件，便于复用）。"""
    if any(marker in mat for marker in _BLACKBOX_MARKERS):
        return "blackbox_mat"
    return "scope_mat"


def load_blackbox_mat(path: str, fs_override: Optional[float] = None,
                      variables: Optional[Dict[str, Any]] = None) -> SignalSet:
    """解析含采集参数元数据的 .mat。

    ``variables`` 可传入已读好的变量（``load_any`` 复用同一次读取，
    避免大文件在判别与解析阶段各读一遍）。
    """
    if variables is None:
        variables = read_mat_variables(path)
    return _build_blackbox(path, variables, fs_override)


def _build_blackbox(path: str, loaded: Dict[str, Any],
                    fs_override: Optional[float]) -> SignalSet:
    """由已读好的变量构造含元数据 MAT 的 ``SignalSet``。"""
    mat = loaded["variables"]
    channels, ch_notes = _collect_blackbox_channels(mat)
    warnings: List[str] = list(loaded.get("notes") or []) + list(ch_notes)

    fs = 20000.0
    fs_source = "默认值（文件内无采样率字段）"
    for key in _FS_FIELD_ORDER:
        v = _scalar_number(mat, key)
        if v:
            fs = v
            fs_source = _FS_SOURCE_LABEL.get(key, key)
            break
    if fs_override:
        fs = float(fs_override)
        fs_source = "手动指定"

    meta = {
        "工况": _scalar_text(mat, "label_cn"),
        "故障类型": _scalar_text(mat, "fault_type_cn"),
        "严重度": _scalar_text(mat, "severity_cn"),
        "转速(rpm)": _scalar_text(mat, "rpm"),
        "采集时间": _scalar_text(mat, "created_at"),
        "通道变量": ", ".join(channels),
        "采样率依据": fs_source,
        "MAT 容器": loaded.get("format", ""),
    }

    # 通道数自洽性：文件声明的通道数与实际解析到的变量数不一致时，
    # 说明该文件只写入了部分通道，提示用户以免误判为"设备只接了一路"。
    declared = _declared_channel_ids(mat)
    if declared and len(declared) != len(channels):
        warnings.append(
            f"文件声明 {len(declared)} 个通道（编号 {', '.join(str(i) for i in declared)}），"
            f"实际解析到 {len(channels)} 个（{', '.join(channels)}）；"
            f"该文件可能只写入了部分通道")

    # 采样率自洽性：有效值与配置值不一致时，频率轴存在同量级的系统偏差。
    # 采集端若已自行给出说明（capture_rate_warning），则以其为准，不再重复提示。
    eff = _scalar_number(mat, "capture_effective_fs")
    cfg = _scalar_number(mat, "capture_fs")
    rate_warning = _scalar_text(mat, "capture_rate_warning")
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

    discont = _scalar_text(mat, "capture_discontinuities", "0")
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
        channels=channels,
        fs=fs,
        fs_locked=fs_locked,
        unit=_scalar_text(mat, "signal_unit", "V") or "V",
        meta=meta,
        warnings=warnings,
    )


# ----------------------------------------------------------------------------
# 3. MAT（纯通道）
# ----------------------------------------------------------------------------

def load_scope_mat(path: str, fs_override: Optional[float] = None,
                   variables: Optional[Dict[str, Any]] = None) -> SignalSet:
    """解析仅含通道变量的 .mat。

    ``variables`` 可传入已读好的变量，避免重复读盘。
    """
    if variables is None:
        variables = read_mat_variables(path)
    return _build_scope(path, variables, fs_override)


def _build_scope(path: str, loaded: Dict[str, Any],
                 fs_override: Optional[float]) -> SignalSet:
    """由已读好的变量构造纯通道 MAT 的 ``SignalSet``。"""
    mat = loaded["variables"]

    channels, ch_notes = _collect_scope_channels(mat)
    if not channels:
        raise ValueError(_no_channel_message(mat))

    # 采样率：优先手动指定；其次读文件自带的标量字段（不同导出器命名不一）；
    # 都没有才退回默认 20000 Hz。自动识别值不锁定，允许用户按已知频率源修正。
    warnings: List[str] = list(loaded.get("notes") or []) + list(ch_notes)
    auto = None
    if not fs_override:
        for key in _FS_FIELD_ORDER:
            if key not in mat:
                continue
            v = _scalar_number(mat, key)
            if v and 10.0 <= v <= 2e6:
                auto = (v, key)
                break

    if fs_override:
        fs = float(fs_override)
    elif auto is not None:
        fs = auto[0]
        warnings.append(f"采样率取自文件字段 {auto[1]}（{fs:g} Hz）；"
                        f"如与实际不符，可直接在右侧面板修改")
    else:
        fs = 20000.0
        warnings.append("该 MAT 不含采样率字段，已按默认 20000 Hz 处理，"
                        "请在右侧面板手动确认真实采样率")

    return SignalSet(
        path=path,
        name=os.path.basename(path),
        source_type="scope_mat",
        channels=channels,
        fs=fs,
        fs_locked=False,
        unit="V",
        meta={"MAT 容器": loaded.get("format", "")},
        warnings=warnings,
    )


def _no_channel_message(mat: Dict[str, Any]) -> str:
    """一个通道都没认出来时，告诉用户文件里到底有什么，而不是只说"没找到"。"""
    numeric, other = [], []
    for key, value in mat.items():
        if str(key).startswith("#"):
            continue
        arr = None
        try:
            arr = np.asarray(value)
        except Exception:                          # noqa: BLE001
            arr = None
        if isinstance(value, dict):
            other.append(f"{key}(结构体)")
        elif arr is not None and arr.dtype.kind in "iuf" and arr.size > 0:
            numeric.append(f"{key}{tuple(arr.shape)}")
        else:
            other.append(key)
    detail = []
    if numeric:
        detail.append("数值变量：" + "、".join(numeric[:12]))
    if other:
        detail.append("其它变量：" + "、".join(other[:12]))
    return ("MAT 中未找到波形通道变量（候选名：CH01 / CH02 / Chan1 / "
            "Waveform / X …）。" + ("；文件内含 " + "；".join(detail) if detail else ""))


# ----------------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------------

def read_mat_variables(path: str) -> Dict[str, Any]:
    """读出 MAT 的全部变量（供自检 / 调试 / 外部工具复用）。

    返回 ``mat_reader`` 的结果字典；格式不支持时抛 ``ValueError``。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in MAT_CONTAINER_EXTS:
        raise ValueError(f"不是 MAT 文件：{ext}")
    try:
        return mat_reader.load_mat_variables(path)
    except mat_reader.MatLoadError as exc:
        raise ValueError(str(exc)) from exc


def _is_mat_path(path: str) -> bool:
    """是否按 MAT/HDF5 容器处理（含 .h5 / .hdf5 这类 v7.3 的常见别名）。"""
    return os.path.splitext(path)[1].lower() in MAT_CONTAINER_EXTS


def sniff_type(path: str) -> str:
    """根据扩展名与文件内容判断来源类型。

    两类 MAT 都以 .mat 保存，含元数据者在 schema>=3 起主波形变量名也叫 ``CH01``，
    因此不能再用波形变量名区分二者。判据顺序：

    1. 含 ``capture_*`` / ``history_payload_json`` 元数据字段 → 含元数据；
    2. 含旧 schema 的 ``signal`` 变量 → 含元数据；
    3. 其余含通道变量（CHxx / Chan1 / Waveform …）的文件 → 纯通道。

    **坏文件不再被误分类**：读取失败时抛 ``ValueError`` 并说明原因，
    而不是像旧版那样一律当成"纯通道 MAT"，让用户在下游收到
    "未找到 CHxx 通道变量"这种与真实原因无关的报错。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return "csv"
    if not _is_mat_path(path):
        raise ValueError(f"不支持的文件类型: {ext}")
    return _classify_mat(read_mat_variables(path)["variables"])


def load_any(path: str, fs_override: Optional[float] = None) -> SignalSet:
    """按类型分派到对应解析器。

    MAT 只读一次：类型判别与解析共用同一份变量，避免大文件被读两遍
    （示波器文件动辄几百 MB，重复读取会明显拖慢批量导入）。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return load_software_csv(path, fs_override)
    if not _is_mat_path(path):
        raise ValueError(f"不支持的文件类型: {ext}")
    loaded = read_mat_variables(path)          # 坏文件在此处给出可读的失败原因
    if _classify_mat(loaded["variables"]) == "blackbox_mat":
        return _build_blackbox(path, loaded, fs_override)
    return _build_scope(path, loaded, fs_override)


# 按 MAT/HDF5 容器处理的扩展名。.h5/.hdf5 是 MATLAB v7.3 文件的常见别名
# （部分仪器和 Python 侧工具会这样存），一并接受可省去用户手工改名的麻烦。
MAT_CONTAINER_EXTS = (".mat", ".h5", ".hdf5")

SUPPORTED_EXTS = (".csv", ".mat", ".h5", ".hdf5")


def list_data_files(folder: str) -> List[str]:
    """递归列出文件夹下所有支持的数据文件。"""
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in SUPPORTED_EXTS:
                out.append(os.path.join(root, fn))
    return sorted(out)
