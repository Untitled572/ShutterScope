# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

"""Integration test of our GUI class; does not control an existing desktop app."""
import csv
import json
from pathlib import Path
import sys
import time
import tempfile
import tkinter as tk
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from main import App
from core import Config, Detector, demo_signal, read_wav

root=tk.Tk();root.withdraw()
errors=[]
root.report_callback_exception=lambda kind,value,tb:errors.append(str(value))
app=App(root)
assert app.pol_var.get()=='负向开沿'
assert app.config().expected_s==0
assert app.config().mode=='transition'
assert app.config().confirm_samples==3
assert app.config().duration_bounds==(3/48000,30.)
original=(app.pol_var.get(),app.threshold_var.get(),app.baseline)
app.demo()
deadline=time.monotonic()+4
while '分析完成' not in app.status_var.get() and time.monotonic()<deadline:
    root.update()
assert len(app.entries)==1,(len(app.entries),errors)
assert abs(app.entries[0]['m'].seconds-.008)<2/48000
assert original==(app.pol_var.get(),app.threshold_var.get(),app.baseline),'Demo changed real-input settings'
camera_path=Path(__file__).resolve().parent/'fixtures'/'camera_fast_44k.wav'
expected_records=1
if camera_path.exists():
    app.status_var.set('正在验证真实 WAV')
    with patch('main.filedialog.askopenfilename',return_value=str(camera_path)):
        app.import_wav()
    deadline=time.monotonic()+10
    while '分析完成' not in app.status_var.get() and time.monotonic()<deadline:
        root.update()
    actual=[e for e in app.entries if e['source']=='WAV 文件']
    assert len(actual)==5,(len(actual),app.status_var.get(),errors)
    assert abs(actual[-1]['m'].seconds-.0045585)<.00003
    assert actual[-1]['m'].expected_s==0
    expected_records=6
bulb_path=Path(__file__).resolve().parent/'fixtures'/'bulb_44k.wav'
if bulb_path.exists():
    before=len(app.entries)
    app.status_var.set('正在验证 B 门 WAV')
    with patch('main.filedialog.askopenfilename',return_value=str(bulb_path)):
        app.import_wav()
    deadline=time.monotonic()+10
    while '分析完成' not in app.status_var.get() and time.monotonic()<deadline:
        root.update()
    bulb=app.entries[before:]
    assert len(bulb)==6,(len(bulb),app.status_var.get(),errors)
    assert abs(bulb[3]['m'].seconds-1.6988)<.0002
    assert bulb[3]['m'].mode=='transition'
    expected_records+=6
temporary=tempfile.TemporaryDirectory(prefix="shutterscope-test-")
folder=Path(temporary.name)
csv_path=folder/'gui_export_check.csv'
wav_path=folder/'gui_export_check.wav'
with patch('main.filedialog.asksaveasfilename',return_value=str(csv_path)):
    app.export_csv()
with patch('main.filedialog.asksaveasfilename',return_value=str(wav_path)):
    app.export_wav()
with csv_path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
assert len(rows)==expected_records+1 and rows[1][1]=='模拟信号'
rate,wav=read_wav(wav_path)
assert rate==(44100 if camera_path.exists() else 48000) and len(wav)>384
root.deiconify();root.update()
app.toggle_advanced();root.update();assert app.advanced_window.state()!='withdrawn'
app.toggle_advanced();root.update();assert app.advanced_window.state()=='withdrawn'
status=[w for w in root.winfo_children() if isinstance(w,tk.Label) and str(w.cget('textvariable'))==str(app.status_var)][0]
assert status.winfo_ismapped() and status.winfo_y()+status.winfo_height()<=root.winfo_height(), 'Status bar clipped'
root.withdraw()
m=app.entries[0]['m']
for i in range(12):app.add_result(m,'测试',500+i,0,np.zeros(100,np.float32))
assert sum(e['data'] is not None for e in app.entries)==10
app.cursor_result(.008)
assert '8.0000' in app.cursor_var.get()
app.detector=Detector(app.config());app.buffer.append(np.zeros(24000,np.float32))
app.armed=True;app.arm_started_at=time.monotonic()-3;app.last_result_at=0;app.last_wait_status=0
app.show_wait_status();assert '信号低于阈值' in app.status_var.get()
app.detector.start=app.buffer.end-app.rate;app.last_wait_status=0
app.show_wait_status();assert '等待真正闭合沿' in app.status_var.get()
app.detector.start=None
app.running=True;app.armed=True;app.audio.lost.set();app.audio.last_callback=time.monotonic()
app.tick();assert not app.armed and not app.pending
app.running=False
assert not errors,errors
app.close()
report={'gui_demo':'passed','real_settings_preserved':'passed','csv_export':'passed','wav_export':'passed',
        'advanced_window':'passed','raw_history_limit':'passed','manual_cursors':'passed','overflow_disarms':'passed',
        'bulb_wav_import':'passed' if bulb_path.exists() else 'skipped','camera_wav_import':'passed' if camera_path.exists() else 'skipped','low_signal_status':'passed','callback_errors':errors}
report_path=Path(__file__).resolve().parents[1]/'build'/'gui-smoke-report.json'
report_path.parent.mkdir(exist_ok=True)
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
temporary.cleanup()
print(json.dumps(report,ensure_ascii=False))
