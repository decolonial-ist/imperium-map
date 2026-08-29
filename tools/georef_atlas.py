#!/usr/bin/env python3
"""Автопривязка карт атласа УІФ: белые линии страницы (= современные границы,
доказано по розд. 1) совмещаются ICP с границами CShapes 2.0 (срез 2019).

Модель: пиксель@200dpi = подобие(комплексное a,b) ∘ проекция(семейство, параметры).
Перебор семейств/параметров -> инициализация подобия по ручным опорным точкам ->
усечённый ICP -> координатный спуск по параметрам проекции.

Результат: data/atlas/georef.json + диагностический оверлей в scratchpad-каталог
(--diag), печатает резидуалы. Одна рамка у всех карт атласа -> калибровка общая.
"""
import argparse
import json
import os

import numpy as np
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'atlas', 'georef.json')

# ручные опорные точки 17.08 (пиксели@200dpi -> lon/lat) — только для инициализации
CONTROL = [
    ((610, 1453), (34.0, 44.4)), ((405, 1695), (29.05, 41.15)),
    ((910, 1620), (50.3, 40.35)), ((1165, 1390), (59.6, 45.0)),
    ((580, 918), (30.3, 59.95)), ((430, 780), (25.4, 65.8)),
    ((630, 840), (31.4, 60.85)), ((650, 1435), (36.5, 45.2)),
    ((1545, 1485), (74.5, 46.2)), ((575, 585), (31.5, 69.7)),
]

R = 1.0  # сферические проекции безразмерны, масштаб забирает подобие


def forward(lon, lat, fam, p):
    """Проекция -> (x, y вверх). p: (lon0, lat0/lat1, lat2)."""
    lon = np.radians(np.asarray(lon, float))
    lat = np.radians(np.asarray(lat, float))
    lon0 = np.radians(p[0])
    dl = lon - lon0
    if fam in ('lcc', 'eqdc', 'albers'):
        p1, p2 = np.radians(p[1]), np.radians(p[2])
        if fam == 'lcc':
            n = (np.sin(p1) if abs(p[1] - p[2]) < 1e-9 else
                 np.log(np.cos(p1) / np.cos(p2)) /
                 np.log(np.tan(np.pi/4 + p2/2) / np.tan(np.pi/4 + p1/2)))
            F = np.cos(p1) * np.tan(np.pi/4 + p1/2)**n / n
            rho = F / np.tan(np.pi/4 + lat/2)**n
            rho0 = 0.0
        elif fam == 'eqdc':
            n = ((np.cos(p1) - np.cos(p2)) / (p2 - p1)
                 if abs(p[1] - p[2]) > 1e-9 else np.sin(p1))
            G = np.cos(p1) / n + p1
            rho = G - lat
            rho0 = 0.0
        else:  # albers
            n = (np.sin(p1) + np.sin(p2)) / 2
            C = np.cos(p1)**2 + 2 * n * np.sin(p1)
            rho = np.sqrt(np.maximum(C - 2 * n * np.sin(lat), 0)) / n
            rho0 = 0.0
        th = n * dl
        return rho * np.sin(th), rho0 - rho * np.cos(th)
    lat0 = np.radians(p[1])
    cosc = (np.sin(lat0) * np.sin(lat) +
            np.cos(lat0) * np.cos(lat) * np.cos(dl))
    if fam == 'laea':
        k = np.sqrt(np.maximum(2 / (1 + cosc), 0))
    elif fam == 'aeqd':
        c = np.arccos(np.clip(cosc, -1, 1))
        k = np.where(c < 1e-12, 1.0, c / np.maximum(np.sin(c), 1e-12))
    elif fam == 'stere':
        k = 2 / np.maximum(1 + cosc, 1e-9)
    else:
        raise ValueError(fam)
    x = k * np.cos(lat) * np.sin(dl)
    y = k * (np.cos(lat0) * np.sin(lat) - np.sin(lat0) * np.cos(lat) * np.cos(dl))
    return x, y


def inverse(px, fam, p, a, b):
    """Пиксели -> lon/lat (численно не нужен: все семейства обратимы аналитически)."""
    z = (px[:, 0] + 1j * px[:, 1] - b) / a
    x, y = z.real, -z.imag
    lon0 = p[0]
    if fam in ('lcc', 'eqdc', 'albers'):
        p1, p2 = np.radians(p[1]), np.radians(p[2])
        if fam == 'lcc':
            n = (np.sin(p1) if abs(p[1] - p[2]) < 1e-9 else
                 np.log(np.cos(p1) / np.cos(p2)) /
                 np.log(np.tan(np.pi/4 + p2/2) / np.tan(np.pi/4 + p1/2)))
            F = np.cos(p1) * np.tan(np.pi/4 + p1/2)**n / n
            rho = np.sign(n) * np.hypot(x, y)
            th = np.arctan2(x, -y)
            lat = 2 * np.degrees(np.arctan((F / rho)**(1/n))) - 90
        elif fam == 'eqdc':
            n = ((np.cos(p1) - np.cos(p2)) / (p2 - p1)
                 if abs(p[1] - p[2]) > 1e-9 else np.sin(p1))
            G = np.cos(p1) / n + p1
            rho = np.sign(n) * np.hypot(x, y)
            th = np.arctan2(x, -y)
            lat = np.degrees(G - rho)
        else:
            n = (np.sin(p1) + np.sin(p2)) / 2
            C = np.cos(p1)**2 + 2 * n * np.sin(p1)
            rho = np.sign(n) * np.hypot(x, y)
            th = np.arctan2(x, -y)
            lat = np.degrees(np.arcsin(np.clip((C - (rho * n)**2) / (2 * n), -1, 1)))
        lon = lon0 + np.degrees(th / n)
        return np.column_stack([lon, lat])
    lat0 = np.radians(p[1])
    rho = np.hypot(x, y)
    if fam == 'laea':
        c = 2 * np.arcsin(np.clip(rho / 2, -1, 1))
    elif fam == 'aeqd':
        c = rho
    else:  # stere
        c = 2 * np.arctan(rho / 2)
    with np.errstate(invalid='ignore', divide='ignore'):
        lat = np.degrees(np.arcsin(np.clip(
            np.cos(c) * np.sin(lat0) + np.where(rho < 1e-12, 0, y * np.sin(c) * np.cos(lat0) / np.maximum(rho, 1e-12)), -1, 1)))
        lon = lon0 + np.degrees(np.arctan2(
            x * np.sin(c),
            rho * np.cos(lat0) * np.cos(c) - y * np.sin(lat0) * np.sin(c)))
    return np.column_stack([lon, lat])


def proj_px(ll, fam, p, a, b):
    x, y = forward(ll[:, 0], ll[:, 1], fam, p)
    z = a * (x + 1j * (-y)) + b
    return np.column_stack([z.real, z.imag])


def sim_fit(src_xy, dst_px):
    """Комплексный МНК: dst ≈ a*src + b."""
    z_s = src_xy[:, 0] + 1j * src_xy[:, 1]
    z_d = dst_px[:, 0] + 1j * dst_px[:, 1]
    A = np.column_stack([z_s, np.ones_like(z_s)])
    (a, b), *_ = np.linalg.lstsq(A, z_d, rcond=None)
    return a, b


def score_and_icp(atlas_px, ref_ll, fam, p, a, b, iters=8, trim=0.75):
    """Усечённый ICP по подобию; возвращает (score, a, b)."""
    for _ in range(iters):
        ref_px = proj_px(ref_ll, fam, p, a, b)
        tree = cKDTree(ref_px)
        dist, idx = tree.query(atlas_px, workers=-1)
        k = int(len(atlas_px) * trim)
        keep = np.argsort(dist)[:k]
        # обновляем подобие в координатах проекции
        x, y = forward(ref_ll[idx[keep], 0], ref_ll[idx[keep], 1], fam, p)
        a, b = sim_fit(np.column_stack([x, -y]), atlas_px[keep])
        score = dist[keep].mean()
    return score, a, b


def design_quad(XY):
    """Квадратичный базис варпа поверх проекции (стабильная экстраполяция)."""
    x, y = XY[:, 0], XY[:, 1]
    return np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])


def warp_fit(atlas_px, ref_ll, fam, p, a, b, iters=10):
    """Квадратичный варп XY_proj -> px усечённым ICP; возвращает (Q, Rinv, q).

    Q: XY->px (6x2). Rinv: px->XY (6x2), функциональная инверсия Q по сетке.
    """
    x, y = forward(ref_ll[:, 0], ref_ll[:, 1], fam, p)
    XY = np.column_stack([x, -y])
    z = a * (XY[:, 0] + 1j * XY[:, 1]) + b
    ref_px = np.column_stack([z.real, z.imag])
    Q = None
    radii = np.linspace(200, 20, iters)   # multi-scale: дальние области втягиваются
    for it in range(iters):
        dist, idx = cKDTree(ref_px).query(atlas_px, workers=-1)
        keep = dist < max(min(3 * np.median(dist), radii[it]), 15)
        Q, *_ = np.linalg.lstsq(design_quad(XY[idx[keep]]), atlas_px[keep], rcond=None)
        ref_px = design_quad(XY) @ Q
    dist, _ = cKDTree(ref_px).query(atlas_px, workers=-1)
    # обратное отображение: сетка по покрытию XY с полем, px=Q(XY), МНК px->XY
    gx = np.linspace(XY[:, 0].min() - 0.05, XY[:, 0].max() + 0.05, 40)
    gy = np.linspace(XY[:, 1].min() - 0.05, XY[:, 1].max() + 0.05, 40)
    G = np.array([(xx, yy) for xx in gx for yy in gy])
    Gpx = design_quad(G) @ Q
    Rinv, *_ = np.linalg.lstsq(design_quad(Gpx), G, rcond=None)
    inv_err = np.abs(design_quad(design_quad(G) @ Q) @ Rinv - G).max()
    print(f"варп: инверсия по сетке, max ошибка {inv_err:.2e} (ед. проекции)")
    return Q, Rinv, np.percentile(dist, [50, 75, 90])


def mls_fit(atlas_px, ref_ll, fam, p, a, b, Q, sigma=120.0, w0=0.003,
            iters=10, step=40.0, bounds=(-250, -50, 3400, 2400)):
    """Сетка локальных подобий px -> XY_proj (moving least squares).

    Нужна для разворотов, где половины листа скомпонованы вручную и единая
    проекция не сходится (розд. 44: Дальний Восток сдвинут на сотни км).
    Якорь к глобальной подгонке (вес w0) держит области без белых линий.
    """
    x, y = forward(ref_ll[:, 0], ref_ll[:, 1], fam, p)
    XY = np.column_stack([x, -y])
    ref_px_glob = design_quad(XY) @ Q
    xs = np.arange(bounds[0], bounds[2] + 1, step)
    ys = np.arange(bounds[1], bounds[3] + 1, step)
    tree_XY = cKDTree(XY)
    scale_px = np.hypot(*Q[1])

    st = max(1, len(XY) // 3000)
    za = ref_px_glob[::st, 0] + 1j * ref_px_glob[::st, 1]
    zb = XY[::st, 0] + 1j * XY[::st, 1]

    cur_ref_px = ref_px_glob
    Ag = None
    radii = np.linspace(280, 25, iters)   # multi-scale: дальние области втягиваются
    for it in range(iters):
        dist, idx = cKDTree(cur_ref_px).query(atlas_px, workers=-1)
        keep = dist < max(min(3 * np.median(dist), radii[it]), 12)
        Ppx, PXY = atlas_px[keep], XY[idx[keep]]
        zp = Ppx[:, 0] + 1j * Ppx[:, 1]
        zq = PXY[:, 0] + 1j * PXY[:, 1]
        Ag = np.zeros((len(ys), len(xs), 4))
        for j, gy in enumerate(ys):
            d2 = (Ppx[:, 0][None, :] - xs[:, None])**2 + (Ppx[:, 1] - gy)**2
            w = np.exp(-d2 / (2 * sigma**2))
            da2 = (za.real[None, :] - xs[:, None])**2 + (za.imag - gy)**2
            wa = w0 * np.exp(-da2 / (2 * (3 * sigma)**2))
            zz = np.concatenate([zp, za]); tt = np.concatenate([zq, zb])
            ww = np.concatenate([w, wa], axis=1)
            sw = ww.sum(1)
            mz = (ww * zz).sum(1) / sw
            mt = (ww * tt).sum(1) / sw
            num = (ww * np.conj(zz[None, :] - mz[:, None]) * (tt[None, :] - mt[:, None])).sum(1)
            den = (ww * np.abs(zz[None, :] - mz[:, None])**2).sum(1)
            aa = num / den
            bb = mt - aa * mz
            Ag[j, :, 0], Ag[j, :, 1] = aa.real, aa.imag
            Ag[j, :, 2], Ag[j, :, 3] = bb.real, bb.imag
        aXY = mls_apply(atlas_px, xs, ys, Ag)
        dXY, idx2 = tree_XY.query(aXY, workers=-1)
        dpx = dXY * scale_px
        print(f"  MLS итерация {it}: пар {keep.sum()}, q50={np.median(dpx):.1f}px")
        if it < iters - 1:
            gpx = np.array([(xx, yy) for xx in np.arange(bounds[0], bounds[2], 20)
                            for yy in np.arange(bounds[1], bounds[3], 20)], float)
            gXY = mls_apply(gpx, xs, ys, Ag)
            _, ii = cKDTree(gXY).query(XY, workers=-1)
            cur_ref_px = gpx[ii]
    return xs, ys, Ag, np.percentile(dpx, [50, 75, 90])


def mls_apply(px, xs, ys, Ag):
    """Применение MLS-сетки: px -> XY_proj (билинейная интерполяция узлов)."""
    px = np.asarray(px, float)
    fx = np.clip((px[:, 0] - xs[0]) / (xs[1] - xs[0]), 0, len(xs) - 1.001)
    fy = np.clip((px[:, 1] - ys[0]) / (ys[1] - ys[0]), 0, len(ys) - 1.001)
    i0, j0 = fx.astype(int), fy.astype(int)
    tx, ty = fx - i0, fy - j0
    P = (Ag[j0, i0].T * (1 - tx) * (1 - ty) + Ag[j0, i0 + 1].T * tx * (1 - ty) +
         Ag[j0 + 1, i0].T * (1 - tx) * ty + Ag[j0 + 1, i0 + 1].T * tx * ty).T
    a = P[:, 0] + 1j * P[:, 1]
    b = P[:, 2] + 1j * P[:, 3]
    z = a * (px[:, 0] + 1j * px[:, 1]) + b
    return np.column_stack([z.real, z.imag])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--white', required=True, help='npy: белые точки страницы, px@200dpi')
    ap.add_argument('--ref', required=True, help='npy: точки современных границ, lon/lat')
    ap.add_argument('--diag', help='PNG-оверлей для визуальной проверки')
    ap.add_argument('--page', type=int, default=145)
    ap.add_argument('--families', default='lcc,eqdc,albers',
                    help='семейства проекций; азимутальные (laea/aeqd/stere) у '
                         'широких разворотов ломают инверсию у края полусферы')
    ap.add_argument('--bounds', default='-200,5,3350,2333',
                    help='x0,y0,x1,y1 рабочей области px@200dpi: у разворотов '
                         'полотно шире листа (артефакты за границей отсечь)')
    args = ap.parse_args()

    atlas = np.load(args.white)
    x0, y0, x1, y1 = (float(v) for v in args.bounds.split(','))
    m = (atlas[:, 0] > x0) & (atlas[:, 0] < x1) & (atlas[:, 1] > y0) & (atlas[:, 1] < y1)
    atlas = atlas[m]
    sub = atlas[::max(1, len(atlas) // 6000)]
    ref = np.load(args.ref)
    ref_sub = ref[::max(1, len(ref) // 40000)]

    ctrl_px = np.array([c[0] for c in CONTROL], float)
    ctrl_ll = np.array([c[1] for c in CONTROL], float)

    grids = {
        'lcc':    [(l0, l1, l2) for l0 in range(20, 101, 10)
                   for l1 in range(30, 61, 10) for l2 in range(l1 + 10, 81, 10)],
        'eqdc':   [(l0, l1, l2) for l0 in range(20, 101, 10)
                   for l1 in range(30, 61, 10) for l2 in range(l1 + 10, 81, 10)],
        'albers': [(l0, l1, l2) for l0 in range(20, 101, 10)
                   for l1 in range(30, 61, 10) for l2 in range(l1 + 10, 81, 10)],
        'laea':   [(l0, la, 0) for l0 in range(20, 101, 10) for la in range(30, 76, 5)],
        'aeqd':   [(l0, la, 0) for l0 in range(20, 101, 10) for la in range(30, 76, 5)],
        'stere':  [(l0, la, 0) for l0 in range(20, 101, 10) for la in range(30, 76, 5)],
    }

    allowed = set(args.families.split(','))
    grids = {k: v for k, v in grids.items() if k in allowed}
    cands = []
    for fam, plist in grids.items():
        best = None
        for p in plist:
            x, y = forward(ctrl_ll[:, 0], ctrl_ll[:, 1], fam, p)
            a, b = sim_fit(np.column_stack([x, -y]), ctrl_px)
            s, a, b = score_and_icp(sub, ref_sub, fam, p, a, b, iters=3)
            if best is None or s < best[0]:
                best = (s, fam, p, a, b)
        cands.append(best)
        print(f"{fam}: лучший {best[2]} score={best[0]:.2f} px")

    cands.sort()
    results = []
    for s0, fam, p, a, b in cands[:3]:
        # координатный спуск по параметрам проекции
        p = list(p)
        best_s, best_a, best_b = score_and_icp(atlas[::2], ref, fam, p, a, b, iters=6)
        stepsizes = [5, 2, 1, 0.5]
        for step in stepsizes:
            improved = True
            while improved:
                improved = False
                for i in range(3 if fam in ('lcc', 'eqdc', 'albers') else 2):
                    for d in (-step, step):
                        q = list(p); q[i] += d
                        if fam in ('lcc', 'eqdc', 'albers') and not q[1] < q[2]:
                            continue
                        s, a2, b2 = score_and_icp(atlas[::2], ref, fam, q, best_a, best_b, iters=7)
                        if s < best_s - 1e-3:
                            best_s, best_a, best_b, p = s, a2, b2, q
                            improved = True
        results.append((best_s, fam, p, best_a, best_b))
        print(f"уточнено {fam} {p}: score={best_s:.2f} px")

    results.sort()
    s, fam, p, a, b = results[0]
    # квадратичный варп поверх проекции
    Q, Rinv, (q50, q75, q90) = warp_fit(atlas, ref, fam, p, a, b)
    # финальная стадия: MLS-сетка локальных подобий (лечит ручную компоновку)
    xs, ys, Ag, (m50, m75, m90) = mls_fit(atlas, ref, fam, p, a, b, np.asarray(Q))
    print(f"MLS: q50={m50:.1f} q75={m75:.1f} q90={m90:.1f}")
    print(f"\nИТОГ: {fam} параметры {p} + квадратичный варп; "
          f"резидуалы px: медиана {q50:.1f}, q75 {q75:.1f}, q90 {q90:.1f}; "
          f"масштаб ~{6371 / abs(a):.1f} км/px")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump({
            'family': fam, 'params': p,
            'a': [a.real, a.imag], 'b': [b.real, b.imag],
            'warp_q': np.asarray(Q).tolist(), 'warp_rinv': np.asarray(Rinv).tolist(),
            'mls': {'xs': [float(xs[0]), float(xs[1] - xs[0]), len(xs)],
                    'ys': [float(ys[0]), float(ys[1] - ys[0]), len(ys)],
                    'grid': np.asarray(Ag).tolist()},
            'dpi': 200, 'page_calibrated': args.page,
            'residuals_px': {'q50': round(m50, 2), 'q75': round(m75, 2), 'q90': round(m90, 2),
                             'warp_only_q50': round(q50, 2), 'warp_only_q90': round(q90, 2)},
            'km_per_px': round(6371 / abs(a), 2),
            'method': 'ICP белых линий (совр. границы) к CShapes-2019: '
                      'проекция + кв. варп + MLS-сетка локальных подобий',
        }, f, ensure_ascii=False, indent=1)
    print('->', os.path.normpath(OUT))

    if args.diag:
        import pymupdf
        x, y = forward(ref[:, 0], ref[:, 1], fam, p)
        ref_px = design_quad(np.column_stack([x, -y])) @ np.asarray(Q)
        pdf = os.path.expanduser('~/tmp/MATERIALS/common/'
            'Atlas_rosijskogo_imperializmu_i_kolonializmu_UIF_2026/atlas-ua-2.pdf')
        page = pymupdf.open(pdf)[args.page]
        pix = page.get_pixmap(dpi=100)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n).copy()
        for x, y in ref_px * 0.5:
            xi, yi = int(x), int(y)
            if 0 <= yi < pix.height and 0 <= xi < pix.width:
                img[yi, xi, :3] = (0, 200, 0)
        pymupdf.Pixmap(pymupdf.csRGB, pix.width, pix.height,
                       img[:, :, :3].tobytes(), False).save(args.diag)
        print('диагностика ->', args.diag)


if __name__ == '__main__':
    main()
