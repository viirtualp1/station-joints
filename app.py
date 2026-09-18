"""GUI: загрузка картинки схемы станции -> векторная перерисовка -> расстановка стыков.

Запуск:  python app.py  [картинка]
Мышь на схеме:  ЛКМ по пути – добавить стык, ЛКМ по стыку – удалить,
                ПКМ по стыку – габаритный / негабаритный.
"""
from __future__ import annotations

import math
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from graph import Joint
from joints import (RULE_TEXT, check_entries, compute_sections, name_sections,
                    place_joints, report, update_negab)
from layout import build_station, snap_joints
from signals import place_signals
from parser import parse_image
from render import fit_view, render


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title('Схема станции → изолирующие стыки')
        self.geometry('1500x900')
        self.minsize(900, 600)
        self.parsed = None
        self.st = None
        self.src_img = None
        self.transform = None
        self.view = None            # (k, ox, oy) при зуме; None – вся схема в окне
        self._pan = None
        self._tk_imgs = {}
        self._redraw_job = None

        self.opts = {k: tk.BooleanVar(value=v) for k, v in dict(
            grid=True, joints=True, signals=True, letters=False, numbers=True, sections=False,
            section_names=False, annots=True).items()}
        self.annots = []
        self._build_ui()
        if path:
            self.after(100, lambda: self.load(path))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        bar = ttk.Frame(self, padding=4)
        bar.pack(side='top', fill='x')
        ttk.Button(bar, text='Открыть картинку…', command=self.open).pack(side='left')
        ttk.Button(bar, text='Расставить стыки заново', command=self.recompute).pack(side='left', padx=4)
        ttk.Button(bar, text='Сохранить PNG…', command=self.save_png).pack(side='left')
        ttk.Button(bar, text='Сохранить отчёт…', command=self.save_report).pack(side='left', padx=4)
        ttk.Separator(bar, orient='vertical').pack(side='left', fill='y', padx=6)
        labels = dict(grid='Сетка (мм)', joints='Стыки', signals='Светофоры', letters='Буквы правил',
                      numbers='Номера стрелок', sections='Участки цветом',
                      section_names='Имена участков', annots='Надписи')
        for k, text in labels.items():
            ttk.Checkbutton(bar, text=text, variable=self.opts[k],
                            command=self.redraw).pack(side='left', padx=2)
        ttk.Separator(bar, orient='vertical').pack(side='left', fill='y', padx=6)
        ttk.Button(bar, text='−', width=3, command=lambda: self.zoom_center(1 / 1.5)).pack(side='left')
        ttk.Button(bar, text='+', width=3, command=lambda: self.zoom_center(1.5)).pack(side='left', padx=2)
        ttk.Button(bar, text='Вписать', command=self.zoom_fit).pack(side='left')
        self.zoom_lbl = ttk.Label(bar, text='100%', width=7, anchor='e')
        self.zoom_lbl.pack(side='left', padx=4)

        body = ttk.PanedWindow(self, orient='horizontal')
        body.pack(fill='both', expand=True)
        left = ttk.PanedWindow(body, orient='vertical')
        body.add(left, weight=4)

        f1 = ttk.LabelFrame(left, text='Исходная картинка')
        self.cv_src = tk.Canvas(f1, bg='#f4f4f4', highlightthickness=0)
        self.cv_src.pack(fill='both', expand=True)
        left.add(f1, weight=1)

        f2 = ttk.LabelFrame(left, text='Схема со стыками   (ЛКМ – добавить/удалить стык, '
                                       'ПКМ – негабаритный, колесо – зум, '
                                       'Ctrl+ЛКМ или средняя кнопка – двигать, 0 – вписать)')
        self.cv = tk.Canvas(f2, bg='white', highlightthickness=0)
        self.cv.pack(fill='both', expand=True)
        left.add(f2, weight=3)

        f3 = ttk.LabelFrame(body, text='Отчёт')
        self.txt = tk.Text(f3, width=52, wrap='word', font=('Consolas', 9))
        sb = ttk.Scrollbar(f3, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.txt.pack(fill='both', expand=True)
        body.add(f3, weight=1)

        self.status = tk.StringVar(value='Откройте картинку со схемой станции (jpg/png).')
        ttk.Label(self, textvariable=self.status, anchor='w', padding=3).pack(side='bottom', fill='x')

        self.cv.bind('<Configure>', lambda e: self.schedule_redraw())
        self.cv_src.bind('<Configure>', lambda e: self.after_idle(self.redraw_src))
        self.cv.bind('<Button-1>', self.on_click)
        self.cv.bind('<Button-3>', self.on_right)
        self.cv.bind('<Motion>', self.on_motion)
        # зум и перемещение
        self.cv.bind('<MouseWheel>', self.on_wheel)                  # Windows / macOS
        self.cv.bind('<Button-4>', lambda e: self.zoom_at(e.x, e.y, 1.25))   # Linux
        self.cv.bind('<Button-5>', lambda e: self.zoom_at(e.x, e.y, 0.8))
        for press, drag in (('<Button-2>', '<B2-Motion>'),
                            ('<Control-Button-1>', '<Control-B1-Motion>')):
            self.cv.bind(press, self.pan_start)
            self.cv.bind(drag, self.pan_move)
        self.cv.bind('<Enter>', lambda e: self.cv.focus_set())
        for key, f in (('<plus>', 1.5), ('<equal>', 1.5), ('<KP_Add>', 1.5),
                       ('<minus>', 1 / 1.5), ('<KP_Subtract>', 1 / 1.5)):
            self.cv.bind(key, lambda e, f=f: self.zoom_center(f))
        self.cv.bind('<Key-0>', lambda e: self.zoom_fit())

    # ----------------------------------------------------------- действия
    def open(self):
        p = filedialog.askopenfilename(filetypes=[('Изображения', '*.png *.jpg *.jpeg *.bmp *.tif *.tiff'),
                                                  ('Все файлы', '*.*')])
        if p:
            self.load(p)

    def load(self, path):
        self.status.set(f'Распознаю {path} …')
        self.config(cursor='watch')

        def work():
            try:
                parsed = parse_image(path)
                st, annots = build_station(parsed['graph'], parsed['annots'])
                self.after(0, lambda: self._loaded(path, parsed, st, annots))
            except Exception as ex:           # показываем ошибку, а не падаем
                self.after(0, lambda: self._failed(ex))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, ex):
        self.config(cursor='')
        self.status.set('Ошибка распознавания')
        messagebox.showerror('Ошибка', str(ex))

    def _loaded(self, path, parsed, st, annots):
        self.config(cursor='')
        self.parsed, self.st, self.annots = parsed, st, annots
        self.view = None
        self.src_img = Image.open(path).convert('RGB')
        g = st.g
        info = parsed['info']
        self.status.set(f'Готово: узлов {len(g.nodes)}, рёбер {len(g.edges)}, стрелок {len(st.sw)}, '
                        f'стыков {len(st.joints)}. Наклон фото исправлен на {info["angle"]:.1f}°.')
        self.update_report()
        self.redraw_src()
        self.redraw()

    def recompute(self):
        if not self.st:
            return
        place_joints(self.st)
        snap_joints(self.st)
        place_signals(self.st)
        self.update_report()
        self.redraw()

    def save_png(self):
        if not self.st:
            return
        p = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG', '*.png')])
        if not p:
            return
        img, _ = self._render((2800, 1600))
        img.save(p)
        self.status.set(f'Сохранено: {p}')

    def save_report(self):
        if not self.st:
            return
        p = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Текст', '*.txt')])
        if p:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(self._report_text())
            self.status.set(f'Сохранено: {p}')

    # ----------------------------------------------------------- отрисовка
    def _report_text(self):
        legend = '\n'.join(f'  {k}) {v}' for k, v in RULE_TEXT.items())
        return report(self.st) + '\n\nПравила (п. 2.4 пособия):\n' + legend

    def update_report(self):
        self.txt.delete('1.0', 'end')
        self.txt.insert('1.0', self._report_text())

    def schedule_redraw(self):
        if self._redraw_job:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(80, self.redraw)

    def _render(self, size, highlight=None, view=None):
        o = {k: v.get() for k, v in self.opts.items()}
        return render(self.st, size, show_grid=o['grid'], show_joints=o['joints'],
                      show_letters=o['letters'], show_numbers=o['numbers'],
                      show_sections=o['sections'], show_section_names=o['section_names'],
                      show_annots=o['annots'], annots=self.annots, highlight=highlight,
                      view=view, show_signals=o['signals'])

    # ----------------------------------------------------------- зум
    def _fit(self):
        w, h = max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())
        return fit_view(self.st, (w, h), self.annots if self.opts['annots'].get() else ())

    def zoom_at(self, sx, sy, factor):
        """Масштабирование относительно точки экрана (sx, sy) – она остаётся на месте."""
        if not self.st or not self.transform:
            return
        k, ox, oy = self.transform
        kfit = self._fit()[0]
        nk = min(max(k * factor, kfit * 0.5), kfit * 60)
        f = nk / k
        self.view = (nk, sx - (sx - ox) * f, sy - (sy - oy) * f)
        self._preview()

    def zoom_center(self, factor):
        self.zoom_at(self.cv.winfo_width() / 2, self.cv.winfo_height() / 2, factor)

    def zoom_fit(self):
        self.view = None
        self.redraw()

    def on_wheel(self, ev):
        self.zoom_at(ev.x, ev.y, 1.25 if ev.delta > 0 else 0.8)

    def pan_start(self, ev):
        if self.transform:
            self._pan = [ev.x, ev.y]
            self.cv.configure(cursor='fleur')

    def pan_move(self, ev):
        """Перетаскивание: просто сдвигаем готовую картинку на холсте (без перерисовки),
        чёткая перерисовка с дорисовкой краёв – когда мышь остановится."""
        if not self._pan or not self.transform:
            return
        dx, dy = ev.x - self._pan[0], ev.y - self._pan[1]
        self._pan = [ev.x, ev.y]
        k, ox, oy = self.transform
        self.view = self.transform = (k, ox + dx, oy + dy)
        self.cv.move(self._img_item, dx, dy)
        self._schedule_sharp(120)

    def redraw_src(self):
        if self.src_img is None:
            return
        w, h = max(10, self.cv_src.winfo_width()), max(10, self.cv_src.winfo_height())
        iw, ih = self.src_img.size
        k = min(w / iw, h / ih)
        im = self.src_img.resize((max(1, int(iw * k)), max(1, int(ih * k))), Image.LANCZOS)
        self._tk_imgs['src'] = ImageTk.PhotoImage(im)
        self.cv_src.delete('all')
        self.cv_src.create_image(w // 2, h // 2, image=self._tk_imgs['src'])

    def redraw(self, highlight=None):
        """Полная (чёткая) перерисовка схемы."""
        self._redraw_job = None
        if self.st is None:
            return
        w, h = max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())
        img, self.transform = self._render((w, h), highlight, self.view)
        self._base = (img, self.transform)
        self._show(img)
        self.zoom_lbl.configure(text=f'{self.transform[0] / self._fit()[0] * 100:.0f}%')

    def _show(self, img):
        """Вывести картинку на холст (переиспользуя PhotoImage – это быстрее)."""
        ph = self._tk_imgs.get('res')
        if ph is not None and (ph.width(), ph.height()) == img.size:
            ph.paste(img)
        else:
            self._tk_imgs['res'] = ph = ImageTk.PhotoImage(img)
        self.cv.delete('all')
        self._img_item = self.cv.create_image(0, 0, anchor='nw', image=ph)

    def _preview(self):
        """Мгновенный предпросмотр при зуме: масштабируем уже готовую картинку,
        чёткая перерисовка – когда колесо остановится."""
        base = getattr(self, '_base', None)
        if base is None:
            return
        img, (k0, ox0, oy0) = base
        k, ox, oy = self.view
        f = k / k0
        dx, dy = ox - ox0 * f, oy - oy0 * f
        prev = img.transform(img.size, Image.AFFINE, (1 / f, 0, -dx / f, 0, 1 / f, -dy / f),
                             resample=Image.BILINEAR, fillcolor='white')
        self.transform = self.view
        self._show(prev)
        self.zoom_lbl.configure(text=f'{k / self._fit()[0] * 100:.0f}%')
        self._schedule_sharp()

    def _schedule_sharp(self, delay=140):
        if self._redraw_job:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(delay, self.redraw)

    # ----------------------------------------------------------- мышь
    def _to_model(self, ev):
        k, ox, oy = self.transform
        return (ev.x - ox) / k, (ev.y - oy) / k

    def _nearest_joint(self, x, y):
        g, k = self.st.g, self.transform[0]
        best = None
        for j in self.st.joints:
            jx, jy = g.point_on(g.edges[j.edge], j.t)
            d = math.hypot(jx - x, jy - y) * k
            if d < 12 and (best is None or d < best[0]):
                best = (d, j)
        return best[1] if best else None

    def _nearest_edge(self, x, y):
        g, k = self.st.g, self.transform[0]
        best = None
        for e in g.edges.values():
            (ax, ay), (bx, by) = g.pos(e.a), g.pos(e.b)
            L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1
            t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            d = math.hypot(px - x, py - y) * k
            if d < 10 and (best is None or d < best[0]):
                best = (d, e, t * math.sqrt(L2))
        return best

    def _after_edit(self):
        self.st.sections = compute_sections(self.st)
        name_sections(self.st)
        check_entries(self.st)
        place_signals(self.st)            # светофоры стоят на стыках – пересчитать
        self.update_report()
        self.redraw()

    def on_click(self, ev):
        if not self.st or not self.transform:
            return
        x, y = self._to_model(ev)
        j = self._nearest_joint(x, y)
        if j:
            self.st.joints.remove(j)
            self.st.log.append(f'  [р] удалён стык ({j.rule})')
            self.status.set(f'Стык «{j.rule}» удалён')
        else:
            ne = self._nearest_edge(x, y)
            if not ne:
                return
            _, e, t = ne
            j = Joint(e.id, t, 'р')
            update_negab(self.st, [j])
            self.st.joints.append(j)
            self.st.log.append('  [р] стык добавлен вручную')
            self.status.set('Стык добавлен')
        self._after_edit()

    def on_right(self, ev):
        if not self.st or not self.transform:
            return
        j = self._nearest_joint(*self._to_model(ev))
        if j:
            j.negab = not j.negab
            j.fixed = True
            self.status.set('Стык негабаритный' if j.negab else 'Стык габаритный')
            self._after_edit()

    def on_motion(self, ev):
        if not self.st or not self.transform:
            return
        x, y = self._to_model(ev)
        j = self._nearest_joint(x, y)
        if j:
            self.cv.configure(cursor='X_cursor')
            txt = RULE_TEXT.get(j.rule, '')
            self.status.set(f'Стык «{j.rule}»: {txt}' + (' (негабаритный)' if j.negab else '')
                            + ' — ЛКМ удалить, ПКМ габарит/негабарит')
        elif self._nearest_edge(x, y):
            self.cv.configure(cursor='plus')
        else:
            self.cv.configure(cursor='')


if __name__ == '__main__':
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
