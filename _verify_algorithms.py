# -*- coding: utf-8 -*-
"""
_verify_algorithms.py —— 对 analysis.py 中四个移植算法的数值自检。

运行方式：python _verify_algorithms.py

设计原则：
  1. 每条结论均须给出可复现的数值，不采用未经实测的"预期值"。
  2. 以**解析已知**的信号作为基准（AM 信号包络存在解析解），避免循环论证。
  3. 明确区分"已实现"与"数值正确"这两个不同命题。
"""
import sys
import numpy as np

sys.path.insert(0, r"D:\Desktop\VibSpec")
from analysis import (  # noqa: E402
    fir1_like, filter_2s_fir, envelope_liao, svd_liao,
    envelope_spectrum, envelope_spectrum_pipeline, emd_first_imf,
)

FS = 20000.0
OK = 0
FAIL = 0


def check(name, cond, detail=""):
    global OK, FAIL
    tag = "PASS" if cond else "FAIL"
    if cond:
        OK += 1
    else:
        FAIL += 1
    print(f"  [{tag}] {name}" + (f"  |  {detail}" if detail else ""))


print("=" * 72)
print("1. fir1_like —— 与 MATLAB fir1 的 -6dB 截止定义比对")
print("=" * 72)
from scipy.signal import freqz  # noqa: E402

for ft, fc in (("low", 500.0), ("high", 500.0)):
    b = fir1_like(180, fc / (FS / 2), ft)
    w, H = freqz(b, worN=65536, fs=FS)
    db = 20 * np.log10(np.maximum(np.abs(H), 1e-30))
    i6 = int(np.argmin(np.abs(db + 6.0)))
    check(f"{ft}pass 抽头数 = n+1",
          b.size == 181, f"len={b.size}")
    check(f"{ft}pass -6dB 落在截止频率",
          abs(w[i6] - fc) < 2.0, f"-6dB @ {w[i6]:.1f} Hz (目标 {fc})")
    if ft == "low":
        ipass = int(np.argmin(np.abs(w - 100.0)))
        istop = int(np.argmin(np.abs(w - 2000.0)))
        check("lowpass 通带增益 ≈ 0 dB", abs(db[ipass]) < 0.5, f"{db[ipass]:.2f} dB @100Hz")
        check("lowpass 阻带 < -60 dB", db[istop] < -60, f"{db[istop]:.1f} dB @2000Hz")
    else:
        istop = int(np.argmin(np.abs(w - 100.0)))
        ipass = int(np.argmin(np.abs(w - 2000.0)))
        check("highpass 通带增益 ≈ 0 dB", abs(db[ipass]) < 0.5, f"{db[ipass]:.2f} dB @2000Hz")
        check("highpass 阻带 < -60 dB", db[istop] < -60, f"{db[istop]:.1f} dB @100Hz")

b_lp = fir1_like(180, 500 / (FS / 2), "low")
check("线性相位对称性", float(np.max(np.abs(b_lp - b_lp[::-1]))) < 1e-12,
      f"err={float(np.max(np.abs(b_lp - b_lp[::-1]))):.2e}")
b_odd = fir1_like(181, 500 / (FS / 2), "high")
check("奇数阶高通自动 +1 (MATLAB 行为)", b_odd.size == 183, f"len={b_odd.size}")

print()
print("=" * 72)
print("2. filter_2s_fir —— 端到端滤波实测")
print("=" * 72)
N = 16384
t = np.arange(N) / FS
x = 1.0 * np.sin(2 * np.pi * 100 * t) + 1.0 * np.sin(2 * np.pi * 2000 * t)
y = filter_2s_fir(x, 500.0, FS, 180, "high")
mid = y[2048:-2048]
M = mid.size
Y = np.abs(np.fft.rfft(mid * np.hanning(M))) * 2 / np.sum(np.hanning(M))
f = np.fft.rfftfreq(M, 1 / FS)
a100 = float(Y[int(np.argmin(np.abs(f - 100)))])
a2000 = float(Y[int(np.argmin(np.abs(f - 2000)))])
check("100Hz 被高通压制", a100 < 0.01, f"幅值={a100:.5f} (输入1.0)")
check("2000Hz 通过且增益≈1", 0.95 < a2000 < 1.02, f"幅值={a2000:.4f} (输入1.0)")

try:
    filter_2s_fir(x[:100], 500.0, FS, 180, "high")
    check("短信号长度保护(应抛错)", False, "未抛错")
except ValueError as e:
    check("短信号长度保护(应抛错)", True, str(e)[:46] + "...")
try:
    filter_2s_fir(x, 12000.0, FS, 180, "high")
    check("超过 Nyquist 保护(应抛错)", False, "未抛错")
except ValueError as e:
    check("超过 Nyquist 保护(应抛错)", True, str(e)[:46] + "...")

print()
print("=" * 72)
print("3. envelope_liao —— 对解析已知 AM 信号求包络")
print("=" * 72)
fm, fc_, m = 20.0, 2000.0, 0.5
xam = (1 + m * np.cos(2 * np.pi * fm * t)) * np.cos(2 * np.pi * fc_ * t)
up, down = envelope_liao(xam)
theo = np.abs(1 + m * np.cos(2 * np.pi * fm * t))
sl = slice(500, -500)
err = float(np.max(np.abs(up[sl] - theo[sl])))
check("包络长度保持", up.size == N, f"{up.size} vs {N}")
check("上包络与解析解一致 (中段)", err < 1e-6, f"max err = {err:.2e}")
ef, ea = envelope_spectrum(up, FS, num=None, lfr=None)
k = 1 + int(np.argmax(ea[1:800]))
check("包络谱主峰 ≈ 调制频率 20Hz", abs(ef[k] - fm) < 2.0,
      f"峰 @ {ef[k]:.2f} Hz (bin={FS / N:.3f} Hz)")

print()
print("=" * 72)
print("4. svd_liao —— 恒等重构与分组重构")
print("=" * 72)
N2 = 1024
t2 = np.arange(N2) / FS
xs = 1.0 * np.sin(2 * np.pi * 300 * t2) + 0.2 * np.sin(2 * np.pi * 2500 * t2)
y_all = svd_liao(xs, 28, list(range(1, 29)), 0)
err_all = float(np.max(np.abs(y_all - xs)))
check("全奇异值重构 = 原信号 (逐点)", err_all < 1e-9, f"max err = {err_all:.2e}")
y3 = svd_liao(xs, 28, [1, 2, 3], 0)
c = float(np.corrcoef(xs[100:-100], y3[100:-100])[0, 1])
check("前3个奇异值重构相关性 > 0.98", c > 0.98, f"corr = {c:.4f}")
check("重构长度保持", y3.size == N2, f"{y3.size} vs {N2}")
y_recon, sv = svd_liao(xs, 28, [1, 2], 1)
check("Flag=1 返回奇异值谱", sv.size == 28, f"len={sv.size}")
check("奇异值降序排列", bool(np.all(np.diff(sv) <= 1e-12)), f"top3={np.round(sv[:3], 3)}")
y_ed = svd_liao(xs, 800, [1, 2, 3], 0)
check("ED>Num/2 自动修正", y_ed.size == N2, f"len={y_ed.size}")

print()
print("=" * 72)
print("5. 完整链路 envelope_spectrum_pipeline (fir / svd / raw)")
print("=" * 72)
res = envelope_spectrum_pipeline(xam, FS, fc=500.0, n_fir=180, lfr=800, method="fir")
check("fir 链路输出字段完整",
      all(k in res for k in ("filtered", "up", "down", "env_freq", "env_amp")),
      f"keys={sorted(res.keys())}")
# MATLAB 原文是 plot(sf(2:Lfr), ODaF2(2:Lfr)) —— 跳过直流后正好 Lfr-1 = 799 点
check("fir 链路包络谱长度 = Lfr-1 (跳过直流，对齐 sf(2:Lfr))",
      res["env_freq"].size == 799, f"{res['env_freq'].size}")
check("包络谱起点不是 0 Hz（已跳直流）",
      float(res["env_freq"][0]) > 0, f"首点={float(res['env_freq'][0]):.3f} Hz")
res_svd = envelope_spectrum_pipeline(xam, FS, lfr=800, method="svd")
check("svd 链路可运行", res_svd["up"].size == xam.size,
      f"up.size={res_svd['up'].size}")
res_raw = envelope_spectrum_pipeline(xam, FS, lfr=800, method="raw")
check("raw 链路 = 直接取包络", float(np.max(np.abs(res_raw["up"] - up))) < 1e-9,
      "与 envelope_liao 一致")

print()
print("=" * 72)
print("6. 补充能力：带通/带阻 + first_bin + EMD 可选依赖")
print("=" * 72)
for ft, flo, fhi in (("bandpass", 500.0, 3000.0), ("stop", 500.0, 3000.0)):
    bb = fir1_like(180, [flo / (FS / 2), fhi / (FS / 2)], ft)
    w2, H2 = freqz(bb, worN=65536, fs=FS)
    db2 = 20 * np.log10(np.maximum(np.abs(H2), 1e-30))
    mid = float(db2[int(np.argmin(np.abs(w2 - 1500.0)))])       # 通带中心
    edges = [float(db2[int(np.argmin(np.abs(w2 - f0)))])        # -6dB 截止点
             for f0 in (flo, fhi)]
    outside = min(float(db2[int(np.argmin(np.abs(w2 - 50.0)))]),
                  float(db2[int(np.argmin(np.abs(w2 - 9000.0)))]))
    if ft == "bandpass":
        check("bandpass 通带增益≈0dB (|err|<=1)",
              abs(mid) <= 1.0, f"1500Hz={mid:+.2f} dB")
        check("bandpass 截止点≈-6dB",
              all(abs(e + 6.0) <= 1.5 for e in edges),
              f"500/3000Hz={edges[0]:+.2f}/{edges[1]:+.2f} dB")
        check("bandpass 阻带 < -60 dB", outside < -60, f"{outside:.1f} dB")
    else:
        check("stop 通带增益≈0dB (|err|<=1)",
              abs(outside) <= 1.0, f"50/9000Hz={outside:+.2f} dB")
        check("stop 截止点≈-6dB",
              all(abs(e + 6.0) <= 1.5 for e in edges),
              f"500/3000Hz={edges[0]:+.2f}/{edges[1]:+.2f} dB")
        check("stop 阻带 < -40 dB", mid < -40, f"{mid:.1f} dB")
check("带通抽头数 = n+1", fir1_like(180, [0.05, 0.3], "bandpass").size == 181)

ef0, ea0 = envelope_spectrum(up, FS, num=None, lfr=800, first_bin=0)
ef1, ea1 = envelope_spectrum(up, FS, num=None, lfr=800, first_bin=1)
check("first_bin=0 从 0Hz 起", abs(float(ef0[0])) < 1e-9 and ef0.size == 800,
      f"len={ef0.size} f0={float(ef0[0]):.3f}")
check("first_bin=1 跳过直流", float(ef1[0]) > 0 and ef1.size == 799,
      f"len={ef1.size} f0={float(ef1[0]):.3f}")
check("两种起点的谱值一致（只是切片不同）",
      abs(float(ea1[0]) - float(ea0[1])) < 1e-9,
      f"{float(ea1[0]):.6g} vs {float(ea0[1]):.6g}")

# EMD 可选依赖：未安装时应抛 ImportError 且带安装指引，而不是无声失败
try:
    from PyEMD import EMD  # noqa: F401
    _has_emd = True
except Exception:
    _has_emd = False
if _has_emd:
    y_emd = emd_first_imf(xam[:4096])
    check("EMD 第1个IMF 长度正确", y_emd.size == 4096, f"{y_emd.size}")
else:
    try:
        emd_first_imf(xam[:4096])
        check("EMD 未安装时应抛 ImportError", False, "未抛出异常")
    except ImportError as e:
        check("EMD 未安装时抛出带指引的 ImportError",
              "EMD-signal" in str(e), str(e)[:52] + "...")
    print("     （当前环境未装 PyEMD，属预期；exe 构建环境已包含）")

print()
print("=" * 72)
print(f"结果：PASS {OK} 项，FAIL {FAIL} 项")
print("=" * 72)
sys.exit(1 if FAIL else 0)
