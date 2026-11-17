# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

"""ShutterScope — local photodiode shutter timer."""
import csv
import sys
from datetime import datetime
from pathlib import Path
import queue
import time
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
import sounddevice as sd
from audio import AudioInput, input_devices
from version import __version__
from core import Config, Detector, SampleBuffer, describe, nominal, read_wav, write_wav, demo_signal

BG, PANEL, FIELD = '#f3f3f3', '#ffffff', '#f7f7f7'
TEXT, MUTED, ACCENT, GOLD = '#1b1b1b', '#616161', '#0067c0', '#ad6800'
MODE_NAMES = {'快慢门 · 光变沿配对': 'transition', '光电脉冲 · 半高宽': 'pulse', '开闭沿配对 · AC': 'edges', '电平脉冲 · DC': 'level'}

class Waveform(tk.Canvas):
    def __init__(self, parent, on_cursor):
        super().__init__(parent, bg='#ffffff', highlightthickness=0, height=265)
        self.data = np.empty(0, np.float32)
        self.rate, self.offset = 48000, 0
        self.cursors, self.markers = [], []
        self.threshold, self.baseline = .025, 0.
        self.view = (0., 1.)
        self.measurement_level = None
        self.on_cursor = on_cursor
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Button-1>', self.click)
        self.bind('<MouseWheel>', lambda e: self.zoom(.7 if e.delta > 0 else 1.4))

    def set_data(self, data, rate, offset=0, markers=(), focus=False, level=None):
        self.data, self.rate, self.offset = data, rate, offset
        self.measurement_level = level
        self.markers, self.cursors = list(markers), []
        total = max(len(data) / rate, 1 / rate)
        self.view = (0., total)
        if focus and len(markers) == 2:
            a, b = [(x - offset) / rate for x in markers]
            margin = max(.0002, (b - a) * .35)
            self.view = (max(0, a - margin), min(total, b + margin))
        self.draw()

    def fit(self):
        self.view = (0., max(len(self.data) / self.rate, 1 / self.rate))
        self.draw()

    def zoom(self, factor):
        a, b = self.view
        total = max(len(self.data) / self.rate, 1 / self.rate)
        span = min(total, max(8 / self.rate, (b - a) * factor))
        a = max(0, min(total - span, (a + b - span) / 2))
        self.view = (a, a + span)
        self.draw()

    def click(self, event):
        if not len(self.data):
            return
        fraction = (event.x - 55) / max(10, self.winfo_width() - 78)
        if not 0 <= fraction <= 1:
            return
        t = self.view[0] + fraction * (self.view[1] - self.view[0])
        index = min(len(self.data) - 1, max(0, round(t * self.rate)))
        if len(self.cursors) == 2:
            self.cursors = []
        self.cursors.append(index / self.rate)
        self.draw()
        if len(self.cursors) == 2:
            self.on_cursor(abs(self.cursors[1] - self.cursors[0]))

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 100 or h < 70:
            return
        left, top, right, bottom = 55, 18, w - 23, h - 35
        a, b = self.view
        start, end = max(0, int(a * self.rate)), min(len(self.data), int(b * self.rate) + 1)
        segment = self.data[start:end]
        peak = max(.04, float(np.max(np.abs(segment))) * 1.12 if len(segment) else .05,
                   abs(self.baseline) + self.threshold * 1.3)
        def y(value):
            return top + (peak - value) / (2 * peak) * (bottom - top)
        def x(t):
            return left + (t - a) / max(b - a, 1 / self.rate) * (right - left)
        for i in range(5):
            yy = top + i * (bottom - top) / 4
            self.create_line(left, yy, right, yy, fill='#e9e9e9')
            self.create_text(left - 8, yy, text=f'{(1 - i / 2) * peak * 100:.1f}', fill=MUTED, anchor='e', font=('Segoe UI', 8))
        for i in range(7):
            t = a + i * (b - a) / 6
            xx = x(t)
            self.create_line(xx, top, xx, bottom, fill='#efefef')
            self.create_text(xx, bottom + 15, text=f'{t * 1000:.2f}', fill=MUTED, font=('Segoe UI', 8))
        self.create_text(8, 8, text='%FS', anchor='nw', fill=MUTED, font=('Segoe UI', 8))
        self.create_text(right, h - 2, text='ms', anchor='se', fill=MUTED, font=('Segoe UI', 8))
        for level in (self.baseline + self.threshold, self.baseline - self.threshold):
            if abs(level) <= peak:
                self.create_line(left, y(level), right, y(level), fill='#d5b786', dash=(4, 5))
        if self.measurement_level is not None and abs(self.measurement_level) <= peak:
            yy = y(self.measurement_level)
            self.create_line(left, yy, right, yy, fill=GOLD, dash=(6, 3))
            self.create_text(right-5, yy-4, text='50%', anchor='se', fill=GOLD, font=('Segoe UI', 8))
        if len(segment) > 1:
            # Preserve extrema so narrow pulses remain visible when zoomed out.
            step = max(1, int(np.ceil(len(segment) / max(10, int(right - left)))))
            points = []
            for k in range(0, len(segment), step):
                chunk = segment[k:k + step]
                for j in sorted({int(np.argmin(chunk)), int(np.argmax(chunk))}):
                    points.extend((x((start + k + j) / self.rate), y(float(chunk[j]))))
            if len(points) >= 4:
                self.create_line(*points, fill=ACCENT, width=1.3)
        else:
            self.create_text((left + right) / 2, (top + bottom) / 2, text='打开输入预览，观察光电二极管的信号', fill=MUTED)
        for i, marker in enumerate(self.markers):
            t = (marker - self.offset) / self.rate
            if a <= t <= b:
                xx = x(t)
                self.create_line(xx, top, xx, bottom, fill=GOLD, dash=(4, 3), width=2)
                self.create_text(xx + 5, top + 7, anchor='nw', text='开' if i == 0 else '闭', fill=GOLD)
        for i, t in enumerate(self.cursors):
            if a <= t <= b:
                xx = x(t)
                self.create_line(xx, top, xx, bottom, fill='#8764b8', width=2)
                self.create_text(xx + 4, bottom - 8, anchor='sw', text=chr(65 + i), fill='#8764b8')

class App:
    def __init__(self, root):
        self.root = root
        root.title(f'ShutterScope {__version__} · 快门测速仪 · 快慢门版')
        try:
            root.iconbitmap(str(Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets' / 'shutter.ico'))
        except tk.TclError:
            pass
        root.geometry('1220x850')
        root.minsize(1080, 790)
        root.configure(bg=BG)
        self.audio = AudioInput()
        self.running = self.armed = self.frozen = False
        self.detector = None
        self.rate = 48000
        self.buffer = SampleBuffer(12 * self.rate)
        self.entries, self.pending = [], []
        self.last_open = None
        self.run_id = 0
        self.source = '实时输入'
        self.last_plot = 0.
        self.arm_started_at = 0.
        self.last_result_at = 0.
        self.last_wait_status = 0.
        self.current_capture = None
        self.build_style()
        self.build_ui()
        self.refresh_devices()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<space>', self.space)
        root.after(35, self.tick)

    def build_style(self):
        self.root.option_add('*Font', ('Microsoft YaHei UI', 10))
        self.root.option_add('*TCombobox*Listbox.background', FIELD)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('.', background=PANEL, foreground=TEXT, borderwidth=0)
        s.configure('TFrame', background=PANEL)
        s.configure('TLabel', background=PANEL, foreground=TEXT)
        s.configure('Muted.TLabel', foreground=MUTED)
        s.configure('TButton', background=FIELD, foreground=TEXT, padding=(12, 7), borderwidth=1, bordercolor='#e5e5e5', relief='flat')
        s.map('TButton', background=[('active', '#e8e8e8'), ('disabled', '#f5f5f5')], foreground=[('disabled', '#a0a0a0')])
        s.configure('Accent.TButton', background=ACCENT, foreground='#ffffff', font=('Microsoft YaHei UI', 10, 'bold'))
        s.map('Accent.TButton', background=[('active', '#1975c5'), ('disabled', '#c8ddec')])
        s.configure('TCombobox', fieldbackground=FIELD, background=FIELD, foreground=TEXT, padding=5, arrowsize=13)
        s.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT), ('disabled', MUTED)])
        s.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=5)
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28, borderwidth=0, font=('Microsoft YaHei UI', 9))
        s.configure('Treeview.Heading', background=FIELD, foreground=MUTED, padding=6)
        s.map('Treeview', background=[('selected', '#e0effb')])

    def label(self, parent, text, muted=False, **kw):
        return ttk.Label(parent, text=text, style='Muted.TLabel' if muted else 'TLabel', **kw)

    def build_ui(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill='x', padx=24, pady=(19, 15))
        tk.Label(head, text='ShutterScope', bg=BG, fg=TEXT, font=('Segoe UI', 22, 'bold')).pack(side='left')
        tk.Label(head, text='快门速度检测', bg=BG, fg=MUTED).pack(side='left', padx=20, pady=(12, 0))
        ttk.Button(head, text='使用说明', command=self.help).pack(side='right')
        ttk.Button(head, text='关于', command=self.about).pack(side='right', padx=(0, 6))
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True, padx=24, pady=(0, 14))
        left = ttk.Frame(body, padding=18, width=286)
        left.pack(side='left', fill='y', padx=(0, 16))
        left.pack_propagate(False)
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        self.label(left, '输入设备').pack(anchor='w', pady=(0, 9))
        self.device_var = tk.StringVar()
        self.device_box = ttk.Combobox(left, textvariable=self.device_var, state='readonly', width=27)
        self.device_box.pack(fill='x')
        self.device_box.bind('<<ComboboxSelected>>', lambda e: self.update_channels())
        ttk.Button(left, text='刷新输入设备', command=self.refresh_devices).pack(fill='x', pady=7)
        row = ttk.Frame(left)
        row.pack(fill='x', pady=(1, 9))
        self.rate_var, self.channel_var = tk.StringVar(value='48000'), tk.StringVar(value='1')
        self.rate_box = ttk.Combobox(row, textvariable=self.rate_var, values=('44100', '48000', '96000', '192000'), state='readonly', width=11)
        self.rate_box.pack(side='left')
        self.channel_box = ttk.Combobox(row, textvariable=self.channel_var, values=('1', '2'), state='readonly', width=7)
        self.channel_box.pack(side='right')
        self.label(left, '采样率 Hz                       输入声道', True).pack(anchor='w')
        self.preview_btn = ttk.Button(left, text='打开输入预览', command=self.toggle_preview)
        self.preview_btn.pack(fill='x', pady=(10, 15))
        self.label(left, '测量设置').pack(anchor='w', pady=(0, 8))
        self.mode_var = tk.StringVar(value=next(iter(MODE_NAMES)))
        self.mode_box = ttk.Combobox(left, textvariable=self.mode_var, values=tuple(MODE_NAMES), state='readonly')
        self.mode_box.pack(fill='x')
        target_row = ttk.Frame(left)
        target_row.pack(fill='x', pady=(7, 0))
        self.label(target_row, '预计档位', True).pack(side='left')
        self.expected_var = tk.StringVar(value='不限')
        self.expected_box = ttk.Combobox(target_row, textvariable=self.expected_var, state='readonly', width=12, values=('不限', '1/8000 s', '1/4000 s', '1/2000 s', '1/1000 s', '1/500 s', '1/250 s', '1/125 s', '1/100 s', '1/60 s', '1/30 s', '1/15 s', '1/8 s', '1/4 s', '1/2 s', '1 s', '2 s', '4 s', '8 s', '15 s', '30 s'))
        self.expected_box.pack(side='right')
        self.label(left, '仅筛选 ¼–4 倍时长，可选择“不限”', True).pack(anchor='w', pady=(3, 0))
        self.advanced_visible = False
        self.advanced_btn = ttk.Button(left, text='高级参数  ▸', command=self.toggle_advanced)
        self.advanced_window = tk.Toplevel(self.root)
        self.advanced_window.title('高级参数')
        self.advanced_window.geometry('410x470')
        self.advanced_window.configure(bg=PANEL)
        self.advanced_window.transient(self.root)
        self.advanced_window.withdraw()
        self.advanced_window.protocol('WM_DELETE_WINDOW', self.advanced_window.withdraw)
        self.advanced = ttk.Frame(self.advanced_window, padding=18)
        self.advanced.pack(fill='both', expand=True)
        self.pol_var = tk.StringVar(value='负向开沿')
        self.pol_box = ttk.Combobox(self.advanced, textvariable=self.pol_var, values=('自动极性', '正向开沿', '负向开沿'), state='readonly')
        self.pol_box.pack(fill='x', pady=7)
        self.threshold_var, self.min_var = tk.StringVar(value='5.0'), tk.StringVar(value='0.05')
        self.max_var, self.cool_var = tk.StringVar(value='30'), tk.StringVar(value='10')
        self.slope_var = tk.StringVar(value='100')
        self.confirm_var = tk.StringVar(value='3')
        self.edge_time_var = tk.StringVar(value='3')
        self.edge_ratio_var = tk.StringVar(value='8')
        self.step_ratio_var = tk.StringVar(value='35')
        self.param_entries = []
        for text, variable in [('触发阈值（%FS）', self.threshold_var), ('最短曝光 / 消抖（ms）', self.min_var), ('最长曝光（s）', self.max_var), ('测量后冷却（ms）', self.cool_var), ('边沿斜率（%FS/ms）', self.slope_var), ('边沿连续确认（采样点）', self.confirm_var), ('最大边沿过渡（ms）', self.edge_time_var), ('闭沿最小斜率比（%）', self.edge_ratio_var), ('闭沿最小幅度比（%）', self.step_ratio_var)]:
            frame = ttk.Frame(left if variable is self.threshold_var else self.advanced)
            frame.pack(fill='x', pady=4)
            self.label(frame, text, True).pack(side='left')
            entry = ttk.Entry(frame, textvariable=variable, width=8, justify='right')
            entry.pack(side='right')
            self.param_entries.append(entry)
        self.advanced_btn.pack(fill='x', pady=(6, 3))
        self.baseline = 0.
        self.cal_btn = ttk.Button(left, text='遮光校准噪声', command=self.calibrate)
        self.cal_btn.pack(fill='x', pady=(8, 3))
        self.noise_var = tk.StringVar(value='尚未校准噪声')
        self.label(left, '', True, textvariable=self.noise_var, wraplength=247).pack(anchor='w', pady=4)
        self.arm_btn = ttk.Button(left, text='开始测量  [空格]', style='Accent.TButton', command=self.toggle_arm)
        self.arm_btn.pack(fill='x', pady=(9, 4))
        self.label(left, '持续采集；每次曝光完成自动记入历史。', True, wraplength=245).pack(anchor='w', pady=5)
        tools = ttk.Frame(left)
        tools.pack(side='bottom', fill='x')
        self.label(tools, '辅助工具').pack(anchor='w', pady=(9, 6))
        ttk.Button(tools, text='导入 WAV 并分析', command=self.import_wav).pack(fill='x', pady=3)
        ttk.Button(tools, text='载入模拟信号 · 1/125 s', command=self.demo).pack(fill='x', pady=3)
        self.controls = [self.mode_box, self.pol_box, self.cal_btn, self.expected_box] + self.param_entries
        metrics = tk.Frame(right, bg=BG)
        metrics.pack(fill='x', pady=(0, 13))
        self.speed_var, self.ms_var = tk.StringVar(value='—'), tk.StringVar(value='等待一次完整曝光')
        self.nominal_var, self.error_var = tk.StringVar(value='—'), tk.StringVar(value='预计档位或相近档位 / 实测偏差')
        self.period_var = tk.StringVar(value='—')
        self.res_var = tk.StringVar(value='采样间隔 20.83 μs（非精度保证）')
        for i, (title, main, sub) in enumerate([('实测脉宽 / 曝光估计', self.speed_var, self.ms_var), ('参考档位', self.nominal_var, self.error_var), ('重复触发周期', self.period_var, self.res_var)]):
            metrics.columnconfigure(i, weight=1)
            frame = ttk.Frame(metrics, padding=14)
            frame.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else 10, 0))
            self.label(frame, title, True).pack(anchor='w')
            tk.Label(frame, textvariable=main, font=('Segoe UI', 25 if i == 0 else 20, 'bold'), bg=PANEL, fg=ACCENT if i == 0 else TEXT).pack(anchor='w', pady=7)
            self.label(frame, '', True, textvariable=sub, wraplength=250).pack(anchor='w')
        wave_panel = ttk.Frame(right, padding=(14, 10, 14, 5))
        wave_panel.pack(fill='both', expand=True, pady=(0, 13))
        wave_head = ttk.Frame(wave_panel)
        wave_head.pack(fill='x', pady=(0, 4))
        self.wave_var = tk.StringVar(value='信号波形 · 等待输入')
        self.label(wave_head, '', textvariable=self.wave_var).pack(side='left')
        self.freeze_btn = ttk.Button(wave_head, text='冻结 / 实时', command=self.toggle_freeze)
        self.freeze_btn.pack(side='right')
        ttk.Button(wave_head, text='全览', command=lambda: self.plot.fit()).pack(side='right', padx=3)
        ttk.Button(wave_head, text='−', width=3, command=lambda: self.plot.zoom(1.6)).pack(side='right', padx=3)
        ttk.Button(wave_head, text='+', width=3, command=lambda: self.plot.zoom(.6)).pack(side='right')
        self.plot = Waveform(wave_panel, self.cursor_result)
        self.plot.pack(fill='both', expand=True)
        self.cursor_var = tk.StringVar(value='金色线：开 / 闭光变的计时位置 · 半高宽模式另显示 50% 水平线 · 滚轮缩放')
        self.label(wave_panel, '', True, textvariable=self.cursor_var).pack(anchor='w', pady=6)
        history_panel = ttk.Frame(right, padding=14)
        history_panel.pack(fill='x')
        bar = ttk.Frame(history_panel)
        bar.pack(fill='x', pady=(0, 8))
        self.history_var = tk.StringVar(value='测量历史  0')
        self.label(bar, '', textvariable=self.history_var).pack(side='left')
        ttk.Button(bar, text='导出 CSV', command=self.export_csv).pack(side='right')
        ttk.Button(bar, text='保存波形 WAV', command=self.export_wav).pack(side='right', padx=6)
        columns = ('time', 'ms', 'speed', 'error', 'source')
        self.tree = ttk.Treeview(history_panel, columns=columns, show='headings', height=5, selectmode='browse')
        for key, title, width in zip(columns, ('时间', '曝光 ms', '实测速率', '参考偏差', '来源 / 核对提示'), (85, 100, 105, 90, 230)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, stretch=key == 'source', anchor='w')
        scroll = ttk.Scrollbar(history_panel, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='x', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.select_history)
        self.status_var = tk.StringVar(value='就绪。选择实体麦克风输入 → 打开预览 → 遮光校准 → 开始测量。')
        tk.Label(self.root, textvariable=self.status_var, bg='#eaeaea', fg=TEXT, anchor='w', padx=20, pady=10, wraplength=1150).pack(fill='x', side='bottom', before=body)

    def toggle_advanced(self):
        if self.advanced_window.state() == 'withdrawn':
            self.advanced_window.deiconify()
            self.advanced_window.lift()
        else:
            self.advanced_window.withdraw()

    def refresh_devices(self):
        if self.running:
            return
        try:
            self.devices = input_devices()
            self.device_box['values'] = [f'{i} · {d["name"]} [{api}]' for i, d, api in self.devices]
            preferred = next((n for n, (_, d, api) in enumerate(self.devices) if 'realtek' in d['name'].lower() and 'WASAPI' in api), None)
            if preferred is None:
                preferred = next((n for n, (i, _, _) in enumerate(self.devices) if i == sd.default.device[0]), 0)
            if self.devices:
                self.device_box.current(preferred)
                self.update_channels()
            else:
                self.status_var.set('没有可用输入设备。请检查音频驱动和 Windows 麦克风权限。')
        except Exception as e:
            self.status_var.set(f'无法枚举输入：{e}')

    def update_channels(self):
        index = self.device_box.current()
        if 0 <= index < len(self.devices):
            count = min(8, self.devices[index][1]['max_input_channels'])
            self.channel_box['values'] = tuple(str(i + 1) for i in range(count))
            if int(self.channel_var.get()) > count:
                self.channel_var.set('1')

    def config(self, rate=None):
        numbers = [float(v.get()) for v in (self.threshold_var, self.min_var, self.max_var, self.cool_var, self.slope_var)]
        if not all(np.isfinite(x) for x in numbers) or not 0 <= numbers[3] <= 30000:
            raise ValueError('参数必须为有限数值，冷却范围为 0–30000 ms。')
        expected_text = self.expected_var.get().split()[0]
        expected = 0. if expected_text == '不限' else 1 / float(expected_text[2:]) if expected_text.startswith('1/') else float(expected_text)
        return Config(minimum_edge_ratio=float(self.edge_ratio_var.get())/100, minimum_step_ratio=float(self.step_ratio_var.get())/100, maximum_edge_ms=float(self.edge_time_var.get()), confirm_samples=int(self.confirm_var.get()), expected_s=expected, rate=rate or self.rate, threshold=numbers[0] / 100, baseline=self.baseline, minimum_ms=numbers[1], maximum_s=numbers[2], cooldown_s=numbers[3] / 1000, edge_slope=numbers[4] * 10, mode=MODE_NAMES[self.mode_var.get()], polarity={'自动极性': 0, '正向开沿': 1, '负向开沿': -1}[self.pol_var.get()])

    def set_locked(self):
        for widget in (self.device_box, self.rate_box, self.channel_box):
            widget.configure(state='disabled' if self.running else 'readonly')
        for widget in self.controls:
            widget.configure(state='disabled' if self.armed else 'readonly' if isinstance(widget, ttk.Combobox) else 'normal')
        self.preview_btn.configure(text='关闭输入预览' if self.running else '打开输入预览')
        self.arm_btn.configure(text='停止测量  [空格]' if self.armed else '开始测量  [空格]')

    def stop(self):
        self.armed = self.running = False
        try:
            self.audio.close()
        except Exception as e:
            self.status_var.set(f'关闭输入：{e}')
        self.finish_pending(force=True)
        self.set_locked()

    def toggle_preview(self):
        if self.running:
            self.stop()
            self.status_var.set('输入已关闭；已完成的测量仍可导出。')
            return
        try:
            index = self.device_box.current()
            if index < 0:
                raise ValueError('请先选择音频输入设备。')
            rate = int(self.rate_var.get())
            self.config(rate)
            self.rate = self.audio.start(self.devices[index][0], rate, int(self.channel_var.get()) - 1)
            self.buffer = SampleBuffer(int((self.config().maximum_s + 2) * self.rate))
            self.running, self.frozen = True, False
            self.current_capture = None
            self.source = '实时输入'
            self.run_id += 1
            self.last_open = None
            self.res_var.set(f'采样间隔 {1e6 / self.rate:.2f} μs（非精度保证）')
            self.status_var.set('预览中。遮住二极管并校准噪声，再开始测量。声道无信号时可换另一个声道。')
        except Exception as e:
            self.status_var.set(f'打开输入失败：{e}')
            messagebox.showerror('输入未打开', f'{e}\n\n可尝试 48000 Hz、声道 1，或同名设备的其他音频接口。\n权限关闭时，请在 Windows 中自行允许桌面应用访问麦克风。')
        self.set_locked()

    def space(self, event):
        if isinstance(event.widget, (ttk.Entry, ttk.Combobox)):
            return
        self.toggle_arm()
        return 'break'

    def toggle_arm(self):
        if self.armed:
            self.armed = False
            self.finish_pending(force=True)
            self.set_locked()
            self.status_var.set('测量已暂停；输入继续预览。')
            return
        try:
            if not self.running:
                self.toggle_preview()
                if not self.running:
                    return
            config = self.config()
            self.finish_pending(force=True)
            self.detector = Detector(config)
            self.buffer.capacity = int((config.maximum_s + 2) * self.rate)
            self.detector.position = self.buffer.end
            self.detector.ready_at = self.buffer.end + int(.3 * self.rate)
            self.armed = True
            self.arm_started_at = time.monotonic()
            self.last_wait_status = self.arm_started_at
            self.last_open = None
            self.audio.lost.clear()
            lo, hi = config.duration_bounds
            self.status_var.set(f'测量中：预热 0.3 秒，连续 {config.confirm_samples} 点确认；接受 {lo*1000:.3f}–{hi*1000:.1f} ms。请触发快门。')
            self.set_locked()
        except Exception as e:
            messagebox.showerror('参数无效', str(e))

    def calibrate(self):
        if not self.running or self.armed:
            self.status_var.set('请打开输入预览、停止测量，并遮住光电二极管再校准。')
            return
        _, data = self.buffer.get(self.buffer.end - int(.5 * self.rate))
        if len(data) < self.rate // 4:
            self.status_var.set('请等待至少半秒后再次校准。')
            return
        baseline = float(np.median(data))
        sigma = float(np.median(np.abs(data - baseline))) * 1.4826
        threshold = max(.01, sigma * 10, float(np.quantile(np.abs(data - baseline), .999)) * 2.5)
        if threshold > .5:
            self.status_var.set('校准期间信号过强；请遮光并降低输入增益后重试。')
            return
        self.baseline = baseline
        self.threshold_var.set(f'{threshold * 100:.3f}')
        noise_step = float(np.quantile(np.abs(np.diff(data)), .995))
        self.slope_var.set(f'{max(10., noise_step * 2 * self.rate / 10):.1f}')
        self.noise_var.set(f'基线 {baseline * 100:.3f}%FS · 噪声 σ {sigma * 100:.3f}%FS')
        self.status_var.set('噪声阈值已校准。恢复光路后观察波形，必要时提高阈值以避开衰减尾巴。')

    def tick(self):
        try:
            if self.running:
                if self.audio.lost.is_set():
                    self.audio.lost.clear()
                    self.armed = False
                    self.pending.clear()
                    self.last_open = self.detector = None
                    self.set_locked()
                    self.status_var.set('音频发生丢帧：未完成测量已丢弃。请降低采样率后重新开始测量。')
                limit = time.monotonic() + .025
                while time.monotonic() < limit:
                    try:
                        data = self.audio.queue.get_nowait()
                    except queue.Empty:
                        break
                    self.buffer.append(data)
                    if self.armed:
                        for m in self.detector.feed(data):
                            self.pending.append((m, self.source, self.run_id))
                        if self.detector.messages:
                            self.status_var.set(self.detector.messages[-1])
                            self.detector.messages.clear()
                self.finish_pending()
                self.show_wait_status()
                if time.monotonic() - self.audio.last_callback > 2:
                    self.stop()
                    self.status_var.set('音频输入已中断，请检查插头和设备后重新打开预览。')
                if not self.frozen and time.monotonic() - self.last_plot > .09:
                    self.last_plot = time.monotonic()
                    offset, data = self.buffer.get(self.buffer.end - self.rate)
                    try:
                        threshold = float(self.threshold_var.get()) / 100
                        if np.isfinite(threshold) and 0 < threshold <= 1:
                            self.plot.threshold = threshold
                    except ValueError:
                        pass
                    self.plot.baseline = self.baseline
                    self.plot.set_data(data, self.rate, offset)
                    peak = float(np.max(np.abs(data))) if len(data) else 0.
                    self.wave_var.set(f'实时输入 · {self.rate} Hz · 峰值 {peak * 100:.1f}%FS' + (' · 削顶' if peak >= .999 else ''))
        except Exception as e:
            self.stop()
            self.status_var.set(f'采集已停止：{e}')
        self.root.after(35, self.tick)

    def show_wait_status(self):
        now = time.monotonic()
        if not self.armed or self.detector is None:
            return
        interval = .25 if self.detector.start is not None else 1.5
        if now - max(self.arm_started_at, self.last_result_at, self.last_wait_status) < interval:
            return
        self.last_wait_status = now
        if self.detector.start is not None:
            elapsed = max(0., (self.buffer.end-self.detector.start)/self.rate)
            self.status_var.set(f'已检测到开启 · 已经过 {elapsed:.3f} s · 等待真正闭合沿；当前最长曝光 {self.detector.c.duration_bounds[1]:g} s。')
            return
        _, recent = self.buffer.get(self.buffer.end - self.rate // 2)
        if not len(recent):
            return
        peak = float(np.max(np.abs(recent - self.detector.c.baseline)))
        threshold = self.detector.c.threshold
        text = f'等待快门 · 输入峰值 {peak*100:.2f}%FS / 阈值 {threshold*100:.2f}%FS · 已滤除 {self.detector.rejected} 次可疑事件。'
        if peak < threshold:
            text += ' 当前信号低于阈值，请检查光路和输入声道。'
        self.status_var.set(text)

    def finish_pending(self, force=False):
        remaining = []
        for m, source, run in self.pending:
            if not force and self.buffer.end < m.end + .06 * m.rate:
                remaining.append((m, source, run))
                continue
            offset, data = self.buffer.get(int(m.start - .06 * m.rate), int(m.end + .06 * m.rate))
            self.add_result(m, source, run, offset, data)
        self.pending = remaining

    def reference(self, m):
        if m.expected_s:
            reference = m.expected_s
            name = f'1/{1/reference:g} s' if reference < 1 else f'{reference:g} s'
            return name, (m.seconds / reference - 1) * 100, float(np.log2(m.seconds / reference))
        return nominal(m.seconds)

    def add_result(self, m, source, run, offset, data):
        period = None
        if self.last_open is not None and self.last_open[0] == run:
            period = (m.start - self.last_open[1]) / m.rate
        self.last_open = (run, m.start)
        stamp = datetime.now().astimezone().isoformat(timespec='seconds')
        entry = dict(m=m, source=source, run=run, offset=offset, data=data, stamp=stamp,
                     period=period, device=self.device_var.get(), channel=self.channel_var.get())
        self.entries.append(entry)
        self.last_result_at = time.monotonic()
        if len(self.entries) > 10:
            self.entries[-11]['data'] = None
        name, error, ev = self.reference(m)
        self.tree.insert('', 0, iid=str(len(self.entries) - 1), values=(stamp[11:19], f'{m.seconds * 1000:.4f}',
                         describe(m.seconds), f'{error:+.1f}%', source + (' · 点数偏少' if m.samples < 20 else '')))
        self.history_var.set(f'测量历史  {len(self.entries)}')
        self.show_entry(entry)
        self.status_var.set(f'{source}：{m.seconds * 1000:.4f} ms，{m.samples:.1f} 个采样间隔。{m.quality}。' + ('继续等待下一次曝光。' if self.armed else ''))

    def show_entry(self, entry):
        m = entry['m']
        name, error, ev = self.reference(m)
        self.speed_var.set(describe(m.seconds))
        self.ms_var.set(f'{m.seconds * 1000:.4f} ms  ·  {entry["source"]}')
        self.nominal_var.set(name)
        self.error_var.set(f'{error:+.2f}% 时长  /  {ev:+.3f} EV')
        period = entry['period']
        self.period_var.set(f'{period:.3f} s' if period else '—')
        self.res_var.set(f'{1 / period:.3f} Hz · 闪烁频率' if period else f'采样间隔 {1e6 / m.rate:.2f} μs')
        self.current_capture, self.frozen = entry, True
        self.wave_var.set(f'{entry["source"]} · 已捕获 · {m.quality}')
        if entry['data'] is not None:
            self.plot.threshold, self.plot.baseline = m.threshold, m.baseline
            self.plot.set_data(entry['data'], m.rate, entry['offset'], (m.start, m.end), focus=True, level=m.half_level)
        else:
            self.plot.set_data(np.empty(0, np.float32), m.rate)
            self.wave_var.set('该条波形已释放；仅保留最近 10 条原始波形，历史数据仍可导出')

    def select_history(self, event):
        selected = self.tree.selection()
        if selected:
            self.show_entry(self.entries[int(selected[0])])

    def toggle_freeze(self):
        if self.frozen and self.running:
            self.frozen = False
            self.current_capture = None
            self.wave_var.set('实时输入')
        elif len(self.plot.data):
            self.frozen = True
            self.current_capture = dict(data=self.plot.data.copy(), m=None, rate=self.plot.rate)
            self.wave_var.set('波形已冻结 · 点击两点手动核对')

    def cursor_result(self, seconds):
        if not self.frozen:
            self.cursor_var.set('请先冻结波形后放置两个游标。')
            return
        self.cursor_var.set(f'手动游标 Δt = {seconds * 1000:.4f} ms' + (f'  ·  {describe(seconds)}' if seconds > 0 else '') + '（不写入自动测量历史）')

    def offline(self, data, rate, source, config=None):
        self.stop()
        self.run_id += 1
        self.last_open = None
        self.rate, self.source = rate, source
        config = config or self.config(rate)
        detector = Detector(config)
        self.frozen = True
        self.plot.threshold, self.plot.baseline = config.threshold, config.baseline
        self.plot.set_data(data, rate)
        self.current_capture = dict(data=data, m=None, rate=rate)
        self.wave_var.set(f'{source} · {rate} Hz · 分析中')
        state = {'position': 0, 'count': 0}
        token = self.run_id
        def step():
            if self.run_id != token or self.running:
                return
            start = state['position']
            end = min(len(data), start + rate)
            results = detector.feed(data[start:end])
            for m in results:
                lo, hi = max(0, int(m.start - .06 * rate)), min(len(data), int(m.end + .06 * rate))
                self.add_result(m, source, token, lo, data[lo:hi].copy())
            state['count'] += len(results)
            state['position'] = end
            if end < len(data):
                self.root.after(1, step)
            else:
                note = detector.messages[-1] if detector.messages else ''
                if detector.start is not None:
                    note = '文件结尾仍未检测到闭合沿，该次未计入。'
                self.status_var.set(f'{source}分析完成：找到 {state["count"]} 次完整曝光。{note}')
                if not state['count']:
                    self.wave_var.set(f'{source} · 未找到完整曝光，请调整阈值、极性或模式')
        self.root.after(1, step)

    def demo(self):
        mode = MODE_NAMES[self.mode_var.get()]
        self.offline(demo_signal(mode=mode), 48000, '模拟信号', Config(mode=mode))

    def import_wav(self):
        path = filedialog.askopenfilename(title='选择整数 PCM WAV', filetypes=[('PCM WAV', '*.wav')])
        if not path:
            return
        try:
            rate, data = read_wav(path, int(self.channel_var.get()) - 1)
            self.offline(data, rate, 'WAV 文件', self.config(rate))
        except Exception as e:
            messagebox.showerror('无法分析 WAV', str(e))

    def export_csv(self):
        if not self.entries:
            self.status_var.set('还没有完整测量可导出。')
            return
        path = filedialog.asksaveasfilename(title='导出测量记录', defaultextension='.csv', initialfile='shutter_measurements.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['时间', '来源', '曝光秒', '曝光毫秒', '实测速率', '标称档位', '时长偏差百分比', '偏差EV', '采样率Hz', '采样间隔数', '检测模式', '开沿极性', '阈值FS', '基线FS', '峰值FS', '重复周期秒', '质量提示', '输入设备', '声道', '预计曝光秒'])
                for entry in self.entries:
                    m = entry['m']
                    name, error, ev = self.reference(m)
                    writer.writerow([entry['stamp'], entry['source'], m.seconds, m.seconds * 1000, describe(m.seconds), name, error, ev, m.rate, m.samples, m.mode, m.polarity, m.threshold, m.baseline, m.peak, entry['period'] or '', m.quality, entry['device'], entry['channel'], m.expected_s or ''])
            self.status_var.set(f'已导出 {len(self.entries)} 条记录：{path}')
        except OSError as e:
            messagebox.showerror('导出失败', str(e))

    def export_wav(self):
        capture = self.current_capture
        if not capture or capture['data'] is None:
            self.status_var.set('请先捕获或冻结波形；原始波形只保留最近 10 条。')
            return
        path = filedialog.asksaveasfilename(title='保存当前波形', defaultextension='.wav', initialfile='shutter_waveform.wav', filetypes=[('PCM WAV', '*.wav')])
        if path:
            try:
                rate = capture['m'].rate if capture.get('m') else capture['rate']
                write_wav(path, rate, capture['data'])
                self.status_var.set(f'已保存 16 位单声道 PCM WAV：{path}')
            except Exception as e:
                messagebox.showerror('保存失败', str(e))

    def about(self):
        from tkinter.scrolledtext import ScrolledText
        dialog = tk.Toplevel(self.root)
        dialog.title(f'关于 ShutterScope {__version__}')
        dialog.geometry('760x600')
        dialog.configure(bg=PANEL)
        heading = ttk.Label(dialog, padding=16, text=f'ShutterScope {__version__}\nCopyright (C) 2026 Untitled572\nGPLv3：可按许可修改与再分发；本程序不提供担保。\n源代码：https://github.com/Untitled572/ShutterScope')
        heading.pack(fill='x')
        text = ScrolledText(dialog, wrap='word', font=('Consolas', 9), bg=PANEL, fg=TEXT)
        text.pack(fill='both', expand=True, padx=16, pady=(0,16))
        license_path = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'LICENSE'
        text.insert('1.0', license_path.read_text(encoding='utf-8'))
        text.configure(state='disabled')

    def help(self):
        messagebox.showinfo('ShutterScope · 使用说明',
            '1. 常亮光源照射快门，二极管放在快门后方待测位置。\n'
            '2. 选择实体麦克风输入，打开预览，遮住二极管后校准噪声。\n'
            '3. 恢复光路后开始测量；结果完成时自动捕获波形。\n'
            '4. 默认快慢门模式分别测开启和关闭的局部光变沿。\n'
            '   信号在曝光中衰减回零时仍继续等待关闭，默认最长 30 秒。\n'
            '   半高宽模式保留用于单向脉冲核对，不适合交流耦合慢门。\n'
            '   它适合不对称回摆的光电信号，不要求关闭后达到相反电压。\n'
            '   AC 模式用于两次相反极性突变；DC 模式按固定电平计时。\n'
            '5. 预计档位只筛选 ¼–4 倍范围；显示时长仍由波形实际测量。\n'
            '   默认不限速度，未知档位不会被预计值过滤。\n'
            '   默认连续 3 个采样点确认边沿；拒绝的毛刺不进入冷却。\n'
            '6. 边沿斜率过滤缓慢回摆；慢上升信号可降低斜率，设 0 为关闭。\n'
            '   冷却时间需要短于重复测量间隔；最短时间会丢弃更短的候选。\n'
            '7. 1 Hz 闪烁用于通路验证；重复周期与每次亮起时长分别显示。\n\n'
            '建议关闭音频降噪、自动增益、回声消除等增强；软件不修改系统设置。\n'
            '采样间隔不代表整套硬件的测量精度。只测二极管位置的局部曝光。\n'
            '音频仅在本机内存处理，主动保存时才写出 WAV。\n'
            '原始波形保留最近 10 条，关闭程序前请导出需要的结果。')

    def close(self):
        self.stop()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    def callback_error(kind, value, tb):
        messagebox.showerror('程序错误', ''.join(traceback.format_exception_only(kind, value)))
    root.report_callback_exception = callback_error
    root.mainloop()

def packaged_self_test(report_path):
    """Exercise the frozen GUI and detector without opening an audio stream."""
    import json
    root = None
    app = None
    payload = {'ok': False, 'version': __version__}
    try:
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        app.demo()
        deadline = time.monotonic() + 10
        while not app.entries and time.monotonic() < deadline:
            root.update()
            time.sleep(.002)
        if len(app.entries) != 1 or abs(app.entries[0]['m'].seconds-.008) > 2/48000:
            raise RuntimeError('Frozen detector/GUI demo check failed')
        payload.update(ok=True, tcl=root.tk.call('info', 'patchlevel'),
                       audio_driver=Path(sd._libname).name,
                       measured_seconds=app.entries[0]['m'].seconds)
    except Exception as error:
        payload['error'] = f'{type(error).__name__}: {error}'
    finally:
        if app is not None:
            app.close()
        elif root is not None:
            root.destroy()
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if payload['ok'] else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        raise SystemExit(packaged_self_test(sys.argv[2]))
    main()
