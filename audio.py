# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

"""Keep the PortAudio callback short: only copy audio into a bounded queue."""
import queue
import threading
import time
import os
import sys
# The portable build ships the standard PortAudio driver, without ASIO.
if getattr(sys, "frozen", False):
    os.environ.pop("SD_ENABLE_ASIO", None)
import sounddevice as sd


def input_devices():
    apis = sd.query_hostapis()
    return [(i, d, apis[d['hostapi']]['name']) for i, d in enumerate(sd.query_devices())
            if d['max_input_channels'] > 0]


class AudioInput:
    def __init__(self):
        self.queue = queue.Queue(maxsize=128)
        self.lost = threading.Event()
        self.last_callback = 0.
        self.stream = None

    def start(self, device, rate, channel):
        self.close()
        self.queue = queue.Queue(maxsize=128)
        self.lost.clear()
        sd.check_input_settings(device=device, channels=channel + 1, dtype='float32', samplerate=rate)
        def callback(indata, frames, timing, status):
            self.last_callback = time.monotonic()
            if status:
                self.lost.set()
            try:
                self.queue.put_nowait(indata[:, channel].copy())
            except queue.Full:
                self.lost.set()
        stream = sd.InputStream(device=device, samplerate=rate, channels=channel + 1,
                                dtype='float32', blocksize=0, latency='high', callback=callback)
        self.stream = stream
        try:
            stream.start()
            self.last_callback = time.monotonic()
        except Exception:
            self.close()
            raise
        return int(round(stream.samplerate))

    def close(self):
        if self.stream is not None:
            stream, self.stream = self.stream, None
            try:
                stream.stop()
            finally:
                stream.close()
