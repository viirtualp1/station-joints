"""Распознавание однониточной схемы станции с картинки в граф.

Конвейер: бинаризация -> выравнивание наклона -> отделение надписей ->
скелет -> граф пикселей -> обрезка «усиков» (тупиковые упоры ']') ->
аппроксимация ломаными -> выпрямление (горизонтальные пути по уровням).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from graph import Annotation, Graph


def _thin_luts():
    """Таблицы удаления для утончения Го–Холла (Guo, Hall 1989), как в scikit-image."""
    def bits(n):
        return [(n >> i) & 1 for i in range(8)]

    def g1(b):
        return sum(1 for i in (0, 2, 4, 6) if not b[i] and (b[i + 1] or b[(i + 2) % 8])) == 1

    def g2(b):
        n1 = sum(1 for k in (1, 3, 5, 7) if b[k] or b[k - 1])
        n2 = sum(1 for k in (1, 3, 5, 7) if b[k] or b[(k + 1) % 8])
        return min(n1, n2) in (2, 3)

    def g3(b):
        return not ((b[1] or b[2] or not b[7]) and b[0])

    def g3p(b):
        return not ((b[5] or b[6] or not b[3]) and b[4])

    lut1 = np.array([g1(bits(n)) and g2(bits(n)) and g3(bits(n)) for n in range(256)])
    lut2 = np.array([g1(bits(n)) and g2(bits(n)) and g3p(bits(n)) for n in range(256)])
    return lut1, lut2


_LUT1, _LUT2 = _thin_luts()
# вес соседа (dy, dx) в коде окрестности: E=1, NE=2, N=4, NW=8, W=16, SW=32, S=64, SE=128
_NB_W = [((0, 1), 1), ((-1, 1), 2), ((-1, 0), 4), ((-1, -1), 8),
         ((0, -1), 16), ((1, -1), 32), ((1, 0), 64), ((1, 1), 128)]


def skeletonize(mask: np.ndarray) -> np.ndarray:
    """Скелет толщиной 1 пиксель с сохранением 8-связности (утончение Го–Холла,
    векторно на numpy). Своя реализация вместо scikit-image – без scipy в сборке."""
    img = np.pad(mask.astype(np.uint8), 1)
    H, W = img.shape
    while True:
        before = int(img.sum())
        for lut in (_LUT1, _LUT2):
            code = np.zeros((H - 2, W - 2), np.uint8)
            for (dy, dx), w in _NB_W:
                code |= img[1 + dy:H - 1 + dy, 1 + dx:W - 1 + dx] * np.uint8(w)
            kill = lut[code] & (img[1:-1, 1:-1] == 1)
            img[1:-1, 1:-1][kill] = 0
        if int(img.sum()) == before:
            return img[1:-1, 1:-1].astype(bool)

TARGET_W = 1400


def load_gray(path: str) -> np.ndarray:
    data = np.fromfile(path, np.uint8)          # поддержка кириллицы в пути
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f'Не удалось открыть изображение: {path}')
    return img


# --------------------------------------------------------------------------
# 1. Предобработка
# --------------------------------------------------------------------------
def binarize(gray: np.ndarray):
    h, w = gray.shape
    s = max(1.0, TARGET_W / w)
    g = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (0, 0), max(0.8, s * 0.35))
    H, W = g.shape
    block = int(W * 0.04) | 1
    th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, block, 12)
    # на чистых сканах/PDF adaptive даёт то же, но добавим отсечку по Отсу,
    # чтобы не ловить шум бумаги на фото
    otsu_t, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th[g > min(245, otsu_t + 40)] = 0
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return g, th, s


def deskew(gray: np.ndarray, binimg: np.ndarray):
    H, W = binimg.shape
    lines = cv2.HoughLinesP(binimg, 1, np.pi / 720, threshold=int(W * 0.15),
                            minLineLength=int(W * 0.3), maxLineGap=int(W * 0.01))
    if lines is None:
        return gray, binimg, 0.0
    angs, wts = [], []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        a = math.degrees(math.atan2(y1 - y0, x1 - x0))
        if abs(a) < 6:
            angs.append(a)
            wts.append(math.hypot(x1 - x0, y1 - y0))
    if not angs:
        return gray, binimg, 0.0
    ang = float(np.average(angs, weights=wts))
    if abs(ang) < 0.15:
        return gray, binimg, 0.0
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
    gray = cv2.warpAffine(gray, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=255)
    binimg = cv2.warpAffine(binimg, M, (W, H), flags=cv2.INTER_NEAREST, borderValue=0)
    return gray, binimg, ang


def split_components(binimg: np.ndarray):
    """Сеть путей – крупные компоненты; всё мелкое (текст, рамка номера) – надписи."""
    H, W = binimg.shape
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binimg, connectivity=8)
    net = np.zeros_like(binimg, bool)
    annots = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 0.0001 * W * H:
            continue
        m = lab[y:y + h, x:x + w] == i
        if w >= 0.12 * W and w > 1.5 * h * 0.5:
            net[y:y + h, x:x + w] |= m
        elif x > 2 and y > 2 and x + w < W - 2 and y + h < H - 2:
            # всё, что касается края кадра – края листа/фото, не надписи
            annots.append(Annotation(x, y, x + w, y + h, m))
    return net, annots


def detach_text(net: np.ndarray, annots: list, sw: float):
    """Отрывает надписи, прилипшие к путям (например «п/п» над концом пути).

    Длинные горизонтали вырезаются морфологией; в остатке мелкие фрагменты,
    стоящие группой (≥2 рядом) – это буквы; одиночные – тупиковые упоры ']'.
    """
    H, W = net.shape
    m = net.astype(np.uint8)
    klen = max(15, int(W * 0.05))
    hl = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((1, klen), np.uint8))
    hl = cv2.dilate(hl, np.ones((int(sw) + 2, 3), np.uint8))
    rest = (m > 0) & (hl == 0)
    n, lab, st, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
    hlb = hl > 0
    pad = int(sw) + 3

    def touches(x0, x1, y0, y1):
        y0, y1 = max(0, y0), min(H, y1)
        return y1 > y0 and hlb[y0:y1, max(0, x0):min(W, x1)].any()

    small = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if max(w, h) >= W * 0.045 or area <= sw * 2:
            continue
        # кусок диагонали между двумя путями касается линий и сверху, и снизу
        if touches(x - pad, x + w + pad, y - pad, y + 3) and \
                touches(x - pad, x + w + pad, y + h - 3, y + h + pad):
            continue
        small.append(i)

    # группируем соседние фрагменты
    gap = W * 0.03
    parent = {i: i for i in small}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in small:
        xa, ya, wa, ha = st[a][:4]
        for b in small:
            if b <= a:
                continue
            xb, yb, wb, hb = st[b][:4]
            dx = max(0, max(xa, xb) - min(xa + wa, xb + wb))
            dy = max(0, max(ya, yb) - min(ya + ha, yb + hb))
            if dx < gap and dy < max(ha, hb):
                parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in small:
        groups.setdefault(find(i), []).append(i)

    for members in groups.values():
        if len(members) < 2:
            continue                    # одиночный фрагмент – упор тупика
        gx0 = min(st[i][0] for i in members)
        gx1 = max(st[i][0] + st[i][2] for i in members)
        gy0 = min(st[i][1] for i in members)
        gy1 = max(st[i][1] + st[i][3] for i in members)
        rows = np.nonzero(hlb[gy0:gy1, gx0:gx1].any(axis=1))[0]
        straddle = False
        if rows.size:
            ly = gy0 + rows.mean()
            above = any(st[i][1] + st[i][3] / 2 < ly for i in members)
            below = any(st[i][1] + st[i][3] / 2 > ly for i in members)
            straddle = above and below
        if straddle:
            continue                    # половинки упора ']' по обе стороны пути
        for i in members:
            x, y, w, h = st[i][:4]
            msk = lab[y:y + h, x:x + w] == i
            net[y:y + h, x:x + w] &= ~msk
            annots.append(Annotation(x, y, x + w, y + h, msk))
    return net


def stroke_width(mask: np.ndarray) -> float:
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    sk = skeletonize(mask)
    v = dist[sk]
    return float(np.median(v) * 2) if v.size else 3.0


# --------------------------------------------------------------------------
# 2. Скелет -> граф пикселей
# --------------------------------------------------------------------------
_NB = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]


def _crossing_number(sk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = np.pad(sk.astype(np.int8), 1)
    ring = [p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx] for dy, dx in _NB]
    cn = np.zeros(sk.shape, np.int8)
    for i in range(8):
        cn += ((ring[i] == 0) & (ring[(i + 1) % 8] == 1)).astype(np.int8)
    nb = np.sum(np.stack(ring), axis=0)
    return cn, nb


def skeleton_to_paths(sk: np.ndarray):
    """Возвращает (узлы {label: (x, y)}, рёбра [(la, lb, [(x, y), ...])])."""
    cn, nb = _crossing_number(sk)
    core = sk & ((cn != 2) | (nb == 1))
    # узел = окрестность особой точки: все пиксели скелета рядом с развилкой
    # принадлежат узлу, чтобы ветви на выходе из него не «слипались»
    dil = cv2.dilate(core.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    nodemask = sk & dil
    nlab_n, nlab = cv2.connectedComponents(dil.astype(np.uint8), connectivity=8)
    nlab = np.where(nodemask, nlab, 0)
    nodes = {}
    for l in range(1, nlab_n):
        ys, xs = np.nonzero(nlab == l)
        if len(xs):
            nodes[l] = (float(xs.mean()), float(ys.mean()))
    H, W = sk.shape
    visited = np.zeros_like(sk, bool)
    edges = []

    def nbrs(y, x):
        for dy, dx in _NB:
            yy, xx = y + dy, x + dx
            if 0 <= yy < H and 0 <= xx < W and sk[yy, xx]:
                yield yy, xx

    node_pixels = list(zip(*np.nonzero(nlab)))
    for y, x in node_pixels:
        la = nlab[y, x]
        for yy, xx in nbrs(y, x):
            if nlab[yy, xx] or visited[yy, xx]:
                if nlab[yy, xx] and nlab[yy, xx] != la:
                    edges.append((la, nlab[yy, xx], [(x, y), (xx, yy)]))
                continue
            path = [(x, y), (xx, yy)]
            visited[yy, xx] = True
            cy, cx = yy, xx
            end = None
            while True:
                nxt = None
                for ny, nx in nbrs(cy, cx):
                    lab_n = nlab[ny, nx]
                    if lab_n and (lab_n != la or len(path) > 40):
                        end = lab_n
                        path.append((nx, ny))
                        break
                    if not lab_n and not visited[ny, nx]:
                        nxt = (ny, nx)
                if end is not None or nxt is None:
                    break
                cy, cx = nxt
                visited[cy, cx] = True
                path.append((cx, cy))
            if end is not None:
                edges.append((la, end, path))
    # удаляем дубли рёбер, найденных с двух сторон
    uniq, seen = [], set()
    for la, lb, path in edges:
        key = (min(la, lb), max(la, lb), len(path), tuple(sorted([path[0], path[-1]])))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((la, lb, path))
    return nodes, uniq


def _rdp(pts, eps):
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0], float), np.array(pts[-1], float)
    ab = b - a
    L = np.hypot(*ab)
    P = np.array(pts, float)
    if L == 0:
        d = np.hypot(*(P - a).T)
    else:
        Q = P - a
        d = np.abs(ab[0] * Q[:, 1] - ab[1] * Q[:, 0]) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return _rdp(pts[:i + 1], eps)[:-1] + _rdp(pts[i:], eps)
    return [pts[0], pts[-1]]


# --------------------------------------------------------------------------
# 3. Сборка и чистка графа
# --------------------------------------------------------------------------
def build_graph(net: np.ndarray, sw: float):
    H, W = net.shape
    sk = skeletonize(net)
    pnodes, pedges = skeleton_to_paths(sk)

    # --- граф «сырых» путей с длинами, обрезка усиков -------------------
    adj: dict[int, list[int]] = {k: [] for k in pnodes}
    E = {}
    for i, (a, b, path) in enumerate(pedges):
        E[i] = [a, b, path]
        adj[a].append(i)
        adj[b].append(i)

    def plen(path):
        return sum(math.hypot(path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
                   for k in range(len(path) - 1))

    spur = max(sw * 3.0, W * 0.03)
    marks: dict[int, str] = {}
    for _ in range(4):
        changed = False
        for n in list(adj):
            if n not in adj or len(adj[n]) < 3:
                continue
            spurs = []
            for ei in adj[n]:
                a, b, path = E[ei]
                o = b if a == n else a
                if o != n and len(adj[o]) == 1 and o not in marks and plen(path) < spur:
                    spurs.append(ei)
            if not spurs:
                continue
            keep = [ei for ei in adj[n] if ei not in spurs]
            if len(keep) == 0:
                continue
            # тупиковый упор: два усика поперёк оставшегося пути, узел становится концом
            if len(keep) == 1 and len(spurs) >= 2:
                a, b, path = E[keep[0]]
                p0 = path[0] if a == n else path[-1]
                p1 = path[min(6, len(path) - 1)] if a == n else path[-min(7, len(path))]
                vx, vy = p1[0] - p0[0], p1[1] - p0[1]
                perp = 0
                for ei in spurs:
                    sa, sb, sp = E[ei]
                    if sa != n:
                        sp = sp[::-1]
                    q0, q1 = sp[0], sp[min(len(sp) - 1, max(3, len(sp) // 2))]
                    ux, uy = q1[0] - q0[0], q1[1] - q0[1]
                    c = abs(vx * ux + vy * uy) / ((math.hypot(vx, vy) * math.hypot(ux, uy)) or 1)
                    if c < 0.6:
                        perp += 1
                if perp >= 2:
                    marks[n] = 'tupik'
            for ei in spurs:
                a, b, path = E.pop(ei)
                o = b if a == n else a
                adj[n].remove(ei)
                adj[o].remove(ei)
                adj.pop(o, None)
            changed = True
        if not changed:
            break

    # --- ломаные -> граф ------------------------------------------------
    g = Graph()
    idmap = {}
    for n in adj:
        if adj[n]:
            idmap[n] = g.add_node(*pnodes[n], mark=marks.get(n))
    eps = max(sw * 0.9, W * 0.004)
    for a, b, path in E.values():
        if a not in idmap or b not in idmap:
            continue
        simp = _rdp(path, eps)
        prev = idmap[a]
        for p in simp[1:-1]:
            nid = g.add_node(*p)
            g.add_edge(prev, nid)
            prev = nid
        g.add_edge(prev, idmap[b])
    return g, sk


def _angle(g: Graph, e, from_node):
    dx, dy = g.direction(e, from_node)
    return math.atan2(dy, dx)


def cleanup(g: Graph, W: int, sw: float):
    merge_r = max(sw * 2.2, W * 0.008)

    # 1. слить близкие узлы
    changed = True
    while changed:
        changed = False
        ids = list(g.nodes)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if a in g.nodes and b in g.nodes:
                    (x0, y0), (x1, y1) = g.pos(a), g.pos(b)
                    if math.hypot(x1 - x0, y1 - y0) < merge_r:
                        da, db = g.degree(a), g.degree(b)
                        keep, drop = (a, b) if da >= db else (b, a)
                        g.merge_nodes(keep, drop)
                        changed = True
    for n in [n for n in g.nodes if g.degree(n) == 0]:
        g.nodes.pop(n)

    # 2. уровни горизонтальных путей
    snap_levels(g, W)

    # 3. убрать изломы на прямой
    straighten(g)

    # 4. разобрать пересечения «X» (узел степени 4 из двух прямых)
    for n in [n for n in list(g.nodes) if g.degree(n) == 4]:
        inc = g.incident(n)
        best = None
        for pairing in (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))):
            dev = 0
            for i, j in pairing:
                a1, a2 = _angle(g, inc[i], n), _angle(g, inc[j], n)
                d = abs((a1 - a2) % (2 * math.pi) - math.pi)
                dev += d
            if best is None or dev < best[0]:
                best = (dev, pairing)
        if best and best[0] < math.radians(30):
            x, y = g.pos(n)
            others = [g.other(e, n) for e in inc]
            g.remove_node(n)
            for i, j in best[1]:
                g.add_edge(others[i], others[j])
    return g


def snap_levels(g: Graph, W: int):
    tol = W * 0.012
    hs = [e for e in g.edges.values() if g.is_horizontal(e, 12)]
    ys = []
    for e in hs:
        L = g.length(e)
        for n in (e.a, e.b):
            ys.append((g.nodes[n].y, L))
    ys.sort()
    levels = []
    for y, w in ys:
        if levels and y - levels[-1][2] <= tol:
            lv = levels[-1]
            lv[0] += y * w
            lv[1] += w
            lv[2] = y
        else:
            levels.append([y * w, w, y])
    lvl = [s / w for s, w, _ in levels]
    for e in hs:
        for n in (e.a, e.b):
            y = g.nodes[n].y
            best = min(lvl, key=lambda v: abs(v - y))
            if abs(best - y) <= tol * 1.5:
                g.nodes[n].y = best


def straighten(g: Graph, tol_deg=9):
    changed = True
    while changed:
        changed = False
        for n in list(g.nodes):
            if n not in g.nodes or g.degree(n) != 2 or g.nodes[n].mark:
                continue
            e1, e2 = g.incident(n)
            a1, a2 = _angle(g, e1, n), _angle(g, e2, n)
            d = abs((a1 - a2) % (2 * math.pi) - math.pi)
            if d < math.radians(tol_deg):
                g.dissolve(n)
                changed = True


# --------------------------------------------------------------------------
# 4. Метки концов
# --------------------------------------------------------------------------
def classify_ends(g: Graph, annots, W, H, sw):
    """п/п – рядом с концом пути есть надпись (буквы размером с текст)."""
    near = W * 0.05
    texts = [a for a in annots
             if (a.x1 - a.x0) < W * 0.1 and 2 * sw < (a.y1 - a.y0) < H * 0.12]
    for n in g.nodes.values():
        if g.degree(n.id) != 1 or n.mark == 'tupik':
            continue
        e = g.incident(n.id)[0]
        dx, _ = g.direction(e, n.id)
        for a in texts:
            cx = min(max(n.x, a.x0), a.x1)
            cy = min(max(n.y, a.y0), a.y1)
            # надпись должна быть за концом пути или над ним, но не «внутри» пути
            ax = (a.x0 + a.x1) / 2
            behind = (ax - n.x) * (-dx) > -W * 0.03
            if behind and math.hypot(cx - n.x, cy - n.y) < near:
                n.mark = 'pp'
                break


def drop_switchless(g: Graph):
    """Компоненты без стрелок – это рамки/линии листа, а не путевое развитие."""
    seen = set()
    for start in list(g.nodes):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            stack += [g.other(e, n) for e in g.incident(n)]
        seen |= comp
        if not any(g.degree(n) >= 3 for n in comp):
            for n in comp:
                g.remove_node(n)


# --------------------------------------------------------------------------
def parse_image(path: str):
    gray0 = load_gray(path)
    gray, binimg, scale = binarize(gray0)
    gray, binimg, ang = deskew(gray, binimg)
    net, annots = split_components(binimg)
    sw = stroke_width(net)
    net = detach_text(net, annots, sw)
    annots = [a for a in annots if max(a.x1 - a.x0, a.y1 - a.y0) > 2.5 * sw]   # точки-шум
    g, sk = build_graph(net, sw)
    H, W = net.shape
    cleanup(g, W, sw)
    drop_switchless(g)
    classify_ends(g, annots, W, H, sw)
    info = dict(scale=scale, angle=ang, stroke=sw, size=(W, H))
    return dict(graph=g, gray=gray, bin=binimg, net=net, skel=sk,
                annots=annots, info=info)
