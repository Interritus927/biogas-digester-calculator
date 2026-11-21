"""Schematic drawing of the digester, scaled to the calculated volumes.
The standard (PAES 413:2001) gives volumes, not dimensions, so the shape
uses an ASSUMED proportion (height/diameter, or length/diameter for the
balloon type). This is a schematic, not a structural design.
"""
import math

from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Rectangle

SLURRY = "#8d6e3f"
GAS = "#cfe8f3"
WALL = "#333333"
PIPE = "#555555"


def _segment_fraction(h_over_d):
    """Fraction of a circle's area below a horizontal line at height h/D."""
    r = 0.5
    h = h_over_d
    if h <= 0:
        return 0.0
    if h >= 1:
        return 1.0
    theta = 2 * math.acos((r - h) / r)
    return (r * r / 2 * (theta - math.sin(theta))) / (math.pi * r * r)


def _level_for_fraction(frac):
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _segment_fraction(mid) < frac:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _vertical(ax, res, ratio):
    """Fixed-type or floating-type vertical cylinder (cross-section)."""
    dtype = res["digester_type"]
    Vd = res["Vd"]
    if dtype == "fixed":
        V = res["Vtot"]
    else:
        V = Vd
    D = (4 * V / (math.pi * ratio)) ** (1 / 3)
    H = ratio * D
    h_slurry = Vd / (math.pi * D * D / 4)
    gas_h = H - h_slurry if dtype == "fixed" else 0.0

    ax.add_patch(Rectangle((0, 0), D, h_slurry, fc=SLURRY, ec="none"))
    if dtype == "fixed":
        ax.add_patch(Rectangle((0, h_slurry), D, gas_h, fc=GAS, ec="none"))
        top = H
        ax.text(D / 2, h_slurry + gas_h / 2, "Gas", ha="center", va="center", fontsize=10)
    else:
        top = h_slurry
        Vg = res.get("Vg")
        if Vg and Vg > 0:
            hg = Vg / (math.pi * D * D / 4)
            ax.add_patch(Rectangle((-0.04 * D, h_slurry + 0.02 * D), 1.08 * D, hg,
                                   fc=GAS, ec=WALL, lw=1.5))
            ax.text(D / 2, h_slurry + 0.02 * D + hg / 2, "Floating gas holder",
                    ha="center", va="center", fontsize=9)
            top = h_slurry + 0.02 * D + hg
    ax.add_patch(Rectangle((0, 0), D, H if dtype == "fixed" else h_slurry,
                           fc="none", ec=WALL, lw=2))
    ax.text(D / 2, h_slurry / 2, f"Slurry\n{Vd:.1f} m³", ha="center", va="center",
            color="white", fontsize=11, fontweight="bold")

    # inlet / outlet / gas pipe
    ax.plot([-0.45 * D, 0], [0.15 * h_slurry] * 2, color=PIPE, lw=4)
    ax.annotate("Inlet", (-0.45 * D, 0.15 * h_slurry), xytext=(0, 8),
                textcoords="offset points", ha="left", fontsize=9)
    ax.plot([D, 1.45 * D], [0.9 * h_slurry] * 2, color=PIPE, lw=4)
    ax.annotate("Outlet", (1.45 * D, 0.9 * h_slurry), xytext=(0, 8),
                textcoords="offset points", ha="right", fontsize=9)
    ax.plot([D / 2] * 2, [top, top * 1.08], color=PIPE, lw=4)
    ax.annotate("Biogas", (D / 2, top * 1.08), xytext=(0, 6),
                textcoords="offset points", ha="center", fontsize=9)

    ax.plot([0, D], [-0.07 * H] * 2, color="black", lw=1)
    ax.text(D / 2, -0.07 * H, f"D = {D:.2f} m", ha="center", va="top", fontsize=9)
    ax.set_xlim(-0.6 * D, 1.6 * D)
    ax.set_ylim(-0.2 * H, top * 1.25)
    return D, H


def _balloon(ax, res, ratio):
    """Balloon type: horizontal tubular bag (side view)."""
    V = res["Vtot"]
    Vd = res["Vd"]
    D = (4 * V / (math.pi * ratio)) ** (1 / 3)
    L = ratio * D
    outline = FancyBboxPatch((0, 0), L, D, boxstyle=f"round,pad=0,rounding_size={D / 2}",
                             fc=GAS, ec=WALL, lw=2)
    ax.add_patch(outline)
    level = _level_for_fraction(Vd / V) * D
    liquid = Rectangle((0, 0), L, level, fc=SLURRY, ec="none")
    ax.add_patch(liquid)
    liquid.set_clip_path(outline)
    ax.add_patch(FancyBboxPatch((0, 0), L, D, boxstyle=f"round,pad=0,rounding_size={D / 2}",
                                fc="none", ec=WALL, lw=2))
    ax.text(L / 2, level / 2, f"Slurry\n{Vd:.1f} m³", ha="center", va="center",
            color="white", fontsize=11, fontweight="bold")
    ax.text(L / 2, level + (D - level) / 2, "Gas", ha="center", va="center", fontsize=10)
    ax.plot([-0.4 * D, 0.05 * D], [0.3 * D] * 2, color=PIPE, lw=4)
    ax.annotate("Inlet", (-0.4 * D, 0.3 * D), xytext=(0, 8), textcoords="offset points",
                ha="left", fontsize=9)
    ax.plot([L - 0.05 * D, L + 0.4 * D], [0.3 * D] * 2, color=PIPE, lw=4)
    ax.annotate("Outlet", (L + 0.4 * D, 0.3 * D), xytext=(0, 8), textcoords="offset points",
                ha="right", fontsize=9)
    ax.plot([L / 2] * 2, [D, 1.25 * D], color=PIPE, lw=4)
    ax.annotate("Biogas", (L / 2, 1.25 * D), xytext=(0, 6), textcoords="offset points",
                ha="center", fontsize=9)
    ax.text(L / 2, -0.12 * D, f"L = {L:.2f} m,  D = {D:.2f} m", ha="center", va="top",
            fontsize=9)
    ax.set_xlim(-0.6 * D, L + 0.6 * D)
    ax.set_ylim(-0.5 * D, 1.7 * D)
    return D, L


def digester_figure(res, ratio):
    """Returns a matplotlib Figure. `ratio` = H/D (vertical types) or L/D (balloon)."""
    fig = Figure(figsize=(6.5, 5))
    ax = fig.subplots()
    ax.set_aspect("equal")
    ax.axis("off")
    dtype = res["digester_type"]
    if dtype == "balloon":
        _balloon(ax, res, ratio)
        shape = f"L/D = {ratio:g}"
    else:
        _vertical(ax, res, ratio)
        shape = f"H/D = {ratio:g}"
    fig.suptitle(f"{dtype.capitalize()} digester (schematic, {shape} assumed)", fontsize=11)
    fig.tight_layout()
    return fig