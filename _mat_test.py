# -*- coding: utf-8 -*-
"""
_mat_test.py —— MAT 读取兼容性与多通道回归测试

覆盖本次扩展的每个分支，确保「不再因为一种写法打不开文件」：
  1. 实测故障文件（DL950 导出，含坏 FFT 变量）—— 关键回归
  2. MATLAB v5 多通道 / 官方 savemat 文件
  3. MATLAB v7.3（HDF5）+ 原生 HDF5（无 MATLAB 属性）
  4. 通道命名变体：CH01 / Chan2 / Channel_3 / AI4 / 无编号 Waveform / 结构体
  5. 坏文件：空文件、未知格式、截断文件、只有坏变量的文件
  6. 不应被当成通道的变量：fs / rpm / label / 时间轴
  7. 采样率字段变体：capture_fs / SamplingRate / fs
  8. 多通道等长 / 不等长

运行方式：python _mat_test.py
退出码 0 = 全部通过。

说明：第 1 项需要真实样本文件 TEST_DIESEL_0015.MAT 存在；不存在时跳过并计入 SKIP，
不视为失败（该文件属用户数据，不在仓库内）。
"""

import os
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np                                     # noqa: E402
from scipy.io import savemat                           # noqa: E402

import loader                                          # noqa: E402
import mat_reader                                      # noqa: E402

OK = 0
FAIL = 0
SKIP = 0

REAL_15 = r"D:\Desktop\示波器\TEST_DIESEL_0015.MAT"


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  |  {detail}")


def skip(name, detail=""):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}  |  {detail}")


# ---------------------------------------------------------------------------
# 构造各种「厂商写法」的 MAT 文件
# ---------------------------------------------------------------------------

def write_v5_with_broken_variable(path, channels, extra=None):
    """手写一个 v5 文件：包含一个 miCOMPRESSED 变量，但其内容是**坏 zlib 流**。

    这正是 TEST_DIESEL_0015.MAT 的病态结构：scipy 读到坏变量就整份文件报
    ``could not read bytes``，而其它变量其实完好。
    """
    def elem(dtype, payload, pad=True):
        head = struct.pack("<II", dtype, len(payload))
        body = payload + (b"\x00" * ((8 - len(payload) % 8) % 8) if pad else b"")
        return head + body

    def matrix(name, arr):
        arr = np.asarray(arr)
        dims = struct.pack("<" + "i" * arr.ndim, *arr.shape)
        payload = (elem(6, struct.pack("<II", 6, 0))          # 数组标志
                   + elem(5, dims)                            # 维度
                   + elem(1, name.encode("ascii"))            # 变量名
                   + elem({np.dtype("f4"): 7, np.dtype("f8"): 9}[arr.dtype],
                          arr.tobytes(order="F")))
        return elem(14, payload)

    def compressed(name, arr, corrupt=True):
        """把变量写成 miCOMPRESSED，并（可选）破坏成非法 deflate 流。

        注意：破坏后的字节流里，变量名的原始 ASCII 也被压缩掉了，
        因此读取端**无法**再还原出名字——这正是需要容错读取的场景：
        名字丢了可以接受，整份文件的波形不能跟着一起丢。
        """
        inner = matrix(name, arr)
        blob = zlib.compress(inner)
        if corrupt:
            mid = len(blob) // 2
            blob = blob[:mid] + b"\x00\xff" * 8 + blob[mid + 16:]
        return elem(15, blob)

    header = (b"MATLAB 5.0 MAT-file, Platform: DL950, File Version 1.00, "
              b"Created on: 2026/07/31 17:33:54")
    header = header + b" " * (116 - len(header))
    header += b"\x00" * 8                                     # 子系统数据偏移
    header += b"\x00\x01" + b"IM"                              # 版本 + 字节序
    assert len(header) == 128, len(header)

    body = b"".join(matrix(name, arr) for name, arr in channels)
    body += compressed("FFT01", np.zeros((501, 1), dtype="f4"), corrupt=True)
    for name, arr in (extra or {}).items():
        body += matrix(name, arr)
    with open(path, "wb") as fh:
        fh.write(header + body)


def write_v5_truncated(path, channels, keep_ratio=0.55):
    """写一个正常 v5 文件，然后从中间截断，模拟拷盘中断/写盘未完成。"""
    savemat(path, {n: np.asarray(a) for n, a in channels.items()})
    data = open(path, "rb").read()
    with open(path, "wb") as fh:
        fh.write(data[:int(len(data) * keep_ratio)])


def write_hdf5(path, datasets, matlab_style=False):
    """写 v7.3 / 原生 HDF5 文件。"""
    import h5py
    with h5py.File(path, "w", userblock_size=512 if matlab_style else 0) as fh:
        for name, arr in datasets.items():
            ds = fh.create_dataset(name, data=arr)
            if matlab_style and arr.dtype.kind == "f":
                ds.attrs["MATLAB_class"] = np.bytes_(
                    b"single" if arr.dtype == np.float32 else b"double")
        if matlab_style:
            fh.create_group("#refs#")


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

def main():
    tmpd = tempfile.mkdtemp(prefix="vibspec_mat_")
    n = 4096
    t = np.arange(n) / 20000.0
    sig = np.sin(2 * np.pi * 500 * t).astype(np.float32)

    try:
        # ---------------------------------------------------------------
        print("== 1. 实测故障文件（DL950：坏 FFT 变量 + 单通道 CH02）==")
        if os.path.isfile(REAL_15):
            raw = mat_reader.load_mat_variables(REAL_15)
            check("整份文件仍可读取（旧版必报 could not read bytes）",
                  bool(raw["variables"]), f"变量 {list(raw['variables'])}")
            check("坏变量被单独跳过而非拖垮整份文件",
                  "FFT01" in raw["skipped"], f"skipped={raw['skipped']}")
            check("通道波形完整恢复",
                  "CH02" in raw["variables"]
                  and np.asarray(raw["variables"]["CH02"]).size > 40000,
                  f"N={np.asarray(raw['variables']['CH02']).size}")
            s = loader.load_any(REAL_15)
            check("经统一入口加载成功", s.n_samples > 40000,
                  f"{s.source_type} fs={s.fs:g} N={s.n_samples}")
            check("文件信息里如实提示丢了哪个变量",
                  any("FFT01" in w for w in s.warnings), f"{len(s.warnings)} 条提示")
            check("容器类型被记录", s.meta.get("MAT 容器") == "v5", str(s.meta.get("MAT 容器")))
        else:
            skip("实测文件回归（样本不在本机）", REAL_15)

        # ---------------------------------------------------------------
        print("== 2. 坏变量 + 多通道（自造，结构同 DL950）==")
        p = os.path.join(tmpd, "broken_multi.mat")
        write_v5_with_broken_variable(
            p,
            [("CH01", sig.reshape(-1, 1)), ("CH02", (0.5 * sig).reshape(-1, 1))])
        raw = mat_reader.load_mat_variables(p)
        check("坏变量不阻断读取", bool(raw["variables"]), f"{list(raw['variables'])}")
        check("多通道全部取回", set(raw["variables"]) >= {"CH01", "CH02"},
              f"{sorted(raw['variables'])}")
        s = loader.load_any(p)
        check("多通道全部导入", list(s.channels) == ["CH01", "CH02"], f"{list(s.channels)}")
        check("通道数值未串位",
              np.allclose(s.channels["CH02"], 0.5 * sig, atol=1e-6),
              "CH02 = 0.5 x CH01")
        check("坏变量被如实计入提示（名字不可恢复时说明有几个）",
              any("无法解析" in w for w in s.warnings), f"{s.warnings[:2]}")

        # ---------------------------------------------------------------
        print("== 3. MATLAB v5 官方文件（savemat）==")
        p = os.path.join(tmpd, "v5_multi.mat")
        savemat(p, {"CH01": sig.reshape(-1, 1),
                    "CH03": (0.25 * sig).reshape(-1, 1),
                    "fs": np.array([[25600.0]])})
        s = loader.load_any(p)
        check("通道名保留原始编号（不补零/去零）",
              set(s.channels) == {"CH01", "CH03"}, f"{list(s.channels)}")
        check("采样率取自文件字段", abs(s.fs - 25600.0) < 1e-6, f"fs={s.fs:g}")
        check("fs 变量未被当成通道", "fs" not in s.channels, f"{list(s.channels)}")

        # ---------------------------------------------------------------
        print("== 4. v7.3（HDF5）==")
        p = os.path.join(tmpd, "v73.mat")
        write_hdf5(p, {
            "CH01": np.linspace(-1, 1, 2048, dtype=np.float32).reshape(1, 2048),
            "CH02": np.linspace(1, -1, 2048, dtype=np.float32).reshape(1, 2048),
            "capture_fs": np.array([[51200.0]]),
            "label_cn": np.array([[ord(c) for c in "外圈点蚀"]], dtype=np.uint16),
        }, matlab_style=True)
        r = mat_reader.load_mat_variables(p)
        check("识别为 v7.3", r["format"] == "v7.3", r["format"])
        s = loader.load_any(p)
        check("v7.3 多通道全部导入", set(s.channels) == {"CH01", "CH02"},
              f"{list(s.channels)}")
        check("v7.3 采样率正确", abs(s.fs - 51200.0) < 1e-6, f"fs={s.fs:g}")
        check("v7.3 中文标签正确解码", s.meta.get("工况") == "外圈点蚀",
              repr(s.meta.get("工况")))
        check("行为数为时间、列数为通道（维度顺序未反）",
              s.n_samples == 2048, f"N={s.n_samples}")

        # ---------------------------------------------------------------
        print("== 5. 原生 HDF5（无 MATLAB 属性）==")
        p = os.path.join(tmpd, "native.h5")
        write_hdf5(p, {
            "CH01": sig.astype(np.float64).reshape(-1, 1),
            "SamplingRate": np.array([[20000.0]]),
        })
        r = mat_reader.load_mat_variables(p)
        check("原生 HDF5 也能读", bool(r["variables"]), f"format={r['format']}")
        s = loader.load_any(p)
        check("原生 HDF5 通道可导入", "CH01" in s.channels, f"{list(s.channels)}")
        check("SamplingRate 字段被识别", abs(s.fs - 20000.0) < 1e-6, f"fs={s.fs:g}")

        # ---------------------------------------------------------------
        print("== 6. 通道命名变体 ==")
        p = os.path.join(tmpd, "naming.mat")
        savemat(p, {"Chan1": sig.reshape(-1, 1),
                    "Channel_3": (0.3 * sig).reshape(-1, 1),
                    "AI4": (0.4 * sig).reshape(-1, 1),
                    "rpm": np.array([[1480.0]]),
                    "label_cn": "内圈点蚀"})
        s = loader.load_any(p)
        check("Chan1 / Channel_3 / AI4 都被识别",
              set(s.channels) == {"Chan1", "Channel_3", "AI4"}, f"{list(s.channels)}")
        check("rpm 未被当成通道", "rpm" not in s.channels, f"{list(s.channels)}")
        check("标量字符变量不报错", True, f"工况={s.meta.get('工况')!r}")

        # ---------------------------------------------------------------
        print("== 7. 无编号 & 结构体写法 ==")
        p = os.path.join(tmpd, "generic.mat")
        savemat(p, {"Waveform": sig.reshape(-1, 1)})
        s = loader.load_any(p)
        check("单个无编号波形变量被导入", s.n_samples == n, f"{list(s.channels)}")

        p = os.path.join(tmpd, "struct.mat")
        savemat(p, {"data": {"XY": np.stack([np.zeros(n), sig], axis=1),
                             "fs": np.array([[30000.0]])}})
        s = loader.load_any(p)
        check("结构体中的二维波形能取出", s.n_samples == n,
              f"{list(s.channels)} N={s.n_samples}")
        check("结构体内 fs 未当成通道", "fs" not in s.channels, f"{list(s.channels)}")

        # ---------------------------------------------------------------
        print("== 8. 不该被当成通道的变量 ==")
        p = os.path.join(tmpd, "metaonly.mat")
        savemat(p, {
            "time": np.arange(n, dtype=np.float64) / 20000.0,
            "CH01": sig.reshape(-1, 1),
            "n_samples": np.array([[n]]),
            "version": "1.0",
        })
        s = loader.load_any(p)
        check("时间轴变量不作为通道",
              list(s.channels) == ["CH01"], f"{list(s.channels)}")
        check("标量元数据不作为通道",
              not ({"n_samples", "version"} & set(s.channels)), f"{list(s.channels)}")

        # ---------------------------------------------------------------
        print("== 9. 坏文件不再给出无关报错 ==")
        p = os.path.join(tmpd, "empty.mat")
        open(p, "wb").close()
        try:
            loader.load_any(p)
            check("空文件报错", False, "未抛异常")
        except Exception as exc:                   # noqa: BLE001
            msg = str(exc)
            check("空文件给出可读原因", "空" in msg or "没有" in msg, msg[:60])

        p = os.path.join(tmpd, "junk.mat")
        with open(p, "wb") as fh:
            fh.write(b"not a mat file at all" * 40)
        try:
            loader.load_any(p)
            check("未知格式报错", False, "未抛异常")
        except Exception as exc:                   # noqa: BLE001
            msg = str(exc)
            check("未知格式说明是格式问题（而非通道缺失）",
                  ("无法识别" in msg or "格式" in msg) and "CH0" not in msg, msg[:60])

        # ---------------------------------------------------------------
        print("== 10. 截断文件的结构级兜底 ==")
        p = os.path.join(tmpd, "truncated.mat")
        write_v5_truncated(p, {"CH01": sig.reshape(-1, 1)})
        try:
            s = loader.load_any(p)
            check("截断文件尽力救回部分数据", s.n_samples > 0,
                  f"N={s.n_samples}（原 {n}）")
            check("截断时如实提示", any("截断" in w or "扫描" in w or "跳过" in w
                                        for w in s.warnings),
                  f"{s.warnings[:1]}")
        except Exception as exc:                   # noqa: BLE001
            check("截断文件给出可读原因（未崩溃）", "截断" in str(exc) or "v5" in str(exc),
                  str(exc)[:60])

        # ---------------------------------------------------------------
        print("== 11. 多通道长度不一致 ==")
        p = os.path.join(tmpd, "uneven.mat")
        savemat(p, {"CH01": sig.reshape(-1, 1),
                    "CH02": sig[: n // 2].reshape(-1, 1)})
        s = loader.load_any(p)
        check("不等长通道全部导入并给出提示",
              len(s.channels) == 2 and s.n_samples == n // 2
              and any("不一致" in w for w in s.warnings),
              f"{list(s.channels)} N={s.n_samples}")

        # ---------------------------------------------------------------
        print("== 12. sniff_type 与坏文件 ==")
        p = os.path.join(tmpd, "v5_meta.mat")
        savemat(p, {"CH01": sig.reshape(-1, 1), "capture_fs": np.array([[40000.0]])})
        check("含元数据 → blackbox_mat", loader.sniff_type(p) == "blackbox_mat",
              loader.sniff_type(p))
        p = os.path.join(tmpd, "v5_plain.mat")
        savemat(p, {"CH03": sig.reshape(-1, 1)})
        check("纯通道 → scope_mat", loader.sniff_type(p) == "scope_mat",
              loader.sniff_type(p))
        p = os.path.join(tmpd, "garbage.mat")
        with open(p, "wb") as fh:
            fh.write(b"\x00" * 4096)
        try:
            loader.sniff_type(p)
            check("坏文件 sniff 不再静默误判为纯通道", False, "未抛异常")
        except Exception:                          # noqa: BLE001
            check("坏文件 sniff 不再静默误判为纯通道", True,
                  "抛出可读异常，交给导入列表显示")
    finally:
        import shutil
        shutil.rmtree(tmpd, ignore_errors=True)

    print()
    print("=" * 64)
    print(f"结果：PASS {OK} 项，FAIL {FAIL} 项，SKIP {SKIP} 项")
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
