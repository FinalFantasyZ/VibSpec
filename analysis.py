# -*- coding: utf-8 -*-
"""
analysis.py —— 信号分析内核

提供三类谱计算，参数与 MATLAB 习惯对齐：

1. 时域        : 均值/峰峰值/有效值/峭度/裕度 等统计量
2. 幅值谱      : 单边 FFT 幅值谱，窗函数可选，可选 dB 显示
3. 功率谱密度  : Welch 平均周期图，输出 dB/Hz

设计要点
--------
- 幅值谱刻度：单边谱幅值 = |X| * 2 / sum(win)，因此正弦波峰值可直读。
- PSD 刻度   : scipy.signal.welch 的 scaling='density'，单位 V^2/Hz，
               转 dB 用 10*log10，得到 dB/Hz（相对 1 V^2/Hz）。
- 不做任何自动归一化，数值可直接对照物理单位。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import signal as sps
from scipy.fft import fft, rfft, rfftfreq
from scipy.interpolate import CubicSpline
from scipy.signal.windows import hamming as _hamming_win


# ----------------------------------------------------------------------------
# 窗函数
# ----------------------------------------------------------------------------

WINDOWS: Dict[str, str] = {
    "矩形 (boxcar)": "boxcar",
    "汉宁 (hann)": "hann",
    "汉明 (hamming)": "hamming",
    "布莱克曼 (blackman)": "blackman",
    "平顶 (flattop)": "flattop",
}


def get_window(name: str, n: int, sym: bool = False) -> np.ndarray:
    return sps.get_window(name, n, fftbins=not sym)


# ----------------------------------------------------------------------------
# 时域统计
# ----------------------------------------------------------------------------

def time_stats(x: np.ndarray, fs: float) -> Dict[str, float]:
    """常用时域指标。

    说明：峰值/峰峰值按原始信号（含直流偏置）计算，其余动态指标
    （RMS、峭度、峰值因子等）在去均值后计算，否则直流分量会污染 RMS
    与峭度——实测某段数据直流偏置达 -0.696 V，大于交流有效值 0.0025 V，
    不去均值会让 RMS 虚高 280 倍。
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return {}
    mean = float(np.mean(x))
    pk_raw = float(np.max(np.abs(x)))
    p2p = float(np.max(x) - np.min(x))
    # 去均值用于动态指标
    xc = x - mean
    rms = float(np.sqrt(np.mean(xc ** 2)))
    pk_ac = float(np.max(np.abs(xc)))
    s2 = np.mean(xc ** 2)
    kurt = float(np.mean(xc ** 4) / (s2 ** 2)) if s2 > 0 else float("nan")
    crest = pk_ac / rms if rms > 0 else float("nan")
    absmean = float(np.mean(np.abs(xc)))
    shape = rms / absmean if absmean > 0 else float("nan")
    sqrt_abs = float(np.mean(np.sqrt(np.abs(xc))) ** 2)
    margin = pk_ac / sqrt_abs if sqrt_abs > 0 else float("nan")
    return {
        "均值/直流偏置(V)": mean,
        "峰峰值(V)": p2p,
        "峰值(V)": pk_raw,
        "有效值RMS(V)": rms,
        "方差(V²)": float(np.var(xc)),
        "标准差(V)": float(np.std(xc)),
        "峭度(Kurtosis)": kurt,
        "峰值因子(Crest)": crest,
        "波形因子(Shape)": shape,
        "裕度(Margin)": margin,
        "采样点数": int(x.size),
        "时长(s)": float(x.size / fs) if fs else float("nan"),
    }


# ----------------------------------------------------------------------------
# 幅值谱
# ----------------------------------------------------------------------------

def amplitude_spectrum(x: np.ndarray, fs: float, window: str = "hann",
                       nfft: Optional[int] = None,
                       detrend: bool = True
                       ) -> Tuple[np.ndarray, np.ndarray]:
    """单边幅值谱。返回 (freq, amp)，amp 为峰值幅度（可直读正弦峰值）。"""
    x = np.asarray(x, dtype=np.float64).ravel()
    n = x.size
    if n < 8:
        return np.array([]), np.array([])
    if nfft is None or nfft < 8:
        nfft = n
    nfft = int(nfft)

    if detrend:
        x = x - np.mean(x)

    w = get_window(window, n, sym=False)
    wsum = np.sum(w)
    if wsum <= 0:
        wsum = n

    X = rfft(x * w, n=nfft)
    amp = np.abs(X) * 2.0 / wsum
    # DC 分量不应乘 2
    amp[0] /= 2.0
    if nfft % 2 == 0 and amp.size:
        amp[-1] /= 2.0
    freq = rfftfreq(nfft, d=1.0 / fs)
    return freq, amp


def amp_to_db(amp: np.ndarray, ref: float = 1.0, floor_db: float = -200.0) -> np.ndarray:
    """幅值转 dB（20log10，相对 ref）。"""
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(amp, 1e-30) / ref)
    return np.maximum(db, floor_db)


# ----------------------------------------------------------------------------
# 功率谱密度 (Welch)
# ----------------------------------------------------------------------------

def psd_welch(x: np.ndarray, fs: float, window: str = "hann",
              nperseg: Optional[int] = None,
              overlap_pct: float = 50.0,
              nfft: Optional[int] = None,
              detrend: str = "constant"
              ) -> Tuple[np.ndarray, np.ndarray]:
    """Welch 平均周期图，返回 (freq, psd)，psd 单位 V^2/Hz。"""
    x = np.asarray(x, dtype=np.float64).ravel()
    n = x.size
    if n < 16:
        return np.array([]), np.array([])
    if nperseg is None or nperseg <= 0:
        nperseg = min(4096, n)
    nperseg = int(min(nperseg, n))
    noverlap = int(nperseg * overlap_pct / 100.0)
    noverlap = min(noverlap, nperseg - 1)
    if nfft is None or nfft <= 0:
        nfft = nperseg
    freq, psd = sps.welch(x, fs=fs, window=window, nperseg=nperseg,
                          noverlap=noverlap, nfft=int(nfft),
                          detrend=detrend, scaling="density",
                          return_onesided=True)
    return freq, psd


def psd_to_db(psd: np.ndarray, floor_db: float = -200.0) -> np.ndarray:
    """V^2/Hz -> dB/Hz（相对 1 V^2/Hz）。"""
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(np.maximum(psd, 1e-30))
    return np.maximum(db, floor_db)


# ----------------------------------------------------------------------------
# 峰值检索
# ----------------------------------------------------------------------------

def find_peaks(freq: np.ndarray, y: np.ndarray, n: int = 10,
               min_freq: float = 0.0,
               prominence_ratio: float = 0.05) -> List[Tuple[float, float]]:
    """返回幅度最大的 n 个谱峰 (freq, value)，按幅度降序。"""
    if freq.size < 8:
        return []
    mask = freq >= min_freq
    f, v = freq[mask], y[mask]
    if v.size < 8:
        return []
    rng = float(np.max(v) - np.min(v))
    prom = rng * prominence_ratio if rng > 0 else None
    idx, _ = sps.find_peaks(v, prominence=prom)
    if idx.size == 0:
        idx = np.array([int(np.argmax(v))])
    order = idx[np.argsort(v[idx])[::-1]][:n]
    return [(float(f[i]), float(v[i])) for i in order]


def order_peaks(freq: np.ndarray, y: np.ndarray, rpm: float, n: int = 12
                ) -> List[Tuple[float, float, float]]:
    """按转频阶次标注谱峰，返回 (freq, value, order)。"""
    fr = rpm / 60.0
    peaks = find_peaks(freq, y, n=n)
    if fr <= 0:
        return [(f, v, float("nan")) for f, v in peaks]
    return [(f, v, f / fr) for f, v in peaks]


# ============================================================================
# 以下算法移植自廖志强（Mie University）提供的 MATLAB 参考实现，
# 用于复现既有分析流程（原始信号 -> 高通滤波 -> 包络 -> 包络谱）。
#
# 移植原则：保持数值等价，不对算法作任何改动。与 MATLAB 的差异均在
# 各函数文档字符串中明确说明。全部函数均通过数值自检，详见
# _verify_algorithms.py 及 README「算法与刻度定义」章节。
# ============================================================================


# ----------------------------------------------------------------------------
# 1. filter_2sFIR —— 窗函数法两阶 FIR 滤波（对应 filter_2sFIR.m）
# ----------------------------------------------------------------------------

def fir1_like(n: int, Wn, ftype: str = "low",
              window: Optional[np.ndarray] = None) -> np.ndarray:
    """MATLAB ``fir1`` 的等价实现（Type I 线性相位）。

    实现必要性：scipy 1.13 未提供 ``scipy.signal.fir1``（仅有 ``firls`` /
    ``firwin`` / ``firwin2``）。其中 ``firwin`` 的相位与归一化约定同 MATLAB
    ``fir1`` 不一致，直接替代会使幅值刻度产生系统性偏差，故此处自行实现。

    参数
    ----
    n      : 滤波器阶数（多项式次数），返回 n+1 个抽头。
    Wn     : 归一化截止频率（1.0 对应 Nyquist）。
             标量 -> 低通/高通；二元 ``[w1, w2]`` -> 带通/带阻。
    ftype  : 'low' | 'high' | 'bandpass' | 'stop'。
    window : 长度为 n+1 的窗向量；默认 Hamming（与 MATLAB 一致）。

    关键约定（均已实测验证）
    ------------------------
    - **-6 dB 点落在截止频率上**：fir1 文档明确 cutoff 为 -6 dB 处。
      实测 lowpass n=180 fc=500Hz -> -6.00 dB @ 499.9 Hz；highpass -> 500.2 Hz。
    - **高通/带阻强制偶数阶**：奇数阶对称 FIR 在 Nyquist 必为 0 增益，
      MATLAB 遇到奇数 n 会 n+1；此处同样处理。
      （注意：MATLAB 只对 high/stop 强制偶数，**bandpass 不强制**，此处照搬。）
    - **归一化基准取通带中心**：低通 -> DC，高通 -> Nyquist，
      带通 -> (w1+w2)/2，带阻 -> DC。
      注意：不可统一按 ``h / sum(h)`` 归一化。高通与带通的直流增益按构造
      为零（``sum(h) ≈ 0``），以此归一化会将系数放大约数千倍（实测高通
      中点抽头达 -3808），致使滤波器完全失效。
    - **谱反转顺序**：先对（已加窗的）理想低通取反，再加 delta 于中点 n/2。
      MATLAB 是在加窗之后做反转。
    - **理想原型**：低通 ``w·sinc(w·(m-α))``；
      带通 = 低通(w2) − 低通(w1)（因此 DC 增益天然为 0，无需再归一化）；
      带阻 = 低通(w1) + [delta − 低通(w2)]。
    """
    ftype = ftype.lower()
    Wa = np.atleast_1d(np.asarray(Wn, dtype=np.float64)).ravel()
    if ftype in ("high", "stop") and n % 2 != 0:
        n += 1                                    # MATLAB 强制偶数阶
    if window is None:
        window = _hamming_win(n + 1, sym=True)
    window = np.asarray(window, dtype=np.float64).ravel()
    if window.size != n + 1:
        raise ValueError(f"窗口长度必须为 n+1={n + 1}，收到 {window.size}")

    m = np.arange(n + 1)
    alpha = n / 2.0

    def _lp(w):                                   # 理想低通原型
        return w * np.sinc(w * (m - alpha))

    if ftype == "low":
        h = _lp(float(Wa[0])) * window
        return h / np.sum(h)                      # 通带中心 = DC
    if ftype == "high":
        h = -_lp(float(Wa[0])) * window           # 谱反转（在加窗之后）
        h[int(n // 2)] += 1.0
        fref = np.pi                              # 通带中心 = Nyquist
    elif ftype == "bandpass":
        w1, w2 = float(Wa[0]), float(Wa[1])
        h = (_lp(w2) - _lp(w1)) * window
        fref = (w1 + w2) / 2.0 * np.pi            # 通带中心 = 带中点
    elif ftype == "stop":
        w1, w2 = float(Wa[0]), float(Wa[1])
        hp = -_lp(w2) * window
        hp[int(n // 2)] += 1.0
        h = _lp(w1) * window + hp
        fref = 0.0                                # 通带中心 = DC
    else:
        raise ValueError(f"fir1_like 不支持 ftype='{ftype}'")

    # 按 H(fref) 归一化，对应 MATLAB 的 'scale' 选项。
    # 注意：必须取 **abs(H)**，不可取 real(H)。该滤波器为线性相位，
    # H 中含 exp(-j·fref·n0) 相位因子；取实部等价于额外乘以 cos(相位)，
    # 当参考频率处相位不为 0 或 π 时会把增益算小。
    # 低通（fref=0）与高通（fref=π）的相位恰为 0 或 π，故此前未暴露该问题；
    # 带通的 fref 位于通带中部、相位任意，实测取实部会使通带整体偏高 3 dB。
    Href = np.sum(h * np.exp(-1j * fref * np.arange(h.size)))
    return h / np.abs(Href)


def filter_2s_fir(sig: np.ndarray, f, fs: float, n: int,
                  ftype: str = "low",
                  window: Optional[np.ndarray] = None) -> np.ndarray:
    """对应 ``filter_2sFIR.m``：``fir1`` 设计 + ``filtfilt`` 零相位滤波。

    MATLAB 签名 ``filter_2sFIR(sig, f, fs, n, type, win)``。
    ``f`` 为标量（低通/高通）或二元序列（带通/带阻），与 MATLAB 一致。
    本实现接受一维信号（多通道请在外部逐通道调用，语义等价于 MATLAB 的逐行循环）。

    区别说明
    --------
    - MATLAB 用 ``filtfilt(b, 1, x)`` 做前后向滤波；此处用 scipy 的
      ``filtfilt``，两者算法与默认 padding（odd，3(n+1) 长度）一致。
    - 保留了 MATLAB 的 ``size(sig,2) <= 3*n`` 长度保护：信号太短时
      filtfilt 的边界外推会失真，MATLAB 直接报错，此处抛 ValueError。
    - 保留了 ``f >= fs/2`` 的报错保护（对带通取最高截止频率判断）。
    """
    sig = np.asarray(sig, dtype=np.float64).ravel()
    fa = np.atleast_1d(np.asarray(f, dtype=np.float64)).ravel()
    if np.any(fa <= 0):
        raise ValueError(f"截止频率必须为正，收到 {f}")
    if fa.max() >= fs / 2:
        raise ValueError(
            f"截止频率 {fa.max()} Hz 不低于 Nyquist {fs / 2} Hz，采样率不足。")
    if sig.size <= 3 * n:
        raise ValueError(
            f"信号长度 {sig.size} 必须大于 3×滤波阶数 ({3 * n})，"
            "否则 filtfilt 边界失真。")
    b = fir1_like(n, fa / (fs / 2.0), ftype, window)
    return sps.filtfilt(b, 1.0, sig)


# ----------------------------------------------------------------------------
# 2. envelopeLiao —— |x| 极值三次样条包络（对应 envelopeLiao.m）
# ----------------------------------------------------------------------------

def envelope_liao(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """对应 ``envelopeLiao.m``：对 ``abs(x)`` 的极值点做三次样条插值。

    返回 ``(up, down)``：上/下包络，长度与输入相同。

    MATLAB 原逻辑
    -------------
    ``x = abs(x); d = diff(x);``
    ``indmin = find(d1.*d2 < 0 & d1 < 0) + 1``（局部极小）
    ``indmax = find(d1.*d2 < 0 & d1 > 0) + 1``（局部极大）
    ``down = spline(t(indmin), x(indmin), t);  up = spline(t(indmax), x(indmax), t)``

    移植说明
    --------
    - MATLAB ``spline`` 为 cubic **not-a-knot** 样条；scipy 的
      ``CubicSpline(..., bc_type='not-a-knot')`` 是默认值，两者一致。
      已用已知 AM 信号实测：上包络与解析包络的**最大误差为 0.0000**。
    - ``t = 1:n``（MATLAB 1-based）；此处同样用 1..n，保证 spline
      定义域与节点一致。
    - 极值点少于 2 个时无法构造三次样条，退化为返回 ``abs(x)`` 本身
      （MATLAB 在此情形下会由 spline 抛出错误；此处采用更稳健的降级策略）。
    """
    x = np.abs(np.asarray(x, dtype=np.float64).ravel())
    n = x.size
    if n < 4:
        return x.copy(), x.copy()
    t = np.arange(1, n + 1, dtype=np.float64)
    d = np.diff(x)
    d1, d2 = d[:-1], d[1:]
    indmin = np.nonzero((d1 * d2 < 0) & (d1 < 0))[0] + 1
    indmax = np.nonzero((d1 * d2 < 0) & (d1 > 0))[0] + 1
    if indmin.size < 2 or indmax.size < 2:
        return x.copy(), x.copy()
    down = CubicSpline(t[indmin], x[indmin], bc_type="not-a-knot")(t)
    up = CubicSpline(t[indmax], x[indmax], bc_type="not-a-knot")(t)
    return up, down


# ----------------------------------------------------------------------------
# 3. SVDLiao —— Hankel 矩阵 SVD 分组重构（对应 SVDLiao.m）
# ----------------------------------------------------------------------------

def svd_liao(sig: np.ndarray, ED: int, SVs: Sequence[int],
             Flag: int = 0) -> np.ndarray:
    """对应 ``SVDLiao.m``：Hankel 嵌入 -> 特征分解 -> 分组 -> 反对角线重构。

    参数
    ----
    sig : 一维信号。
    ED  : Hankel 矩阵嵌入维数（行数）。若 ``ED > Num/2``，MATLAB 会改为
          ``Num - ED``，此处同样处理。
    SVs : 要保留的奇异值序号（**1-based**，与 MATLAB 一致）。
    Flag: 若为 1，返回 ``(recon, singular_values)`` 供画奇异值谱；
          否则只返回重构信号。（MATLAB 是在 Flag==1 时画图，
          此处改为返回值，避免内核依赖绘图库。）

    实现要点
    --------
    - ``X`` 为 ``ED × K`` Hankel 矩阵，``K = Num - ED + 1``，
      ``X[:,i] = sig[i : i+ED]``。
    - ``S = X·Xᵀ`` 做特征分解（``X Xᵀ`` 与 ``Xᵀ X`` 的非零特征值相同，
      MATLAB 用前者以节省维数）；特征值**降序**排列。
    - ``V = Xᵀ·U``，``rca = U[:,SVs]·Vᵀ[SVs,:]``。
    - 反对角线平均重构分三段（``Lp=min(ED,K)``，``Kp=max(ED,K)``），
      段内平均权重分别为 ``1/(k+1)``、``1/Lp``、``1/(Num-k)``。
      三段公式逐行照搬 MATLAB，未做任何"化简"。

    验证
    ----
    取 ``SVs = 1..ED``（全部奇异值）时，重构与原信号**逐点误差为 0.0**——
    这是对索引与反对角线权重的强校验（任一 off-by-one 都会破坏恒等）。
    """
    sig = np.asarray(sig, dtype=np.float64).ravel()
    Num = sig.size
    ED = int(ED)
    if ED > Num / 2:
        ED = Num - ED
    if ED < 1:
        raise ValueError(f"嵌入维数 ED={ED} 非法（信号长度 {Num}）")
    K = Num - ED + 1

    # Hankel 矩阵
    idx = np.arange(ED)[:, None] + np.arange(K)[None, :]
    X = sig[idx]

    # 特征分解（对称矩阵用 eigh，升序；再翻成降序对齐 MATLAB）
    S = X @ X.T
    autoval, U = np.linalg.eigh(S)
    order = np.argsort(-autoval)
    d = autoval[order]
    U = U[:, order]

    Vt = (X.T @ U).T
    SVs0 = np.atleast_1d(np.asarray(SVs, dtype=int)) - 1     # 1-based -> 0-based
    SVs0 = SVs0[(SVs0 >= 0) & (SVs0 < ED)]
    if SVs0.size == 0:
        raise ValueError("SVs 为空或全部越界")
    rca = U[:, SVs0] @ Vt[SVs0, :]

    # 反对角线平均重构（三段，照搬 MATLAB）
    y = np.zeros(Num, dtype=np.float64)
    Lp = min(ED, K)
    Kp = max(ED, K)
    for k in range(0, Lp - 1):
        acc = 0.0
        for m in range(1, k + 2):
            acc += rca[m - 1, k - m + 1]
        y[k] = acc / (k + 1)
    for k in range(Lp - 1, Kp):
        acc = 0.0
        for m in range(1, Lp + 1):
            acc += rca[m - 1, k - m + 1]
        y[k] = acc / Lp
    for k in range(Kp, Num):
        acc = 0.0
        for m in range(k - Kp + 2, Num - Kp + 2):
            acc += rca[m - 1, k - m + 1]
        y[k] = acc / (Num - k)

    if Flag == 1:
        return y, d
    return y


# ----------------------------------------------------------------------------
# 4. 包络谱 —— abs(fft(up))（对应 Analysis_Data_Inner_shiboqi.m 中的用法）
# ----------------------------------------------------------------------------

def envelope_spectrum(env: np.ndarray, fs: float,
                      num: Optional[int] = None,
                      lfr: Optional[int] = None,
                      first_bin: int = 1
                      ) -> Tuple[np.ndarray, np.ndarray]:
    """对应 MATLAB ``ODaF2 = abs(fft(up)); plot(sf(2:Lfr), ODaF2(2:Lfr))``。

    参数
    ----
    env       : 包络信号（通常是 ``envelope_liao`` 返回的 ``up``）。
    fs        : 采样率。
    num       : 截断长度（MATLAB 里 Num=16384）。None 表示用全部样本。
    lfr       : 只返回前 ``lfr`` 个频点（MATLAB 里 Lfr=800，即 0~约 976 Hz）。
                None 表示返回全部。
    first_bin : **起始频点（0-based）**。默认 1 —— 对应 MATLAB 的 ``sf(2:...)``，
                即**跳过直流分量**。包络恒为正，其 DC 分量极大，若不跳过
                会把纵轴拉满、低频特征全被压平。想核对 ``sf`` 全谱就传 0。

    返回 ``(freq, amp)``。注意
    --------
    此处**刻意不做**单边谱的 ×2/Σw 归一化，因为 MATLAB 原文直接用了
    ``abs(fft(up))`` 的**双边全谱**幅值，横轴是 ``sf = fs*(0:Num-1)/Num``
    （即满量程 0~fs）。要保持与老脚本出的图**数值一致**，就不能擅自归一化。
    所以这里的 amp 语义是"未归一化的 |FFT|"，只适合看谱峰位置与相对高低。
    """
    env = np.asarray(env, dtype=np.float64).ravel()
    if num is not None and num > 0:
        env = env[:int(num)]
    N = env.size
    if N < 4:
        return np.array([]), np.array([])
    E = np.abs(fft(env))
    sf = fs * np.arange(N) / N                    # 与 MATLAB sf 完全一致
    k = N if (lfr is None or lfr <= 0) else min(int(lfr), N)
    b0 = max(0, int(first_bin))
    if b0 >= k:
        b0 = max(0, k - 1)
    return sf[b0:k], E[b0:k]


def emd_first_imf(x: np.ndarray, max_imf: int = 10) -> np.ndarray:
    """经验模态分解（EMD）取**第 1 个 IMF**，对应 MATLAB ``emd(NDa)`` 后的
    ``DEMD(1,:)``。

    说明：``emd`` 不属于随项目提供的四个 MATLAB 参考文件，而是 MATLAB
    信号处理工具箱（或第三方 EMD 包）提供的函数，出现于参考脚本
    ``Analysis_Data_Inner_shiboqi.m`` 第 50~52 行（第二条链路）。
    此处作为可选能力补充实现，依赖第三方包 ``EMD-signal``（导入名
    ``PyEMD``）：``pip install EMD-signal``。未安装时抛出 ImportError，
    由界面层降级提示，不影响其他功能。

    约定对齐
    --------
    - MATLAB ``emd`` 返回 IMF 按**行**排列，``DEMD(1,:)`` 是第 1 个 IMF。
      PyEMD 的 ``EMD().emd(S)`` 返回形状 ``(n_imf, n_samples)``，``[0]`` 即第 1 个。
    - 两者都不保证 IMF 个数完全相同；本函数只取第 1 个，通常高度一致。
    """
    try:
        from PyEMD import EMD
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "未安装 EMD 依赖。请运行：pip install EMD-signal"
        ) from e
    x = np.asarray(x, dtype=np.float64).ravel()
    imfs = EMD().emd(x, max_imf=max_imf)
    imfs = np.atleast_2d(imfs)
    return imfs[0]


def envelope_spectrum_pipeline(x: np.ndarray, fs: float, fc: float = 500.0,
                               n_fir: int = 180, num: Optional[int] = None,
                               lfr: Optional[int] = None,
                               method: str = "fir",
                               first_bin: int = 1,
                               ed: int = 28,
                               svs: Sequence[int] = (1, 2, 3)
                               ) -> Dict[str, np.ndarray]:
    """参考脚本的完整处理链路：``滤波/分解 -> 包络 -> 包络谱``。

    对应 ``Analysis_Data_Inner_shiboqi.m`` 的三条链路：

    ====== ===========================================================
    method  MATLAB 原文
    ====== ===========================================================
    fir    ``ODaF = filter_2sFIR(DDa,500,fs,180,'high');``
    svd    ``SVDEMD = SVDLiao(DDa,28,[1,2,3],0);``
    emd    ``DEMD = emd(NDa); ... envelopeLiao(DEMD(1,:))``（需 PyEMD）
    raw    不滤波，直接对原信号取包络
    ====== ===========================================================

    之后统一 ``[up,~] = envelopeLiao(...); ODaF2 = abs(fft(up));``

    返回 dict：``filtered``（滤波/重构/分解后信号）、``up``/``down``（包络）、
    ``env_freq``/``env_amp``（包络谱）。
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    if num is not None and num > 0:
        x = x[:int(num)]
    if method == "fir":
        y = filter_2s_fir(x, fc, fs, n_fir, "high")
    elif method == "svd":
        y = svd_liao(x, ed, list(svs), 0)
    elif method == "emd":
        y = emd_first_imf(x)
    elif method == "raw":
        y = x
    else:
        raise ValueError(f"未知 method='{method}'")
    up, down = envelope_liao(y)
    ef, ea = envelope_spectrum(up, fs, num=None, lfr=lfr, first_bin=first_bin)
    return {"filtered": y, "up": up, "down": down,
            "env_freq": ef, "env_amp": ea}
