"""Figure 1: the family-contract editing loop, drawn in the style of the TRV overview figure.

Single-column, black rounded boxes, light-blue fill for this work, white for reused modules,
a four-point star on AI modules, document icons for files, straight black arrows. Not an outcome plot.
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon

ROOT = Path(__file__).resolve().parents[1]
INK = '#111111'
BLUE = '#cfe0f3'
WHITE = '#ffffff'


def star(ax, x, y, r=2.1):
    pts = []
    for k in range(8):
        ang = 3.14159 / 2 + k * 3.14159 / 4
        rad = r if k % 2 == 0 else r * .38
        pts.append((x + rad * __import__('math').cos(ang), y + rad * __import__('math').sin(ang)))
    ax.add_patch(Polygon(pts, closed=True, facecolor=INK, edgecolor=INK, lw=.6, zorder=6))


def box(ax, x, y, w, h, title, sub=None, fill=WHITE, ai=False, title_size=7.2, sub_size=6.0):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=1.6', linewidth=1.5,
                                edgecolor=INK, facecolor=fill, zorder=3))
    if sub:
        two = '\n' in sub
        ax.text(x + w / 2, y + h * (.76 if two else .66), title, ha='center', va='center', fontsize=title_size, weight='bold', color=INK, zorder=7)
        ax.text(x + w / 2, y + h * (.33 if two else .32), sub, ha='center', va='center', fontsize=sub_size, color=INK, zorder=7, linespacing=0.95)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha='center', va='center', fontsize=title_size, weight='bold', color=INK, zorder=7)
    if ai:
        star(ax, x + .6, y + h - .4)


def doc(ax, x, y, w, h, label, fold=2.2):
    top = y + h
    ax.add_patch(Polygon([(x, y), (x, top), (x + w - fold, top), (x + w, top - fold), (x + w, y)], closed=True,
                         facecolor=WHITE, edgecolor=INK, lw=1.2, zorder=4))
    ax.plot([x + w - fold, x + w - fold, x + w], [top, top - fold, top - fold], color=INK, lw=1.0, zorder=5)
    ax.text(x + w / 2, y + h / 2 - .4, label, ha='center', va='center', fontsize=6.8, color=INK, zorder=7)


def arrow(ax, pts, label=None, lxy=None, size=5.8, style='-', ha='center', va='bottom'):
    xs, ys = zip(*pts)
    if len(pts) > 2:
        ax.plot(xs[:-1], ys[:-1], color=INK, lw=1.2, ls=style, zorder=2, solid_capstyle='round')
    ax.annotate('', xy=pts[-1], xytext=pts[-2], arrowprops=dict(arrowstyle='-|>', lw=1.2, color=INK, shrinkA=0, shrinkB=0,
                                                              mutation_scale=7, linestyle=style), zorder=2)
    if label:
        ax.text(*lxy, label, fontsize=size, color=INK, ha=ha, va=va, zorder=7, linespacing=1.0)


def main():
    plt.rcParams.update({'font.family': 'Arial', 'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, ax = plt.subplots(figsize=(3.45, 2.3))
    ax.set(xlim=(0, 100), ylim=(5.4, 87))
    ax.axis('off')
    T, S, L = 6.6, 5.6, 5.6
    # --- row 1: task, policy agent, local model
    ax.text(14, 83.6, 'Editing task', ha='center', va='center', fontsize=6.0, color=INK)
    arrow(ax, [(14, 82.2), (14, 77.3)])
    box(ax, 2, 66.5, 38, 10.8, 'Policy agent', 'Claude, GPT or local model', ai=True, title_size=T, sub_size=S)
    box(ax, 60, 66.5, 38, 10.8, 'Local model', 'SFT / DPO on family labels', fill=BLUE, ai=True, title_size=T, sub_size=S)
    arrow(ax, [(79, 77.3), (79, 81.5), (33, 81.5), (33, 77.3)], style='--')
    ax.text(56, 83.6, 'trained model becomes the policy', ha='center', va='center', fontsize=5.6, color=INK)
    # --- row 2: source file, selector, family verdict
    ax.text(7.0, 53.0, 'gLayout\nsource', ha='center', va='center', fontsize=6.0, weight='bold', color=INK, linespacing=1.0)
    doc(ax, 16, 47.0, 9.5, 12, '.py')
    arrow(ax, [(21, 66.5), (21, 59.0)], label='patch', lxy=(22.3, 62.75), ha='left', va='center', size=L)
    box(ax, 43, 48.0, 23.5, 10.8, 'Test selector', 'next z to test', fill=BLUE, title_size=T, sub_size=S)
    box(ax, 68.5, 48.0, 29.5, 10.8, 'Family verdict', 'coverage, regression', fill=BLUE, title_size=T, sub_size=S)
    arrow(ax, [(83.3, 58.8), (83.3, 66.5)], label='labels', lxy=(84.6, 62.65), ha='left', va='center', size=L)
    arrow(ax, [(43, 53.4), (36, 53.4), (36, 66.5)])
    ax.text(62, 62.6, 'next z, visible feedback', ha='center', va='center', fontsize=L, color=INK)
    # --- row 3: runtime and physical judge
    arrow(ax, [(21, 47.0), (21, 40.8)])
    box(ax, 2, 30.0, 36, 10.8, 'Generator runtime', 'anchor + 8 visible z', title_size=T, sub_size=S)
    box(ax, 46, 30.0, 52, 10.8, 'Physical judge', 'DRC, LVS, intent, RC + SPICE', title_size=T, sub_size=S)
    arrow(ax, [(38, 35.4), (46, 35.4)])
    arrow(ax, [(54.75, 40.8), (54.75, 48.0)], label='verdict on z', lxy=(56.05, 44.4), ha='left', va='center', size=L)
    arrow(ax, [(83.3, 40.8), (83.3, 48.0)])
    # --- row 4: layouts, hidden stage, legend
    for k in range(3):
        doc(ax, 9 + 3.4 * k, 11.5 - 1.1 * k, 8.5, 11, '.gds' if k == 2 else '')
    arrow(ax, [(20, 30.0), (20, 23.0)])
    ax.text(17, 7.0, 'one layout per z', ha='center', va='center', fontsize=5.8, style='italic', color=INK)
    box(ax, 46, 11.0, 30, 10.8, 'Hidden stage', '16 unseen z, once', fill=BLUE, title_size=T, sub_size=S)
    arrow(ax, [(61, 30.0), (61, 21.8)], label='final source', lxy=(62.3, 25.9), ha='left', va='center', size=L)
    ax.text(61, 7.0, 'no verdict returns to editing or training', ha='center', va='center', fontsize=5.6, style='italic', color=INK)
    # legend
    box(ax, 80, 17.6, 7.5, 4.0, '', title_size=1)
    star(ax, 80.6, 21.2, r=1.6)
    ax.text(89, 19.6, 'AI module', ha='left', va='center', fontsize=6.0, color=INK)
    box(ax, 80, 11.6, 7.5, 4.0, '', fill=BLUE, title_size=1)
    ax.text(89, 13.6, 'This work', ha='left', va='center', fontsize=6.0, color=INK)
    output = ROOT / 'paper/figures'
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ('pdf', 'png'):
        fig.savefig(output / ('family_workflow.' + suffix), bbox_inches='tight', pad_inches=0.01, dpi=300)
    plt.close(fig)
    print(output / 'family_workflow.pdf')


if __name__ == '__main__':
    main()
