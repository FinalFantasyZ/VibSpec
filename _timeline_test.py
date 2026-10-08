# -*- coding: utf-8 -*-
"""
_timeline_test.py —— 时域时间轴 & 显示参数自动重绘的回归测试。

背景（老大反馈"时域横坐标和实际不一致"）：
  * `spin_t0` / `spin_tspan` 等纯显示参数原先**没有连接任何信号**，改完必须手动点
    「绘制 / 刷新」才生效，用户会以为参数没起作用；
  * 开启处理链后数据被截断到 Num 点，选「显示全程」时只覆盖这一段，容易被误判为
    "横轴与数据长度不符"。

覆盖：
  1. 「时域时长」决定横轴跨度
  2. 「时域起点」决定横轴左端
  3. 处理链开启时，时域范围以 Num 段为界
  4. 状态栏如实报出时域显示范围与处理链作用点数
  5. 纯显示参数改动后**自动重绘**（防抖）

注意：plot_all() 会 fig.clear() 重建 axes，因此每次都重新获取 ax，不能缓存。

运行方式：python _timeline_test.py    （退出码 0 = 全部通过）
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                    # noqa: E402
from PyQt5 import QtWidgets                            # noqa: E402
from PyQt5.QtTest import QTest                         # noqa: E402
from scipy.io import savemat                           # noqa: E402

import app as A                                        # noqa: E402

OK = 0
FAIL = 0
FS = 25600.0
N = 40000


def check(name, cond, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}  |  {detail}")


def main():
    global OK, FAIL
    qapp = QtWidgets.QApplication(sys.argv)
    w = A.MainWindow()

    tmpd = tempfile.mkdtemp(prefix="vibspec_timeline_")
    t = np.arange(N) / FS
    sig = (1 + 0.8 * np.sin(2 * np.pi * 25.0 * t)) * np.sin(2 * np.pi * 2000 * t)
    p = os.path.join(tmpd, "t.mat")
    savemat(p, {"CH1": sig.reshape(-1, 1).astype("float32"),
                "capture_fs": np.array([[FS]]),
                "capture_effective_fs": np.array([[FS]])})
    w._add_paths([p])
    w._check_all(True)

    def xlim(which="time"):
        return w.windows[0][which].ax.get_xlim()

    def span():
        lo, hi = xlim()
        return round(hi - lo, 4)

    print("== 1. 关闭处理链：时域时长 = 0.2 s ==")
    w.chk_pp.setChecked(False)
    w.spin_t0.setValue(0.0)
    w.spin_tspan.setValue(0.2)
    w.plot_all()
    QTest.qWait(50)
    check("横轴跨度 = 0.2 s", abs(span() - 0.2) < 1e-3, f"{span()} s")

    print("== 2. 时域起点 = 0.5 s ==")
    w.spin_t0.setValue(0.5)
    QTest.qWait(700)                       # 走自动重绘，验证防抖生效
    lo, hi = xlim()
    check("横轴 = (0.5, 0.7)", abs(lo - 0.5) < 1e-3 and abs(hi - 0.7) < 1e-3,
          f"({lo:.4f}, {hi:.4f})")

    print("== 3. 起点超出可用范围时退化为最后一段（不塌缩成一点）==")
    w.spin_t0.setValue(100.0)
    QTest.qWait(700)
    lo, hi = xlim()
    check("横轴仍有宽度", hi > lo, f"({lo:.4f}, {hi:.4f})")

    print("== 4. 开启处理链：范围以 Num 段为界 ==")
    w.spin_t0.setValue(0.0)
    w.chk_pp.setChecked(True)
    w.spin_tspan.setValue(0.0)             # 显示全程
    QTest.qWait(700)
    num = w.spin_pp_num.value()
    expect = min(num, N) / FS
    check("横轴跨度 = min(Num, N) / fs", abs(span() - expect) < 1e-3,
          f"{span()} s，期望 {expect:.4f} s（Num={num}）")

    print("== 5. 状态栏如实报出范围与处理链点数 ==")
    msg = w.statusBar().currentMessage()
    check("含时域实际范围", "时域" in msg and "~" in msg, msg[-70:])
    check("含处理链作用点数", "仅前" in msg, "（仅前 N 点）" if "仅前" in msg else msg[-70:])

    print("== 6. 纯显示参数自动重绘 ==")
    w.spin_tspan.setValue(0.3)
    QTest.qWait(700)
    check("时域时长自动生效", abs(span() - 0.3) < 1e-3, f"{span()} s")
    w.spin_fmax.setValue(3000.0)
    QTest.qWait(700)
    check("频率上限自动生效", abs(xlim("freq")[1] - 3000.0) < 1.0,
          f"{tuple(round(v, 1) for v in xlim('freq'))}")
    w.spin_ylim.setValue(-80.0)
    QTest.qWait(700)
    check("dB 下限自动生效", abs(w.windows[0]["psd"].ax.get_ylim()[0] + 80.0) < 1.0,
          f"ylim={tuple(round(v,1) for v in w.windows[0]['psd'].ax.get_ylim())}")

    print()
    print("=" * 64)
    print(f"结果：PASS {OK} 项，FAIL {FAIL} 项")
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
