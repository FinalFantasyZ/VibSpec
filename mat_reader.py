# -*- coding: utf-8 -*-
"""
mat_reader.py —— MAT 文件的通用读取后端（与「哪种数据来源」无关）

为什么需要单独一层：
    仪器导出的 .mat 并不只有一种实现。实测到过的三类互不兼容的写法：

    1. MATLAB v5（Header 128 字节 + 元素描述符），由 scipy.io.loadmat 读取；
    2. MATLAB v7.3（HDF5 容器，开头可能是 0 字节也可能是 512 字节的 HDF5 签名），
       scipy.io.loadmat **根本不支持**，必须走 h5py；
    3. HDF5 但存储的是**原生 HDF5 字符串**（不是 MATLAB 的 uint16 码点），
       按 MATLAB 规则解码必然得到乱码。

    此外，个别示波器/采集器的 v5 写出器会把某些变量写成 ``miCOMPRESSED``，
    而内部数据并不是合法的 zlib/deflate 流（实测 DL950 导出的 ``FFT01`` 即如此）。
    这种情况 scipy 会**逐个变量读取并抛错**，一个坏变量就让整份文件读不出来，
    甚至把本可直接读到的 ``CH02`` 波形一起赔进去。

本模块的职责：
    只做「把文件里的变量取出来」这件事，输出 ``Dict[str, Any]``：
    ``key -> np.ndarray``（数值/逻辑/字符/结构体）或 ``key -> Dict``（HDF5 组）。
    变量名清洗、通道识别、采样率解析等业务逻辑仍在 loader.py，
    因此新增一种容器（如 TDMS 转存、v4）时，只需在此扩展，不动上层。

容错策略（对应「以后不要再因为一个坏变量整份文件打不开」）：
    - v5：先用 scipy 整体读；失败则退到 ``MatFile5Reader`` **逐个变量**读，
      坏变量单独跳过并记入 ``fmt["skipped"]``；
    - 仍失败则使用内置的**结构级扫描器**（直接解析元素描述符）兜底，
      它能在文件截断/坏变量/缺少结尾的情况下取回已存在的波形；
    - v7.3/HDF5：若 h5py 缺失或文件损坏，用 r2022 以上的后备提示，
      不把底层 OSError 直接抛给用户。
"""

from __future__ import annotations

import os
import struct
import zlib
from typing import Any, Dict, List, Tuple

import numpy as np

MatDict = Dict[str, Any]

# 单次读取的元素大小上限：超过就按块读，避免一次性申请超大内存。
_CHUNK_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------------------
# 结果容器
# ---------------------------------------------------------------------------

class MatLoadError(Exception):
    """MAT 读取失败的统一异常（消息可直接展示给用户）。"""


def _result(variables: MatDict, fmt: str) -> Dict[str, Any]:
    return {
        "format": fmt,               # 'v5' | 'v4' | 'v7.3' | 'hdf5'
        "variables": variables,
        "skipped": [],               # 读不出来的变量名
        "notes": [],                 # 解析提示（逐条汇入 SignalSet.warnings）
    }


# ---------------------------------------------------------------------------
# 入口分派
# ---------------------------------------------------------------------------

def load_mat_variables(path: str) -> Dict[str, Any]:
    """读出一个 .mat 文件中的全部变量。

    返回 ``{"format", "variables", "skipped", "notes"}``。
    失败时抛出 :class:`MatLoadError`，其消息已是面向用户的说明。
    """
    if not os.path.isfile(path):
        raise MatLoadError(f"文件不存在：{path}")

    kind = probe_container(path)

    if kind == "hdf5":
        return _load_hdf5(path)
    if kind == "mat_v5":
        return _load_v5(path)
    if kind == "mat_v4":
        return _load_v4(path)
    if kind == "unknown":
        raise MatLoadError(
            "无法识别该 .mat 的文件格式：既不是 MATLAB v4/v5/v7.3，"
            "也不是 HDF5 容器。请确认文件未被改名或截断后重试。")
    # empty：0 字节或只有文件头
    raise MatLoadError("该 .mat 文件为空（或只剩文件头），没有任何变量数据。")


def probe_container(path: str) -> str:
    """只看文件头判断容器类型：``hdf5`` / ``mat_v5`` / ``mat_v4`` / ``empty`` / ``unknown``。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(1100)
    except OSError as exc:
        raise MatLoadError(f"无法打开文件：{exc}")

    if size == 0:
        return "empty"
    if size < 20:
        return "unknown"

    # HDF5 签名位置：v7.3 既可能是 0（无 userblock），也可能在 512 偏移；
    # 少数写出器用 1024/2048 的 userblock，一并探测。
    sig = b"\x89HDF\r\n\x1a\n"
    for off in (0, 512, 1024, 2048):
        if head[off:off + 8] == sig:
            return "hdf5"

    if head[:19] == b"MATLAB 5.0 MAT-file":
        return "mat_v5"
    if head[:6] == b"MATLAB" and head[6:7].isdigit():
        # 例如 "MATLAB 4.0 MAT-file" / "MATLAB 5.0 MAT-file" 的变体写法
        if head[6:9] == b"4.0":
            return "mat_v4"
        return "mat_v5"
    return "unknown"


# ---------------------------------------------------------------------------
# MATLAB v5
# ---------------------------------------------------------------------------

def _load_v5(path: str) -> Dict[str, Any]:
    import scipy.io as sio

    notes: List[str] = []

    # ① 常规路径：scipy 整体读取，最快也最完整
    try:
        raw = sio.loadmat(path, squeeze_me=False, struct_as_record=True)
        variables = {_clean_name(k): v for k, v in raw.items() if not str(k).startswith("__")}
        if variables:
            return _result(variables, "v5")
    except Exception as exc:                       # noqa: BLE001 —— 兜底路径必须接住一切
        notes.append(f"标准方式读取失败（{_short_exc(exc)}），已改用逐变量容错读取")

    # ② 逐变量读取：坏变量（如示波器的坏 FFT 变量）不再拖垮整份文件
    variables, skipped = _load_v5_per_variable(path)
    if variables:
        named = [n for n in skipped if n]
        if named:
            notes.append("以下变量无法解析，已跳过（其余变量不受影响）："
                         + "、".join(named))
        elif skipped:
            notes.append(f"有 {len(skipped)} 个变量无法解析（数据已损坏，连变量名都"
                         f"读不出），已跳过；其余变量不受影响")
        out = _result(variables, "v5")
        out["skipped"] = skipped
        out["notes"] = notes
        return out

    # ③ 结构级扫描兜底（应对截断 / 描述符异常 / 缺少结尾）
    variables, skipped, scan_notes = _scan_v5_elements(path)
    if variables:
        out = _result(variables, "v5")
        out["skipped"] = skipped
        out["notes"] = notes + scan_notes + [
            "已启用结构级扫描器恢复数据，变量结构（结构体 / cell）可能未被完整展开"]
        return out

    raise MatLoadError(
        "该文件是 MATLAB v5 容器，但其中没有任何可解析的数值变量。"
        + (f"（丢弃的变量：{'、'.join(n for n in skipped if n)}）"
           if any(skipped) else ""))


def _load_v5_per_variable(path: str) -> Tuple[MatDict, List[str]]:
    """逐变量读取：单个变量损坏时不牵连其它变量。

    实现要点：先用**自己的容错目录扫描**拿到每个顶层元素的字节区间，
    再把「128 字节文件头 + 该元素」拼成一个独立的小文件交给 scipy 解析。
    这样：
      - 坏变量只会让它自己的切片解析失败，不会把读者的文件位置搞乱，
        也不会像 ``list_variables()`` 那样一遇到坏的 miCOMPRESSED 就整体抛错；
      - 变量内部若是结构体 / cell / 稀疏矩阵，仍由 scipy 完整展开。

    实测价值：DL950 的 ``FFT01`` 被写成 miCOMPRESSED，但内部并不是合法的
    deflate 流，``loadmat`` 读到它必抛 ``OSError: could not read bytes``；
    而同一文件里的 ``CH02`` 波形其实完好无损。
    """
    import io

    import scipy.io as sio

    variables: MatDict = {}
    skipped: List[str] = []

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return variables, skipped
    if len(data) <= 128:
        return variables, skipped

    header = data[:128]
    endian = ">" if data[126:128] == b"MI" else "<"

    for name, start, end in _v5_directory(data, endian):
        chunk = data[start:end]
        if not chunk:
            skipped.append(name)
            continue
        try:
            raw = sio.loadmat(io.BytesIO(header + chunk), squeeze_me=False,
                              struct_as_record=True)
        except Exception:                          # noqa: BLE001
            skipped.append(name)
            continue
        got = {_clean_name(k): v for k, v in raw.items()
               if not str(k).startswith("__")}
        if got:
            variables.update(got)
        else:
            skipped.append(name)
    return variables, skipped


def _v5_directory(data: bytes, endian: str) -> List[Tuple[str, int, int]]:
    """容错扫描 v5 顶层目录，返回 ``[(变量名, 元素起始, 元素结束), ...]``。

    与 scipy 的 ``list_variables`` 不同：压缩元素解压失败时**不中断扫描**，
    而是尽可能从原始字节里取出变量名后继续往后走。
    """
    entries: List[Tuple[str, int, int]] = []
    total = len(data)
    pos = 128
    while pos + 8 <= total:
        try:
            dtype, nbytes, data_pos, next_pos = _read_tag(data, pos, endian)
        except Exception:                          # noqa: BLE001
            break
        end = min(total, data_pos + nbytes)
        if dtype == _MI_MATRIX:
            name = _peek_matrix_name(data[data_pos:end], endian)
            entries.append((name, pos, end))
        elif dtype == _MI_COMPRESSED:
            payload, _why = _inflate(data[data_pos:end], nbytes)
            name = (_peek_matrix_name(payload, endian) if payload
                    else _peek_compressed_name(data[data_pos:end]))
            entries.append((name or "", pos, end))
        else:
            break                                  # 顶层出现裸数据元素：不是合法 v5
        if next_pos <= pos:
            break
        pos = next_pos
    return entries


def _peek_matrix_name(chunk: bytes, endian: str) -> str:
    """从一个 miMATRIX 元素的**载荷**（不含外层描述符）里取出变量名。

    元素内部固定是三个连续的数据元素：数组标志 → 维度 → 变量名。
    必须按「描述符 → 下一元素」逐级推进；直接按数据偏移再读会把标志值
    当成下一个描述符，得到一串乱码。
    """
    pos = 0
    for _ in range(2):                             # 跳过数组标志、维度
        try:
            _t, _n, _dp, pos = _read_tag(chunk, pos, endian)
        except Exception:                          # noqa: BLE001
            return ""
    try:
        _t, name_len, name_pos, _p = _read_tag(chunk, pos, endian)
    except Exception:                              # noqa: BLE001
        return ""
    if not 0 < name_len <= 128 or name_pos + name_len > len(chunk):
        return ""
    return _clean_name(chunk[name_pos:name_pos + name_len].decode("ascii", "replace"))


def _clean_name(name: Any) -> str:
    """变量名规范化：bytes → str，去掉 MATLAB 写入的 NUL 填充。"""
    if isinstance(name, bytes):
        name = name.decode("ascii", "replace")
    if name is None:
        return ""
    return str(name).strip().strip("\x00").strip()


# ---- 结构级扫描器：不依赖 scipy 的宽松解析 -------------------------------

_MI_DTYPES = {
    1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4",
    7: "f4", 9: "f8", 12: "i8", 13: "u8", 16: "u1", 17: "u2", 18: "u4",
}
_MI_MATRIX = 14
_MI_COMPRESSED = 15


def _scan_v5_elements(path: str) -> Tuple[MatDict, List[str], List[str]]:
    """直接解析 v5 元素描述符，尽量取回还能读的变量。

    只处理「顶层数值矩阵」：这是振动数据的绝大多数情况。
    结构体 / cell / 稀疏矩阵不在此展开——它们已经由 scipy 的两条路径覆盖，
    走到这里说明文件本身有问题，优先保住波形而不是画得太全。
    """
    variables: MatDict = {}
    skipped: List[str] = []
    notes: List[str] = []

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return variables, skipped, [f"文件无法读取：{exc}"]

    if len(data) <= 128:
        return variables, skipped, ["文件不足 128 字节，没有元素数据"]

    endian = "<"
    if len(data) >= 128 and data[126:128] == b"MI":
        endian = ">"

    pos = 128
    total = len(data)
    while pos + 8 <= total:
        try:
            dtype, nbytes, data_pos, next_pos = _read_tag(data, pos, endian)
        except Exception:                          # noqa: BLE001
            notes.append(f"偏移 {pos} 处的元素描述符不可解析，已停止扫描")
            break

        if dtype == _MI_COMPRESSED:
            blob = data[data_pos:data_pos + nbytes]
            payload, why = _inflate(blob, nbytes)
            if payload is None:
                name = _peek_compressed_name(blob)
                skipped.append(name or f"<偏移 {pos} 的压缩变量>")
                notes.append(
                    f"变量 {name or '(未命名)'} 声明的压缩长度为 {nbytes} 字节，"
                    f"但内部数据不是合法的 deflate 流（{why}），已跳过")
            else:
                _scan_matrix(payload, 0, len(payload), endian, variables, skipped, notes)
        elif dtype == _MI_MATRIX:
            _scan_matrix(data, data_pos, min(total, data_pos + nbytes),
                         endian, variables, skipped, notes)
        else:
            # 顶层出现裸数据元素：不是合法 v5 文件的常态，跳过该元素
            pass

        if next_pos <= pos:                        # 防御：描述符异常时避免死循环
            break
        pos = next_pos

    return variables, skipped, notes


def _read_tag(buf: bytes, pos: int, endian: str) -> Tuple[int, int, int, int]:
    """读取一个数据元素描述符，返回 ``(数据类型, 字节数, 数据起点, 下一元素起点)``。

    兼容两种编码：普通 8 字节描述符，以及「小数据元素」（高 16 位存长度、
    数据紧跟在 4 字节类型之后）。
    """
    w0, w1 = struct.unpack_from(endian + "II", buf, pos)
    small = w0 >> 16
    dtype = w0 & 0xFFFF
    if small:
        return dtype, small, pos + 4, pos + 8
    pad = (8 - (w1 % 8)) % 8
    return dtype, w1, pos + 8, pos + 8 + w1 + pad


def _inflate(blob: bytes, declared: int) -> Tuple[bytes, str]:
    """解压 miCOMPRESSED 元素。

    返回 ``(解压后的字节, 失败原因)``；成功时原因为空串。
    依次尝试：标准 zlib → 裸 deflate → 带预设字典的 zlib →
    宽松模式（忽略内嵌长度字段，尽量救回数据）。
    """
    if len(blob) < declared:
        return None, f"文件被截断，实际只有 {len(blob)} 字节"

    for wbits in (15, -15, 31, 47):
        try:
            return zlib.decompress(blob, wbits), ""
        except zlib.error:
            continue

    # 宽松模式：部分写出器写入的长度字段与实际不符，但数据本身可解。
    for wbits in (15, -15):
        try:
            obj = zlib.decompressobj(wbits)
            out = obj.decompress(blob) + obj.flush()
            if out:
                return out, ""
        except zlib.error:
            continue

    return None, "zlib 解压失败（数据损坏或不是 deflate 流）"


def _peek_compressed_name(blob: bytes) -> str:
    """尽力从坏掉的压缩数据里取变量名，便于告诉用户究竟丢了什么。

    坏流已无法按 deflate 规则解压，但**没能压缩掉的那部分字节往往原样留在
    数据中**。这里在原始字节里找出「紧跟在 MAT 变量名元素描述符之后」的
    ASCII 串：变量名元素的类型码为 1（miINT8），长度为 1~63。
    """
    for i in range(len(blob) - 8):
        if blob[i] != 0x01:
            continue
        nbytes = blob[i + 4]
        if not 1 <= nbytes <= 63:
            continue
        candidate = blob[i + 8:i + 8 + nbytes]
        if len(candidate) < nbytes:
            continue
        try:
            name = candidate.decode("ascii")
        except UnicodeDecodeError:
            continue
        if name.isidentifier() or (name and all(c.isalnum() or c == "_" for c in name)):
            return name
    return ""


def _scan_matrix(buf: bytes, start: int, end: int, endian: str,
                 variables: MatDict, skipped: List[str], notes: List[str]) -> None:
    """解析一个 miMATRIX 元素（数组标志、维度、变量名、数值体）。

    ``start`` 是矩阵**载荷**的起点（外层描述符已由调用方读掉）。
    内部按元素逐级推进：标志 → 维度 → 变量名 → 数值体。
    """
    try:
        _t, _n, _dp, pos = _read_tag(buf, start, endian)        # 数组标志
        _t, dim_len, dim_pos, pos = _read_tag(buf, pos, endian)  # 维度
        n_dim = dim_len // 4
        if not 0 < n_dim <= 8:
            return
        dims = list(struct.unpack_from(endian + "i" * n_dim, buf, dim_pos))
        _t, name_len, name_pos, pos = _read_tag(buf, pos, endian)  # 变量名
        name = _clean_name(buf[name_pos:name_pos + name_len].decode("ascii", "replace"))
        if not name or name.startswith("__"):
            return

        # 数值体：必须是数值/字符元素；结构体、cell、复数包装不在此展开
        val_type, val_len, val_pos, _p = _read_tag(buf, pos, endian)
        if val_type not in _MI_DTYPES:
            return
        np_dtype = np.dtype(_MI_DTYPES[val_type]).newbyteorder(endian)
        itemsize = np_dtype.itemsize
        count = int(np.prod(dims)) if dims else val_len // itemsize
        avail = max(0, (min(end, len(buf)) - val_pos)) // itemsize
        count = min(count, avail, max(0, val_len // itemsize))
        if count <= 0:
            return
        arr = np.frombuffer(buf, dtype=np_dtype, count=count, offset=val_pos)
        arr = np.array(arr)
        if dims and int(np.prod(dims)) == count:
            arr = arr.reshape(tuple(dims))
        if name not in variables:
            variables[name] = arr
    except Exception as exc:                       # noqa: BLE001
        notes.append(f"偏移 {start} 处的矩阵解析失败：{_short_exc(exc)}")


# ---------------------------------------------------------------------------
# MATLAB v4
# ---------------------------------------------------------------------------

def _load_v4(path: str) -> Dict[str, Any]:
    import scipy.io as sio

    try:
        raw = sio.loadmat(path, squeeze_me=False)
    except Exception as exc:                       # noqa: BLE001
        raise MatLoadError(f"MATLAB v4 格式读取失败：{_short_exc(exc)}")
    variables = {k: v for k, v in raw.items() if not k.startswith("__")}
    if not variables:
        raise MatLoadError("该文件是 MATLAB v4 容器，但其中没有任何变量。")
    return _result(variables, "v4")


# ---------------------------------------------------------------------------
# MATLAB v7.3 / 原生 HDF5
# ---------------------------------------------------------------------------

def _load_hdf5(path: str) -> Dict[str, Any]:
    try:
        import h5py
    except ImportError:
        raise MatLoadError(
            "该文件是 MATLAB v7.3（HDF5 容器）格式，需要 h5py 才能读取。\n"
            "请执行：pip install h5py\n"
            "或在 MATLAB 中用 save(..., '-v7') 另存为 v5 格式。")

    notes: List[str] = []
    variables: MatDict = {}
    try:
        with h5py.File(path, "r") as fh:
            for key in fh.keys():
                try:
                    variables[key] = _h5_to_python(fh[key])
                except Exception as exc:           # noqa: BLE001
                    notes.append(f"变量 {key} 解析失败：{_short_exc(exc)}")
    except OSError as exc:
        raise MatLoadError(
            f"该文件是 HDF5 容器，但打开失败：{_short_exc(exc)}。"
            "常见原因是文件仍在写入、被其它程序占用或已损坏。")

    if not variables:
        raise MatLoadError("该 HDF5 / v7.3 文件打开成功，但其中没有可读取的变量。")

    is_matlab = path_is_matlab_hdf5(path, variables)
    fmt = "v7.3" if is_matlab else "hdf5"
    if not is_matlab:
        notes.append("该文件是 HDF5 容器但未带 MATLAB 元数据（#refs# / MATLAB_fields），"
                     "已按原生 HDF5 数据集读取")
    out = _result(variables, fmt)
    out["notes"] = notes
    return out


def path_is_matlab_hdf5(path: str, variables: MatDict) -> bool:
    """判断 HDF5 是否由 MATLAB 写出（看是否存在 ``#refs#`` / ``#subsystem#``）。"""
    if "#refs#" in variables or "#subsystem#" in variables:
        return True
    try:
        import h5py
        with h5py.File(path, "r") as fh:
            userblock = fh.userblock_size
            for k in fh.keys():
                if k in ("#refs#", "#subsystem#"):
                    return True
            # MATLAB 的 v7.3 通常使用 512 字节 userblock
            if userblock >= 512:
                return True
    except Exception:                              # noqa: BLE001
        pass
    return False


def _h5_to_python(obj: Any) -> Any:
    """把 HDF5 节点转成 numpy 数组 / 字典。

    需要兼顾两种来源：
      - MATLAB v7.3：把变量名、字符串存成 **uint16 码点**数组，并带
        ``MATLAB_class`` / ``MATLAB_int_decode`` 属性；
      - 原生 HDF5 导出器（LabVIEW、Python、部分示波器固件）：存的是真正的
        HDF5 字符串与普通多维数组，**没有** MATLAB 属性。
    若一律按 MATLAB 规则解码，后者的字符串会变成乱码、通道名匹配不上。
    """
    import h5py

    if isinstance(obj, h5py.Group):
        return {str(k): _h5_to_python(obj[k]) for k in obj.keys()}

    ds = obj
    cls = ds.attrs.get("MATLAB_class")
    try:
        raw = ds[()]
    except Exception:                              # noqa: BLE001
        return np.empty((0,))

    # ---- 字符串：分三种存储方式分别处理 ----
    if cls in (b"char", "char") or ds.dtype == h5py.special_dtype(ref=h5py.Reference):
        text = _h5_decode_strings(ds, raw, is_matlab=(cls is not None))
        if text is not None:
            return np.array([[text]])
    if isinstance(raw, (bytes, str)):
        return np.array([[raw.decode("utf-8", "replace")
                          if isinstance(raw, bytes) else raw]])
    if raw is None:
        return np.empty((0,))
    if isinstance(raw, h5py.Empty):
        return np.empty((0,))

    arr = np.asarray(raw)
    if arr.dtype.kind in ("S", "U", "O"):
        if arr.dtype.kind == "S" and cls is None:
            # 原生 HDF5 的定长字节串
            try:
                arr = np.char.decode(arr, "utf-8")
            except Exception:                      # noqa: BLE001
                pass
        return arr

    # MATLAB 的维度顺序与 numpy 相反（Fortran 序），转置回用户看到的行列
    if cls is not None and arr.ndim == 2:
        arr = arr.T
    return arr


def _h5_decode_strings(ds: Any, raw: Any, is_matlab: bool) -> str | None:
    """解出 HDF5 字符串。

    三种常见存储方式必须分开处理，否则中文标签会变成一串数字：
      - 原生 HDF5 定长字节串（``S``）/ Unicode（``U``）；
      - MATLAB ``char``：**uint16 码点**数组（``MATLAB_class='char'``）；
      - MATLAB 以 UTF-8 字节存入（``MATLAB_int_decode == 1``）。
    """
    try:
        if ds.dtype.kind in ("S", "U"):
            arr = np.asarray(raw).ravel()
            if arr.size and arr.dtype.kind == "S":
                return b"".join(arr.tolist()).decode("utf-8", "replace").strip("\x00")
            return "".join(str(x) for x in arr.tolist()).strip("\x00")

        if ds.dtype.kind in ("u", "i"):
            arr = np.asarray(raw).ravel()
            if not arr.size:
                return ""
            encoding = ds.attrs.get("MATLAB_int_decode")
            if is_matlab and encoding == 1:
                return arr.astype(np.uint8).tobytes().decode("utf-8", "replace").strip("\x00")
            return "".join(chr(int(c)) for c in arr if 0 < int(c) < 0x110000).strip("\x00")
    except Exception:                              # noqa: BLE001
        return None
    return None


# ---------------------------------------------------------------------------
# 杂项
# ---------------------------------------------------------------------------

def _short_exc(exc: BaseException) -> str:
    """把底层异常压成一句人话，避免把 OSError traceback 直接甩给用户。"""
    text = str(exc).strip() or exc.__class__.__name__
    return text if len(text) <= 180 else text[:177] + "..."
