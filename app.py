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
from layout import build_station
from parser import parse_image
from render import render


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
        self._tk_imgs = {}
        self._redraw_job = None

        self.opts = {k: tk.BooleanVar(value=v) for k, v in dict(
            grid=True, joints=True, letters=True, numbers=True, sections=False,
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
        labels = dict(grid='Сетка (мм)', joints='Стыки', letters='Буквы правил',
                      numbers='Номера стрелок', sections='Участки цветом',
                      section_names='Имена участков', annots='Надписи')
        for k, text in labels.items():
            ttk.Checkbutton(bar, text=text, variable=self.opts[k],
                            command=self.redraw).pack(side='left', padx=2)

        body = ttk.PanedWindow(self, orient='horizontal')
        body.pack(fill='both', expand=True)
        left = ttk.PanedWindow(body, orient='vertical')
        body.add(left, weight=4)

        f1 = ttk.LabelFrame(left, text='Исходная картинка')
        self.cv_src = tk.Canvas(f1, bg='#f4f4f4', highlightthickness=0)
        self.cv_src.pack(fill='both', expand=True)
        left.add(f1, weight=1)

        f2 = ttk.LabelFrame(left, text='Распознанная схема со стыками   '
                                       '(ЛКМ – добавить/удалить стык, ПКМ – негабаритный)')
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

        for c in (self.cv, self.cv_src):
            c.bind('<Configure>', lambda e: self.schedule_redraw())
        self.cv.bind('<Button-1>', self.on_click)
        self.cv.bind('<Button-3>', self.on_right)
        self.cv.bind('<Motion>', self.on_motion)

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
        self.src_img = Image.open(path).convert('RGB')
        g = st.g
        info = parsed['info']
        self.status.set(f'Готово: узлов {len(g.nodes)}, рёбер {len(g.edges)}, стрелок {len(st.sw)}, '
                        f'стыков {len(st.joints)}. Наклон фото исправлен на {info["angle"]:.1f}°.')
        self.update_report()
        self.redraw()

    def recompute(self):
        if not self.st:
            return
        place_joints(self.st)
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

    def _render(self, size, highlight=None):
        o = {k: v.get() for k, v in self.opts.items()}
        return render(self.st, size, show_grid=o['grid'], show_joints=o['joints'],
                      show_letters=o['letters'], show_numbers=o['numbers'],
                      show_sections=o['sections'], show_section_names=o['section_names'],
                      show_annots=o['annots'], annots=self.annots, highlight=highlight)

    def redraw(self, highlight=None):
        self._redraw_job = None
        # исходник
        if self.src_img is not None:
            w, h = max(10, self.cv_src.winfo_width()), max(10, self.cv_src.winfo_height())
            iw, ih = self.src_img.size
            k = min(w / iw, h / ih)
            im = self.src_img.resize((max(1, int(iw * k)), max(1, int(ih * k))), Image.LANCZOS)
            self._tk_imgs['src'] = ImageTk.PhotoImage(im)
            self.cv_src.delete('all')
            self.cv_src.create_image(w // 2, h // 2, image=self._tk_imgs['src'])
        # схема
        if self.st is not None:
            w, h = max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())
            img, self.transform = self._render((w, h), highlight)
            self._tk_imgs['res'] = ImageTk.PhotoImage(img)
            self.cv.delete('all')
            self.cv.create_image(0, 0, anchor='nw', image=self._tk_imgs['res'])

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
