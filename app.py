"""Стыки — схема станции: распознавание картинки, стыки и светофоры по методичке.

Запуск:  python app.py [картинка]
Схема:   ЛКМ по пути – добавить стык, ЛКМ по стыку – удалить, ПКМ по стыку – габарит/негабарит,
         колесо – зум, Ctrl+ЛКМ или средняя кнопка – перемещение, 0 – вписать.
Клавиши: Ctrl+O – открыть, Ctrl+S – экспорт PNG, Ctrl+P – печать на 2 листа,
         Ctrl+R – расставить заново.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Literal

import customtkinter as ctk
from PIL import Image, ImageTk

from graph import Joint
from icons import ctk_icon, dots, replace, theme_icon
from joints import RULE_TEXT, Station, place_joints, update_negab, update_sections
from layout import build_station, snap_joints
from parser import parse_image
from render import fit_view, layer_flags, render
from report import report
from resources import resource
from sheets import make_sheets, save_pdf
from signals import footprint, place_signals, prune_signal_joints, signal_rows

APP_NAME = 'Стыки'
APP_SUB = 'Схема станции по методичке ДВГУПС'

# --- дизайн-токены (светлая, тёмная тема) -----------------------------------
BG = ('#F4F5F7', '#111214')
SURFACE = ('#FFFFFF', '#1A1C1F')
SURFACE_2 = ('#F8F9FB', '#202327')
BORDER = ('#E4E6EB', '#2B2E33')
TEXT = ('#15171A', '#E8EAED')
MUTED = ('#6B7280', '#9AA0A6')
ACCENT = ('#2563EB', '#4C8DFF')
ACCENT_HOVER = ('#1D4ED8', '#3B7BF0')
OK = ('#15803D', '#34C27A')
BAD = ('#DC2626', '#FF6B6B')
CANVAS_BG = {'Light': '#E9EBEF', 'Dark': '#0C0D0F'}


def font(size: int = 13, weight: Literal['normal', 'bold'] = 'normal') -> ctk.CTkFont:
    return ctk.CTkFont(family='Segoe UI', size=size, weight=weight)


class Card(ctk.CTkFrame):
    """Карточка боковой панели с заголовком."""

    def __init__(self, master, title: str | None = None, **kw):
        super().__init__(master, fg_color=SURFACE, corner_radius=12, border_width=1,
                         border_color=BORDER, **kw)
        if title:
            ctk.CTkLabel(self, text=title.upper(), font=font(11, 'bold'), text_color=MUTED,
                         anchor='w').pack(fill='x', padx=16, pady=(14, 6))


class App(ctk.CTk):
    def __init__(self, path: str | None = None):
        ctk.set_appearance_mode('system')
        ctk.set_default_color_theme('blue')
        super().__init__(fg_color=BG)
        self.title(f'{APP_NAME} — {APP_SUB}')
        self.geometry('1480x900')
        self.minsize(1120, 680)
        try:
            self.iconbitmap(resource('assets/icon.ico'))
        except tk.TclError:
            pass

        self.st: Station | None = None
        self.parsed: dict | None = None
        self.annots: list = []
        self.src_img: Image.Image | None = None
        self.path: str | None = None
        self.transform: tuple[float, float, float] | None = None
        self.view: tuple[float, float, float] | None = None
        self._base: tuple[Image.Image, tuple[float, float, float]] | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._img_item: int | None = None
        self._redraw_job: str | None = None
        self._pan: list[int] | None = None
        self._toast_job: str | None = None
        self._anim_job: str | None = None
        self._focus = None                                # светофор, к которому приблизились
        self._focus_job: str | None = None
        self._sig_cards: dict[int, ctk.CTkFrame] = {}
        self._sig_selected: ctk.CTkFrame | None = None

        self.layers = {k: tk.BooleanVar(value=v) for k, v in dict(
            grid=True, joints=True, signals=True, numbers=True, letters=False,
            sections=False, section_names=False, annots=True).items()}
        self.two_sheets = tk.BooleanVar(value=False)    # горловины на двух листах
        self.sheet_fmt = tk.StringVar(value='A3')

        self._build()
        self._bind_keys()
        self._show_empty()
        if path:
            self.after(150, lambda: self.load(path))

    # ================================================================ разметка
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_sidebar()
        self._build_center()
        self._build_inspector()
        self._build_statusbar()

    def _build_header(self):
        # шапка как flex-строка с align-items: center – фиксированная высота,
        # у всех элементов общая вертикальная ось
        H = 60
        h = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=H, border_width=0)
        h.grid(row=0, column=0, columnspan=3, sticky='ew')
        h.grid_propagate(False)
        h.grid_rowconfigure(0, weight=1)
        h.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(h, fg_color='transparent', height=34)
        left.grid(row=0, column=0, padx=(18, 0))            # без sticky – по центру строки
        try:                                                # логотип = иконка приложения
            logo_img = ctk.CTkImage(Image.open(resource('assets/icon.png')), size=(34, 34))
            ctk.CTkLabel(left, image=logo_img, text='', width=34, height=34).pack(side='left')
        except OSError:
            pass
        ctk.CTkLabel(left, text=APP_NAME, font=font(16, 'bold'), text_color=TEXT,
                     height=34).pack(side='left', padx=(12, 0))

        actions = ctk.CTkFrame(h, fg_color='transparent', height=40)
        actions.grid(row=0, column=2, padx=14)
        self.theme_btn = ctk.CTkButton(actions, text='', image=theme_icon(22), width=40, height=40,
                                       corner_radius=10, fg_color='transparent',
                                       hover_color=SURFACE_2, command=self.toggle_theme)
        self.theme_btn.pack(side='left', padx=(0, 4))
        self.menu_btn = ctk.CTkButton(actions, text='', image=ctk_icon(dots, 22), width=40,
                                      height=40, corner_radius=10, fg_color='transparent',
                                      hover_color=SURFACE_2, command=self.toggle_menu)
        self.menu_btn.pack(side='left')
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=0, column=0, columnspan=3, sticky='sew')
        self._build_menu()

    # --- выпадающее меню действий -------------------------------------------
    def _build_menu(self):
        m = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12, border_width=1,
                         border_color=BORDER)
        self.menu = m
        self.menu_items: list[ctk.CTkButton] = []
        for text, key, cmd in (('Расставить заново', 'Ctrl+R', self.recompute),
                               ('Сохранить отчёт', '', self.save_report),
                               ('Экспорт PNG', 'Ctrl+S', self.save_png),
                               ('Печать на 2 листа (PDF)', 'Ctrl+P', self.save_sheets)):
            row = ctk.CTkButton(m, text=f'{text}', anchor='w', height=36, width=236,
                                font=font(13), corner_radius=8, fg_color='transparent',
                                hover_color=SURFACE_2, text_color=TEXT,
                                text_color_disabled=MUTED,
                                command=lambda c=cmd: (self.close_menu(), c()))
            row.pack(fill='x', padx=6, pady=(6 if not self.menu_items else 0, 0))
            if key:
                ctk.CTkLabel(row, text=key, font=font(12), text_color=MUTED,
                             fg_color='transparent').place(relx=1.0, rely=0.5, x=-12,
                                                           anchor='e')
            self.menu_items.append(row)
        ctk.CTkFrame(m, height=6, fg_color='transparent').pack()
        self._menu_open = False
        self.bind('<Button-1>', self._click_outside_menu, add='+')
        self.bind('<Escape>', lambda e: self.close_menu(), add='+')

    def toggle_menu(self):
        if self._menu_open:
            self.close_menu()
            return
        state = 'normal' if self.st else 'disabled'
        for b in self.menu_items:
            b.configure(state=state)
        bx = self.menu_btn.winfo_rootx() - self.winfo_rootx() + self.menu_btn.winfo_width()
        by = self.menu_btn.winfo_rooty() - self.winfo_rooty() + self.menu_btn.winfo_height() + 6
        self.menu.place(x=bx, y=by, anchor='ne')
        self.menu.lift()
        self._menu_open = True

    def close_menu(self):
        self.menu.place_forget()
        self._menu_open = False

    def _click_outside_menu(self, ev):
        if not self._menu_open:
            return
        w = ev.widget
        while w is not None:
            if w in (self.menu, self.menu_btn) or str(w).startswith(str(self.menu)) \
                    or str(w).startswith(str(self.menu_btn)):
                return
            w = getattr(w, 'master', None)
        self.close_menu()

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=264, fg_color=BG, corner_radius=0)
        sb.grid(row=1, column=0, sticky='nsew', padx=(16, 0), pady=16)

        src = Card(sb)
        src.pack(fill='x', pady=(0, 12))
        top = ctk.CTkFrame(src, fg_color='transparent', height=30)
        top.pack(fill='x', padx=(16, 10), pady=(10, 4))
        ctk.CTkLabel(top, text='ИСХОДНИК', font=font(11, 'bold'), text_color=MUTED,
                     anchor='w').pack(side='left')
        self.btn_open = ctk.CTkButton(top, text='', image=ctk_icon(replace, 18), width=30,
                                      height=30, corner_radius=8, fg_color='transparent',
                                      hover_color=SURFACE_2, command=self.open)
        self.btn_open.pack(side='right')
        self.btn_open.bind('<Enter>', lambda e: self.set_status('Открыть другую схему (Ctrl+O)'),
                           add='+')
        self.btn_open.bind('<Leave>', lambda e: self.set_status(), add='+')
        self.thumb = ctk.CTkLabel(src, text='Нет изображения', font=font(12), text_color=MUTED,
                                  width=232, height=96, fg_color=SURFACE_2, corner_radius=8)
        self.thumb.pack(fill='x', padx=16)
        self.src_info = ctk.CTkLabel(src, text='', font=font(12), text_color=MUTED, anchor='w',
                                     justify='left')
        self.src_info.pack(fill='x', padx=16, pady=(6, 12))

        sheet = Card(sb, 'Лист')
        sheet.pack(fill='x', pady=(0, 12))
        ctk.CTkSwitch(sheet, text='Два листа (горловины раздельно)', variable=self.two_sheets,
                      font=font(13), text_color=TEXT, progress_color=ACCENT,
                      command=self.relayout, switch_width=34, switch_height=18).pack(
            anchor='w', padx=16, pady=(0, 8))
        self.fmt_seg = ctk.CTkSegmentedButton(
            sheet, values=['A4', 'A3', 'A2'], variable=self.sheet_fmt, font=font(12, 'bold'),
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=SURFACE_2, unselected_hover_color=BORDER, fg_color=SURFACE_2,
            text_color=('#15171A', '#E8EAED'), command=lambda _v: self.relayout())
        self.fmt_seg.pack(fill='x', padx=16, pady=(0, 14))

        lay = Card(sb, 'Слои')
        lay.pack(fill='x')
        names = dict(grid='Миллиметровка', joints='Изолирующие стыки', signals='Светофоры',
                     numbers='Номера и оси', letters='Буквы правил', sections='Участки цветом',
                     section_names='Имена участков', annots='Надписи с картинки')
        for k, text in names.items():
            ctk.CTkSwitch(lay, text=text, variable=self.layers[k], font=font(13),
                          text_color=TEXT, progress_color=ACCENT, command=self.redraw,
                          switch_width=34, switch_height=18).pack(anchor='w', padx=16, pady=4)
        ctk.CTkFrame(lay, height=10, fg_color='transparent').pack()

    def _build_center(self):
        wrap = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12, border_width=1,
                            border_color=BORDER)
        wrap.grid(row=1, column=1, sticky='nsew', padx=16, pady=16)
        self.canvas_wrap = wrap
        self.cv = tk.Canvas(wrap, highlightthickness=0, bd=0, bg=self._canvas_bg(),
                            cursor='arrow')
        self.cv.pack(fill='both', expand=True, padx=2, pady=2)

        # плавающий блок зума
        z = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=10, border_width=1,
                         border_color=BORDER)
        z.place(relx=1.0, rely=1.0, anchor='se', x=-14, y=-14)
        ctk.CTkButton(z, text='−', width=32, height=30, font=font(16), fg_color='transparent',
                      hover_color=SURFACE_2, text_color=TEXT,
                      command=lambda: self.zoom_center(1 / 1.4)).pack(side='left', padx=(4, 0),
                                                                      pady=4)
        self.zoom_lbl = ctk.CTkLabel(z, text='100%', width=54, font=font(12), text_color=MUTED)
        self.zoom_lbl.pack(side='left')
        ctk.CTkButton(z, text='+', width=32, height=30, font=font(16), fg_color='transparent',
                      hover_color=SURFACE_2, text_color=TEXT,
                      command=lambda: self.zoom_center(1.4)).pack(side='left')
        ctk.CTkFrame(z, width=1, height=20, fg_color=BORDER).pack(side='left', padx=4)
        ctk.CTkButton(z, text='Вписать', width=70, height=30, font=font(12),
                      fg_color='transparent', hover_color=SURFACE_2, text_color=TEXT,
                      command=self.zoom_fit).pack(side='left', padx=(0, 4))
        self.zoom_box = z

        # стартовый экран / загрузка – поверх холста
        self.overlay = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=16, border_width=1,
                                    border_color=BORDER)
        self.ov_title = ctk.CTkLabel(self.overlay, text='', font=font(20, 'bold'),
                                     text_color=TEXT)
        self.ov_title.pack(padx=48, pady=(36, 6))
        self.ov_text = ctk.CTkLabel(self.overlay, text='', font=font(13), text_color=MUTED,
                                    justify='center')
        self.ov_text.pack(padx=48)
        self.ov_bar = ctk.CTkProgressBar(self.overlay, mode='indeterminate', width=260,
                                         progress_color=ACCENT)
        self.ov_buttons = ctk.CTkFrame(self.overlay, fg_color='transparent')
        ctk.CTkButton(self.ov_buttons, text='Открыть схему', height=38, width=160,
                      font=font(13, 'bold'), corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.open).pack(side='left', padx=6)
        self.btn_sample = ctk.CTkButton(
            self.ov_buttons, text='Открыть пример', height=38, width=160, font=font(13),
            corner_radius=8, fg_color=SURFACE, hover_color=SURFACE_2, text_color=TEXT,
            border_width=1, border_color=BORDER, command=self.open_sample)
        self.btn_sample.pack(side='left', padx=6)
        self.ov_hint = ctk.CTkLabel(self.overlay, text='', font=font(12), text_color=MUTED)

        self.toast = ctk.CTkLabel(wrap, text='', font=font(13), corner_radius=8,
                                  fg_color=('#15171A', '#E8EAED'),
                                  text_color=('#FFFFFF', '#15171A'), height=34)

        c = self.cv
        c.bind('<Configure>', lambda e: self.schedule_redraw())
        c.bind('<Button-1>', self.on_click)
        c.bind('<Button-3>', self.on_right)
        c.bind('<Motion>', self.on_motion)
        c.bind('<Leave>', lambda e: self.set_status())
        c.bind('<MouseWheel>', self.on_wheel)
        c.bind('<Button-4>', lambda e: self.zoom_at(e.x, e.y, 1.25))
        c.bind('<Button-5>', lambda e: self.zoom_at(e.x, e.y, 0.8))
        for press, drag in (('<Button-2>', '<B2-Motion>'),
                            ('<Control-Button-1>', '<Control-B1-Motion>')):
            c.bind(press, self.pan_start)
            c.bind(drag, self.pan_move)
        c.bind('<Enter>', lambda e: c.focus_set())

    def _build_inspector(self):
        panel = ctk.CTkFrame(self, width=380, fg_color=SURFACE, corner_radius=12,
                             border_width=1, border_color=BORDER)
        panel.grid(row=1, column=2, sticky='nsew', padx=(0, 16), pady=16)
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        # свой переключатель вкладок: у выбранной – белый текст на акценте
        seg = ctk.CTkFrame(panel, fg_color=SURFACE_2, corner_radius=10, height=36)
        seg.grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 8))
        seg.grid_columnconfigure((0, 1), weight=1)
        self.tab_btns: dict[str, ctk.CTkButton] = {}
        for i, name in enumerate(('Светофоры', 'Отчёт')):
            b = ctk.CTkButton(seg, text=name, height=30, corner_radius=8, font=font(13, 'bold'),
                              command=lambda n=name: self.select_tab(n))
            b.grid(row=0, column=i, sticky='ew', padx=3, pady=3)
            self.tab_btns[name] = b

        # явный фон (не «transparent») – иначе в светлой теме у карточек тёмные углы
        self.signals_box = ctk.CTkScrollableFrame(panel, fg_color=SURFACE, corner_radius=0,
                                                  scrollbar_button_color=BORDER)
        self.report_box = ctk.CTkTextbox(panel, font=ctk.CTkFont('Consolas', 12),
                                         fg_color=SURFACE_2, wrap='word',
                                         corner_radius=8, border_width=0)
        self.tab_pages: dict[str, ctk.CTkScrollableFrame | ctk.CTkTextbox] = {
            'Светофоры': self.signals_box, 'Отчёт': self.report_box}
        self._placeholder(self.signals_box, 'Здесь будет список светофоров с ординатами.\n'
                                            'Клик по карточке — приблизить светофор на схеме.')
        self.select_tab('Светофоры')

    def select_tab(self, name: str):
        for n, b in self.tab_btns.items():
            on = n == name
            b.configure(fg_color=ACCENT if on else 'transparent',
                        hover_color=ACCENT_HOVER if on else BORDER,
                        text_color='#FFFFFF' if on else TEXT)
        for n, page in self.tab_pages.items():
            if n == name:
                page.grid(row=1, column=0, sticky='nsew', padx=(12, 6) if n == 'Светофоры'
                          else 12, pady=(0, 12))
            else:
                page.grid_forget()

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=30)
        bar.grid(row=2, column=0, columnspan=3, sticky='nsew')
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=2, column=0, columnspan=3, sticky='new')
        self.status = ctk.CTkLabel(bar, text='', font=font(12), text_color=MUTED, anchor='w')
        self.status.pack(side='left', padx=18)
        self.coord = ctk.CTkLabel(bar, text='', font=font(12), text_color=MUTED, anchor='e')
        self.coord.pack(side='right', padx=18)
        self.set_status()

    def _placeholder(self, box, text):
        for w in box.winfo_children():
            w.destroy()
        ctk.CTkLabel(box, text=text, font=font(13), text_color=MUTED, justify='left',
                     wraplength=320).pack(anchor='w', padx=8, pady=12)

    def _bind_keys(self):
        self.bind('<Control-o>', lambda e: self.open())
        self.bind('<Control-O>', lambda e: self.open())
        self.bind('<Control-s>', lambda e: self.save_png())
        self.bind('<Control-S>', lambda e: self.save_png())
        self.bind('<Control-r>', lambda e: self.recompute())
        self.bind('<Control-p>', lambda e: self.save_sheets())
        for key, f in (('<plus>', 1.4), ('<equal>', 1.4), ('<KP_Add>', 1.4),
                       ('<minus>', 1 / 1.4), ('<KP_Subtract>', 1 / 1.4)):
            self.cv.bind(key, lambda e, f=f: self.zoom_center(f))
        self.cv.bind('<Key-0>', lambda e: self.zoom_fit())

    # ================================================================ состояния
    def _show_overlay(self, title, text, busy=False, buttons=False, hint=''):
        self.ov_title.configure(text=title)
        self.ov_text.configure(text=text)
        self.ov_bar.pack_forget()
        self.ov_buttons.pack_forget()
        self.ov_hint.pack_forget()
        if busy:
            self.ov_bar.pack(pady=(18, 36))
            self.ov_bar.start()
        else:
            self.ov_bar.stop()
        if buttons:
            self.ov_buttons.pack(pady=(22, 10))
        if hint:
            self.ov_hint.configure(text=hint)
            self.ov_hint.pack(pady=(0, 32))
        self.overlay.place(relx=0.5, rely=0.5, anchor='center')
        self.zoom_box.place_forget()

    def _hide_overlay(self):
        self.ov_bar.stop()
        self.overlay.place_forget()
        self.zoom_box.place(relx=1.0, rely=1.0, anchor='se', x=-14, y=-14)

    def _show_empty(self):
        self.btn_sample.configure(state='normal' if os.path.exists(self._sample()) else 'disabled')
        self._show_overlay('Откройте схему станции',
                           'Фото или скан однониточной схемы из задания (PNG, JPG).\n'
                           'Программа распознает пути и стрелки, перечертит схему\n'
                           'на миллиметровке и расставит стыки и светофоры по методичке.',
                           buttons=True, hint='Ctrl+O — открыть файл')

    def set_status(self, text: str | None = None):
        if text is None:
            text = ('ЛКМ по пути — стык · ЛКМ по стыку — удалить · ПКМ — габарит/негабарит · '
                    'колесо — зум · Ctrl+ЛКМ — перемещение · 0 — вписать'
                    if self.st else 'Готов к работе')
        self.status.configure(text=text)

    def show_toast(self, text):
        self.toast.configure(text=f'   {text}   ')
        self.toast.place(relx=0.5, rely=1.0, anchor='s', y=-16)
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(2200, self.toast.place_forget)

    def _canvas_bg(self):
        return CANVAS_BG.get(ctk.get_appearance_mode(), CANVAS_BG['Light'])

    def toggle_theme(self):
        ctk.set_appearance_mode('dark' if ctk.get_appearance_mode() == 'Light' else 'light')
        self.cv.configure(bg=self._canvas_bg())

    # ================================================================ действия
    def _sample(self):
        return resource(os.path.join('samples', 'var96_photo.jpg'))

    def open_sample(self):
        if os.path.exists(self._sample()):
            self.load(self._sample())

    def open(self):
        p = filedialog.askopenfilename(
            title='Схема станции',
            filetypes=[('Изображения', '*.png *.jpg *.jpeg *.bmp *.tif *.tiff'),
                       ('Все файлы', '*.*')])
        if p:
            self.load(p)

    def load(self, path: str):
        self._show_overlay('Распознаю схему…', os.path.basename(path), busy=True)
        self.set_status('Распознавание: бинаризация, скелет, граф путей, компоновка, стыки…')
        fmt = self.sheet_fmt.get() if self.two_sheets.get() else None

        def work():
            try:
                parsed = parse_image(path)
                st, annots = build_station(parsed['graph'], parsed['annots'], sheet_fmt=fmt)
                self.after(0, lambda: self._loaded(path, parsed, st, annots))
            except Exception as ex:                 # показываем ошибку, а не падаем
                msg = str(ex)
                self.after(0, lambda: self._failed(msg))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, msg: str):
        self._show_empty()
        self.set_status('Не удалось распознать схему')
        messagebox.showerror(APP_NAME, f'Не удалось распознать схему:\n{msg}')

    def _loaded(self, path, parsed, st, annots):
        self.path, self.parsed, self.st, self.annots = path, parsed, st, annots
        self.view = None
        self.src_img = Image.open(path).convert('RGB')
        self._hide_overlay()
        self._update_source()
        self.refresh_panels()
        self.redraw()
        self.set_status()

    def relayout(self):
        """Сменился режим листов/формат – перекомпоновать схему (распознавание заново)."""
        self.fmt_seg.configure(state='normal' if self.two_sheets.get() else 'disabled')
        if self.path:
            self.load(self.path)

    def recompute(self):
        if not self.st:
            return
        place_joints(self.st)
        snap_joints(self.st)
        place_signals(self.st)
        prune_signal_joints(self.st)
        self.refresh_panels()
        self.redraw()
        self.show_toast('Стыки и светофоры расставлены заново')

    def save_png(self):
        if not self.st:
            return
        base = os.path.splitext(os.path.basename(self.path or 'схема'))[0]
        p = filedialog.asksaveasfilename(defaultextension='.png', initialfile=f'{base}_стыки.png',
                                         filetypes=[('PNG', '*.png')])
        if not p:
            return
        img, _ = self._render((3200, 1800), None)
        img.save(p)
        self.show_toast(f'Сохранено: {os.path.basename(p)}')

    def save_sheets(self):
        """PDF из двух листов в натуральную величину, разрез у оси станции."""
        if not self.st:
            return
        base = os.path.splitext(os.path.basename(self.path or 'схема'))[0]
        p = filedialog.asksaveasfilename(defaultextension='.pdf',
                                         initialfile=f'{base}_2_листа.pdf',
                                         filetypes=[('PDF', '*.pdf')])
        if not p:
            return
        pages = make_sheets(self.st, self.annots if self.layers['annots'].get() else (),
                            show_grid=self.layers['grid'].get(),
                            show_letters=self.layers['letters'].get(), title=base,
                            fmt=self.sheet_fmt.get() if self.two_sheets.get() else None)
        save_pdf(pages, p)
        self.show_toast(f'Сохранено: {os.path.basename(p)} (2 листа, М 1:1)')

    def save_report(self):
        if not self.st:
            return
        base = os.path.splitext(os.path.basename(self.path or 'схема'))[0]
        p = filedialog.asksaveasfilename(defaultextension='.txt', initialfile=f'{base}_отчёт.txt',
                                         filetypes=[('Текст', '*.txt')])
        if p:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(self._report_text())
            self.show_toast(f'Сохранено: {os.path.basename(p)}')

    # ================================================================ панели
    def _report_text(self):
        assert self.st is not None
        legend = '\n'.join(f'  {k}) {v}' for k, v in RULE_TEXT.items())
        return report(self.st) + '\n\nПравила (п. 2.4 пособия):\n' + legend

    def _update_source(self):
        if self.src_img is None or self.parsed is None:
            return
        iw, ih = self.src_img.size
        k = min(228 / iw, 120 / ih)
        img = ctk.CTkImage(light_image=self.src_img, size=(int(iw * k), int(ih * k)))
        self.thumb.configure(image=img, text='', height=int(ih * k) + 8)
        info = self.parsed['info']
        name = os.path.basename(self.path or '')
        if len(name) > 34:
            name = name[:31] + '…'
        self.src_info.configure(
            text=f'{name}\n{iw}×{ih} px · наклон исправлен на {info["angle"]:+.1f}°')

    def refresh_panels(self):
        st = self.st
        if st is None:
            return
        for w in self.signals_box.winfo_children():
            w.destroy()
        self._sig_cards = {}
        self._sig_selected = None
        for sig, kind, x in signal_rows(st):
            row = ctk.CTkFrame(self.signals_box, fg_color=SURFACE_2, corner_radius=8,
                               border_width=1, border_color=SURFACE_2)
            row.pack(fill='x', padx=4, pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=sig.name, font=font(14, 'bold'), text_color=TEXT, width=52,
                         anchor='w').grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=6,
                                          sticky='w')
            ctk.CTkLabel(row, text=kind, font=font(12), text_color=TEXT, anchor='w').grid(
                row=0, column=1, sticky='w', pady=(6, 0))
            ctk.CTkLabel(row, text=sig.why, font=font(11), text_color=MUTED, anchor='w',
                         wraplength=210, justify='left').grid(row=1, column=1, sticky='w',
                                                              pady=(0, 6))
            ctk.CTkLabel(row, text=f'{x:.0f} мм', font=font(12), text_color=MUTED).grid(
                row=0, column=2, rowspan=2, padx=12)
            self._make_clickable(row, lambda s=sig: self.focus_signal(s))
            self._sig_cards[id(sig)] = row

        self.signals_box._parent_canvas.yview_moveto(0)      # список – с начала
        self.report_box.configure(state='normal')
        self.report_box.delete('1.0', 'end')
        self.report_box.insert('1.0', self._report_text())
        self.report_box.configure(state='disabled')

    # ================================================================ переход к светофору
    def _make_clickable(self, card: ctk.CTkFrame, command):
        """Вся карточка (и её подписи) – одна кнопка: ховер, курсор-рука, клик."""
        def enter(_e):
            if card is not self._sig_selected:
                card.configure(fg_color=BORDER)

        def leave(_e):
            if card is not self._sig_selected:
                card.configure(fg_color=SURFACE_2)

        widgets = [card, *card.winfo_children()]
        for w in widgets:
            w.bind('<Enter>', enter, add='+')
            w.bind('<Leave>', leave, add='+')
            w.bind('<Button-1>', lambda _e: command(), add='+')
            try:
                w.configure(cursor='hand2')
            except (tk.TclError, ValueError):
                pass

    def focus_signal(self, sig):
        """Плавно приблизить схему к светофору и подсветить его."""
        if self.st is None or self.transform is None:
            return
        prev = self._sig_selected
        if prev is not None and prev.winfo_exists():
            prev.configure(fg_color=SURFACE_2, border_color=SURFACE_2)
        card = self._sig_cards.get(id(sig))
        if card is not None:
            card.configure(fg_color=SURFACE_2, border_color=ACCENT)
        self._sig_selected = card

        x0, y0, x1, y1 = footprint(self.st, sig)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        W, H = self._size()
        kfit = self._fit()[0]
        k_t = min(max(min(W / 90.0, H / 55.0), kfit * 2.5), kfit * 60)   # окно ~90×55 мм
        self._focus = sig
        self._animate_to(k_t, cx, cy)
        self.set_status(f'Светофор {sig.name} — {sig.why}')

    def _animate_to(self, k_t, cx, cy, steps=14, interval=16):
        """Переход камеры за ~0,2 с: масштаб – геометрически, центр – линейно, ease-in-out."""
        if self._anim_job:
            self.after_cancel(self._anim_job)
        assert self.transform is not None
        W, H = self._size()
        k0, ox0, oy0 = self.transform
        c0 = ((W / 2 - ox0) / k0, (H / 2 - oy0) / k0)

        def frame(i):
            t = i / steps
            e = 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
            k = k0 * (k_t / k0) ** e
            mx, my = c0[0] + (cx - c0[0]) * e, c0[1] + (cy - c0[1]) * e
            self.view = (k, W / 2 - mx * k, H / 2 - my * k)
            self._preview()
            if i < steps:
                self._anim_job = self.after(interval, lambda: frame(i + 1))
            else:
                self._anim_job = None

        frame(1)

    def _draw_focus(self):
        """Рамка вокруг выбранного светофора (гаснет через 2 с)."""
        if self._focus is None or self.st is None or self.transform is None:
            return
        k, ox, oy = self.transform
        x0, y0, x1, y1 = footprint(self.st, self._focus)
        pad = 2.0
        color = ACCENT[1] if ctk.get_appearance_mode() == 'Dark' else ACCENT[0]
        self.cv.create_rectangle((x0 - pad) * k + ox, (y0 - pad) * k + oy,
                                 (x1 + pad) * k + ox, (y1 + pad) * k + oy,
                                 outline=color, width=3, tags='focus')
        if self._focus_job:
            self.after_cancel(self._focus_job)
        self._focus_job = self.after(2000, self._clear_focus)

    def _clear_focus(self):
        self._focus = None
        self._focus_job = None
        self.cv.delete('focus')

    # ================================================================ отрисовка
    def schedule_redraw(self, delay=80):
        if self._redraw_job:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(delay, self.redraw)

    def _size(self):
        return max(10, self.cv.winfo_width()), max(10, self.cv.winfo_height())

    def _render(self, size, view):
        assert self.st is not None
        o = {k: v.get() for k, v in self.layers.items()}
        return render(self.st, size, annots=self.annots, view=view, **layer_flags(o))

    def _fit(self):
        assert self.st is not None
        return fit_view(self.st, self._size(), self.annots if self.layers['annots'].get() else ())

    def redraw(self):
        """Полная (чёткая) перерисовка схемы."""
        self._redraw_job = None
        if self.st is None:
            return
        img, self.transform = self._render(self._size(), self.view)
        self._base = (img, self.transform)
        self._show(img)
        self._draw_focus()
        self.zoom_lbl.configure(text=f'{self.transform[0] / self._fit()[0] * 100:.0f}%')

    def _show(self, img: Image.Image):
        """Вывести картинку на холст (переиспользуя PhotoImage – это быстрее)."""
        ph = self._photo
        if ph is not None and (ph.width(), ph.height()) == img.size:
            ph.paste(img)
        else:
            self._photo = ph = ImageTk.PhotoImage(img)
        self.cv.delete('all')
        self._img_item = self.cv.create_image(0, 0, anchor='nw', image=ph)

    def _preview(self):
        """Мгновенный предпросмотр при зуме: масштабируем готовую картинку,
        чёткая перерисовка – когда колесо остановится."""
        if self._base is None or self.view is None:
            return
        img, (k0, ox0, oy0) = self._base
        k, ox, oy = self.view
        f = k / k0
        dx, dy = ox - ox0 * f, oy - oy0 * f
        prev = img.transform(img.size, Image.Transform.AFFINE,
                             (1 / f, 0, -dx / f, 0, 1 / f, -dy / f),
                             resample=Image.Resampling.BILINEAR, fillcolor='white')
        self.transform = self.view
        self._show(prev)
        self.zoom_lbl.configure(text=f'{k / self._fit()[0] * 100:.0f}%')
        self.schedule_redraw(140)

    # ================================================================ зум
    def zoom_at(self, sx, sy, factor):
        """Масштаб относительно точки экрана (sx, sy) – она остаётся на месте."""
        if not self.st or not self.transform:
            return
        k, ox, oy = self.transform
        kfit = self._fit()[0]
        nk = min(max(k * factor, kfit * 0.5), kfit * 60)
        f = nk / k
        self.view = (nk, sx - (sx - ox) * f, sy - (sy - oy) * f)
        self._preview()

    def zoom_center(self, factor):
        w, h = self._size()
        self.zoom_at(w / 2, h / 2, factor)

    def _stop_anim(self):
        if self._anim_job:
            self.after_cancel(self._anim_job)
            self._anim_job = None

    def zoom_fit(self):
        self._stop_anim()
        self.view = None
        self.redraw()

    def on_wheel(self, ev):
        self._stop_anim()
        self.zoom_at(ev.x, ev.y, 1.2 if ev.delta > 0 else 1 / 1.2)

    def pan_start(self, ev):
        self._stop_anim()
        if self.transform:
            self._pan = [ev.x, ev.y]
            self.cv.configure(cursor='fleur')

    def pan_move(self, ev):
        """Перетаскивание: сдвигаем готовую картинку, чёткая перерисовка – после остановки."""
        if not self._pan or not self.transform or self._img_item is None:
            return
        dx, dy = ev.x - self._pan[0], ev.y - self._pan[1]
        self._pan = [ev.x, ev.y]
        k, ox, oy = self.transform
        self.view = self.transform = (k, ox + dx, oy + dy)
        self.cv.move('all', dx, dy)                         # картинка и рамка фокуса
        self.schedule_redraw(120)

    # ================================================================ мышь
    def _to_model(self, ev):
        assert self.transform is not None
        k, ox, oy = self.transform
        return (ev.x - ox) / k, (ev.y - oy) / k

    def _nearest_joint(self, x, y):
        assert self.st is not None and self.transform is not None
        g, k = self.st.g, self.transform[0]
        best = None
        for j in self.st.joints:
            jx, jy = g.point_on(g.edges[j.edge], j.t)
            d = math.hypot(jx - x, jy - y) * k
            if d < 12 and (best is None or d < best[0]):
                best = (d, j)
        return best[1] if best else None

    def _nearest_edge(self, x, y):
        assert self.st is not None and self.transform is not None
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

    def _signal_at(self, x, y):
        assert self.st is not None
        for s in self.st.signals:
            b = footprint(self.st, s)
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                return s
        return None

    def _after_edit(self):
        assert self.st is not None
        update_sections(self.st)
        place_signals(self.st)            # светофоры стоят на стыках – пересчитать
        self.refresh_panels()
        self.redraw()

    def on_click(self, ev):
        if not self.st or not self.transform:
            return
        x, y = self._to_model(ev)
        j = self._nearest_joint(x, y)
        if j:
            self.st.joints.remove(j)
            self.st.log.append(f'  [р] удалён стык ({j.rule})')
            self.show_toast('Стык удалён')
        else:
            ne = self._nearest_edge(x, y)
            if not ne:
                return
            _, e, t = ne
            nj = Joint(e.id, t, 'р')
            update_negab(self.st, [nj])
            self.st.joints.append(nj)
            self.st.log.append('  [р] стык добавлен вручную')
            self.show_toast('Стык добавлен')
        self._after_edit()

    def on_right(self, ev):
        if not self.st or not self.transform:
            return
        j = self._nearest_joint(*self._to_model(ev))
        if j:
            j.negab = not j.negab
            j.fixed = True
            self.show_toast('Стык негабаритный' if j.negab else 'Стык габаритный')
            self._after_edit()

    def on_motion(self, ev):
        if not self.st or not self.transform:
            return
        x, y = self._to_model(ev)
        x0 = min(n.x for n in self.st.g.nodes.values())
        self.coord.configure(text=f'ордината {x - x0:.0f} мм')
        j = self._nearest_joint(x, y)
        if j:
            self.cv.configure(cursor='X_cursor')
            self.set_status(f'Стык «{j.rule}» — {RULE_TEXT.get(j.rule, "")}'
                            + (' · негабаритный' if j.negab else '')
                            + ' · ЛКМ — удалить, ПКМ — габарит/негабарит')
            return
        s = self._signal_at(x, y)
        if s:
            self.cv.configure(cursor='arrow')
            self.set_status(f'Светофор {s.name} — {s.why}')
            return
        if self._nearest_edge(x, y):
            self.cv.configure(cursor='plus')
            self.set_status('ЛКМ — поставить стык')
        else:
            self.cv.configure(cursor='arrow')
            self.set_status()


def main():
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()


if __name__ == '__main__':
    main()
