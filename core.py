# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

"""Sample-clock shutter timing; deliberately independent of the GUI/audio driver."""
from dataclasses import dataclass
from collections import deque
from array import array
from pathlib import Path
import math
import wave
import numpy as np
from transitions import TransitionTracker

STANDARD_SPEEDS = (8000, 4000, 2000, 1000, 500, 250, 125, 60, 30, 15, 8, 4, 2, 1)

@dataclass(frozen=True)
class Config:
    rate: int = 48000
    threshold: float = .025
    baseline: float = 0.0
    mode: str = 'edges'
    polarity: int = 0
    minimum_ms: float = .05
    maximum_s: float = 10.0
    cooldown_s: float = .01
    edge_slope: float = 1000.0  # FS/second: 100 %FS per millisecond
    confirm_samples: int = 3
    expected_s: float = 0.0  # Optional search window: one quarter to four times this duration
    maximum_edge_ms: float = 3.0
    minimum_edge_ratio: float = .08
    minimum_step_ratio: float = .35

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.rate, self.threshold, self.baseline, self.minimum_ms, self.maximum_s, self.cooldown_s, self.edge_slope, self.expected_s, self.maximum_edge_ms, self.minimum_edge_ratio, self.minimum_step_ratio)):
            raise ValueError('参数必须为有限数值')
        if not isinstance(self.confirm_samples, int) or not 1 <= self.confirm_samples <= 32:
            raise ValueError('边沿确认采样数必须是 1–32 的整数')
        if not 0 <= self.expected_s <= 30:
            raise ValueError('预计曝光必须在 0–30 秒之间，0 表示不限')
        if self.cooldown_s < 0 or self.edge_slope < 0:
            raise ValueError('冷却时间与边沿斜率不得为负')
        if self.rate <= 0 or not 0 < self.threshold <= 1:
            raise ValueError('采样率或阈值无效')
        if self.maximum_edge_ms <= 0 or self.maximum_edge_ms > 100:
            raise ValueError('最大边沿过渡必须在 0–100 ms 之间')
        if not 0 <= self.minimum_step_ratio <= 1:
            raise ValueError('闭沿最小幅度比必须在 0–100% 之间')
        if not 0 <= self.minimum_edge_ratio <= 1:
            raise ValueError('闭沿最小斜率比必须在 0–100% 之间')
        if self.mode not in ('edges', 'level', 'pulse', 'transition') or self.polarity not in (-1, 0, 1):
            raise ValueError('检测模式或极性无效')
        if not 0 <= self.minimum_ms / 1000 < self.maximum_s <= 30:
            raise ValueError('最短时间必须小于最长时间（上限 30 秒）')
        if self.duration_bounds[0] >= self.duration_bounds[1]:
            raise ValueError('最短/最长时间与预计档位范围没有交集')

    @property
    def duration_bounds(self):
        lower = max(3 / self.rate, self.minimum_ms / 1000)
        upper = self.maximum_s
        if self.expected_s:
            lower = max(lower, self.expected_s / 4)
            upper = min(upper, self.expected_s * 4)
        return lower, upper

@dataclass(frozen=True)
class Measurement:
    start: float
    end: float
    rate: int
    mode: str
    polarity: int
    peak: float
    threshold: float
    baseline: float
    expected_s: float = 0.0
    half_level: float | None = None

    @property
    def seconds(self):
        return (self.end - self.start) / self.rate

    @property
    def samples(self):
        return self.end - self.start

    @property
    def quality(self):
        if self.samples < 20:
            return '采样点偏少，建议复核'
        if self.mode == 'transition':
            return '局部光变沿间隔，请核对开闭沿'
        return '半高宽估计，请核对光变' if self.mode == 'pulse' else '请核对开闭沿'


def describe(seconds):
    return f'1/{1 / seconds:.1f} s' if seconds < 1 else f'{seconds:.3f} s'


def nominal(seconds):
    options = [1 / d for d in STANDARD_SPEEDS] + [2., 4., 8., 15., 30.]
    target = min(options, key=lambda x: abs(math.log2(seconds / x)))
    name = f'1/{round(1 / target)} s' if target < 1 else f'{target:g} s'
    return name, (seconds / target - 1) * 100, math.log2(seconds / target)


class Detector:
    """Confirm edges across blocks, while keeping the first crossing timestamp.

    Unconfirmed excursions never occupy the measurement state. Rejected events
    do not enter cooldown. A stronger, same-polarity opening can replace a weak
    false start before the closing edge arrives. Duration filtering is optional.
    """
    def __init__(self, config):
        self.c = config
        self.position = 0
        self.previous = 0.0
        self.start = None
        self.direction = 0
        self.peak = 0.
        self.clipped = False
        self.quiet = 0
        self.ready_at = 0
        self.is_ready = config.mode == 'edges' and config.edge_slope > 0
        self.close_candidate = None
        self.release_count = 0
        self.edge_candidate = None
        self.opening_strength = 0.
        self.opening_amplitude = 0.
        self.measurement_level = None
        self.messages = []
        self.rejected = 0
        self.reanchored = 0
        self.pulse_prefix = deque(maxlen=max(8, int((config.maximum_edge_ms + 1) * config.rate / 1000)))
        self.pulse_trace = None
        self.pulse_offset = 0
        self.pulse_release_at = None
        self.transition_tracker = TransitionTracker(config) if config.mode == 'transition' else None

    def crossing(self, index, previous, current, threshold):
        if current == previous:
            return float(index)
        return index - 1 + min(1., max(0., (threshold - previous) / (current - previous)))

    def reset_event(self, index, completed=False):
        self.start = None
        self.measurement_level = None
        self.close_candidate = None
        self.release_count = 0
        self.edge_candidate = None
        self.pulse_trace = None
        self.pulse_release_at = None
        self.quiet = 0
        self.is_ready = self.c.mode == 'edges' and self.c.edge_slope > 0
        # A noise rejection must not hide a real shutter arriving immediately.
        self.ready_at = index + (int(self.c.cooldown_s * self.c.rate) if completed else 0)

    def activate(self, edge, replacement=False):
        self.start = edge['time']
        self.direction = edge['direction']
        self.peak = edge['peak']
        self.clipped = edge['clipped']
        self.opening_strength = edge['strength']
        self.close_candidate = None
        self.release_count = 0
        if replacement:
            self.reanchored += 1
        self.edge_candidate = None

    def complete(self, end, index, results):
        c = self.c
        duration = (end - self.start) / c.rate
        lower, upper = c.duration_bounds
        accepted = lower <= duration <= upper and not self.clipped
        if accepted:
            results.append(Measurement(self.start, end, c.rate, c.mode, self.direction,
                                       self.peak, c.threshold, c.baseline, c.expected_s, self.measurement_level))
        else:
            self.rejected += 1
            if self.clipped:
                self.messages.append('信号已削顶：本次丢弃，请降低麦克风增益或光强。')
            elif duration < lower:
                self.messages.append('已忽略短毛刺或范围外事件，继续等待快门。')
            else:
                self.messages.append('已忽略范围外事件，继续等待快门。')
        self.reset_event(index, completed=accepted)

    def feed(self, data):
        if self.c.mode == 'transition':
            return self.feed_transitions(data)
        if self.c.mode == 'pulse':
            return self.feed_pulse(data)
        results = []
        c = self.c
        quiet_needed = max(3, int(.005 * c.rate))
        _, maximum = c.duration_bounds
        for raw in np.asarray(data).reshape(-1):
            raw = float(raw)
            value = raw - c.baseline
            index = self.position
            self.position += 1
            previous = self.previous
            self.previous = value
            if self.start is not None:
                self.peak = max(self.peak, abs(raw))
                self.clipped |= abs(raw) >= .999
                # Permit a closing edge at the upper bound to finish confirmation.
                if index - self.start > maximum * c.rate + c.confirm_samples:
                    self.rejected += 1
                    self.messages.append('等待闭合沿超时：已丢弃可疑事件，继续等待快门。')
                    self.reset_event(index)
            if index < self.ready_at:
                continue
            if self.start is None:
                self.quiet = self.quiet + 1 if abs(value) < c.threshold * .45 else 0
                if self.quiet >= quiet_needed:
                    self.is_ready = True
            # Confirm an excursion for N consecutive samples before accepting it.
            edge = self.edge_candidate
            if edge is not None:
                if value * edge['direction'] >= c.threshold:
                    edge['count'] += 1
                    edge['peak'] = max(edge['peak'], abs(raw))
                    edge['clipped'] |= abs(raw) >= .999
                else:
                    self.edge_candidate = None
                    edge = None
                    self.rejected += 1
            if edge is not None and edge['count'] >= c.confirm_samples:
                self.edge_candidate = None
                if self.start is None:
                    self.activate(edge)
                elif edge['direction'] == self.direction:
                    self.activate(edge, replacement=True)
                else:
                    self.complete(edge['time'], index, results)
                continue
            # DC closing uses the original threshold crossing with release hysteresis.
            if self.start is not None and c.mode == 'level':
                oriented, old = value * self.direction, previous * self.direction
                if old >= c.threshold > oriented:
                    self.close_candidate = self.crossing(index, old, oriented, c.threshold)
                    self.release_count = 0
                if oriented >= c.threshold:
                    self.close_candidate = None
                    self.release_count = 0
                if self.close_candidate is not None:
                    self.release_count = self.release_count + 1 if oriented <= c.threshold * .45 else 0
                    if self.release_count >= c.confirm_samples:
                        self.complete(self.close_candidate, index, results)
                continue
            if edge is not None:
                continue
            direction = 1 if value >= c.threshold else -1 if value <= -c.threshold else 0
            if direction == 0 or previous * direction >= c.threshold:
                continue
            strength = (value - previous) * direction
            if c.mode == 'edges' and strength * c.rate < c.edge_slope:
                continue
            if self.start is None:
                if not self.is_ready or (c.polarity and direction != c.polarity):
                    continue
            elif direction == self.direction:
                if strength < self.opening_strength * 1.5:
                    continue
            self.edge_candidate = dict(time=self.crossing(index, previous * direction, value * direction, c.threshold),
                                       direction=direction, count=1, peak=abs(raw),
                                       clipped=abs(raw) >= .999, strength=strength)
            if c.confirm_samples == 1:
                edge = self.edge_candidate
                self.edge_candidate = None
                if self.start is None:
                    self.activate(edge)
                elif direction == self.direction:
                    self.activate(edge, replacement=True)
                else:
                    self.complete(edge['time'], index, results)
        return results

    def feed_transitions(self, data):
        c=self.c;results=[];tracker=self.transition_tracker
        _,maximum=c.duration_bounds
        for raw in np.asarray(data).reshape(-1):
            raw=float(raw);index=self.position;self.position+=1
            if self.start is not None:
                self.peak=max(self.peak,abs(raw));self.clipped|=abs(raw)>=.999
                if index-self.start>(maximum+2*c.maximum_edge_ms/1000)*c.rate:
                    self.rejected+=1
                    self.messages.append('等待真正闭合沿超时，已重新等待；B 门请检查最长曝光设置。')
                    self.reset_event(index)
            if index<self.ready_at:
                continue
            before=tracker.rejected
            events=tracker.push(raw,index)
            self.rejected+=tracker.rejected-before
            for edge in events:
                if self.start is None:
                    if c.polarity and edge.direction!=c.polarity:
                        continue
                    self.start=edge.time;self.direction=edge.direction
                    self.opening_strength=edge.strength;self.opening_amplitude=edge.amplitude;self.peak=edge.peak;self.clipped=edge.clipped
                elif edge.direction==self.direction:
                    if edge.strength>=self.opening_strength*1.5:
                        self.start=edge.time;self.opening_strength=edge.strength;self.opening_amplitude=edge.amplitude
                        self.peak=edge.peak;self.clipped=edge.clipped;self.reanchored+=1
                elif edge.strength>=self.opening_strength*c.minimum_edge_ratio and edge.amplitude>=self.opening_amplitude*c.minimum_step_ratio:
                    self.peak=max(self.peak,edge.peak);self.clipped|=edge.clipped
                    self.complete(edge.time,index,results)
                    tracker.reset()
                else:
                    self.rejected+=1
        return results

    def finish_pulse(self, index, results):
        """Compute the width at half peak, then validate optical transition speed.

        The amplitude threshold only locates a pulse. Closing need not cross to
        an equal positive voltage, and the per-sample slope gate is not used.
        Slow lighting/handling changes are rejected by their 10–50% edge times.
        """
        c = self.c
        values = (np.asarray(self.pulse_trace, dtype=np.float64) - c.baseline) * self.direction
        trigger = max(0, int(self.start-self.pulse_offset))
        last_peak = min(len(values), self.pulse_release_at-self.pulse_offset+1)
        peak_index = trigger + int(np.argmax(values[trigger:last_peak]))
        amplitude = float(values[peak_index])
        def crossing_at(fraction, rising, first, last, latest=False):
            level = amplitude * fraction
            before, after = values[first:last-1], values[first+1:last]
            mask = (before < level) & (after >= level) if rising else (before >= level) & (after < level)
            matches = np.flatnonzero(mask)
            if latest:
                matches = matches[::-1]
            for match in matches:
                i = first + int(match)
                following = values[i+1:i+1+c.confirm_samples]
                if len(following) < c.confirm_samples:
                    continue
                stable = np.all(following >= level) if rising else np.all(following < level)
                if stable:
                    return i + float((level - values[i]) / (values[i+1] - values[i]))
            return None
        opening50 = crossing_at(.5, True, 0, peak_index+1, latest=True)
        opening10 = crossing_at(.1, True, 0, min(peak_index+1, int(opening50)+2) if opening50 is not None else peak_index+1, latest=True)
        closing50 = crossing_at(.5, False, peak_index, len(values))
        closing10 = crossing_at(.1, False, peak_index, len(values))
        if None in (opening10, opening50, closing50, closing10):
            self.rejected += 1
            self.messages.append('已忽略未形成清晰脉冲的缓慢光照变化。')
            self.reset_event(index)
            return
        transition_limit = c.maximum_edge_ms * c.rate / 1000
        if opening50-opening10 > transition_limit or closing10-closing50 > transition_limit:
            self.rejected += 1
            self.messages.append('已忽略边沿过缓的光照变化；如需测慢信号，可调大最大边沿过渡。')
            self.reset_event(index)
            return
        self.start = self.pulse_offset + opening50
        self.measurement_level = c.baseline + self.direction*amplitude*.5
        self.complete(self.pulse_offset + closing50, index, results)

    def feed_pulse(self, data):
        c = self.c
        results = []
        quiet_needed = max(3, int(.005 * c.rate))
        _, maximum = c.duration_bounds
        for item in np.asarray(data).reshape(-1):
            raw = float(item)
            value = raw - c.baseline
            index = self.position
            self.position += 1
            previous = self.previous
            self.previous = value
            self.pulse_prefix.append((index, raw))
            if self.start is not None:
                self.pulse_trace.append(raw)
                self.peak = max(self.peak, abs(raw))
                self.clipped |= abs(raw) >= .999
                # Allow for trigger-to-half-height offset and release confirmation.
                if index-self.start > (maximum + 2*c.maximum_edge_ms/1000) * c.rate + c.confirm_samples:
                    self.rejected += 1
                    self.messages.append('光电脉冲超时，已重新等待；未知速度可将预计档位设为不限。')
                    self.reset_event(index)
                    continue
                if self.pulse_release_at is None:
                    self.release_count = self.release_count+1 if value*self.direction <= c.threshold*.45 else 0
                    if self.release_count >= c.confirm_samples:
                        self.pulse_release_at = index
                elif index-self.pulse_release_at >= max(c.confirm_samples, int(c.maximum_edge_ms*c.rate/1000)):
                    self.finish_pulse(index, results)
                continue
            edge = self.edge_candidate
            if edge is not None:
                self.pulse_trace.append(raw)
                if value*edge['direction'] < c.threshold:
                    self.edge_candidate = None
                    self.pulse_trace = None
                    self.rejected += 1
                    continue
                edge['count'] += 1
                edge['peak'] = max(edge['peak'],abs(raw))
                edge['clipped'] |= abs(raw) >= .999
                if edge['count'] >= c.confirm_samples:
                    self.activate(edge)
                continue
            if index < self.ready_at:
                continue
            self.quiet = self.quiet+1 if abs(value) < c.threshold*.45 else 0
            if self.quiet >= quiet_needed:
                self.is_ready = True
            if not self.is_ready:
                continue
            direction = 1 if value >= c.threshold else -1 if value <= -c.threshold else 0
            if not direction or (c.polarity and direction != c.polarity) or previous*direction >= c.threshold:
                continue
            self.pulse_offset = self.pulse_prefix[0][0]
            self.pulse_trace = array('f', (v for _,v in self.pulse_prefix))
            edge = dict(time=self.crossing(index,previous*direction,value*direction,c.threshold),
                        direction=direction,count=1,peak=abs(raw),clipped=abs(raw)>=.999,
                        strength=(value-previous)*direction)
            self.edge_candidate = edge
            if c.confirm_samples == 1:
                self.activate(edge)
        return results


class SampleBuffer:
    def __init__(self, capacity):
        self.capacity = int(capacity)
        self.parts = deque()
        self.end = 0
        self.size = 0

    def append(self, data):
        a = np.asarray(data, dtype=np.float32).copy()
        self.parts.append((self.end, a))
        self.end += len(a)
        self.size += len(a)
        while self.parts and self.size - len(self.parts[0][1]) >= self.capacity:
            self.size -= len(self.parts.popleft()[1])

    def get(self, start=None, end=None):
        if not self.parts:
            return 0, np.empty(0, np.float32)
        start = max(self.parts[0][0], self.end - self.capacity, int(start if start is not None else 0))
        end = min(self.end, int(end if end is not None else self.end))
        chunks = [a[max(0, start - i):min(len(a), end - i)]
                  for i, a in self.parts if i < end and i + len(a) > start]
        return start, np.concatenate(chunks) if chunks else np.empty(0, np.float32)


def read_wav(path, channel=0):
    if Path(path).stat().st_size > 128 * 1024 * 1024:
        raise ValueError('WAV 请小于 128 MB；建议先截取包含一次曝光的片段。')
    with wave.open(str(path), 'rb') as f:
        channels, width, rate, count = f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()
        if channel >= channels:
            raise ValueError(f'文件只有 {channels} 个声道，请选择声道 1。')
        raw = f.readframes(count)
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width in (2, 4):
        data = np.frombuffer(raw, '<i2' if width == 2 else '<i4').astype(np.float32) / 2 ** (width * 8 - 1)
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        x = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
        data = ((x ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    else:
        raise ValueError('仅支持 8/16/24/32 位整数 PCM WAV。')
    return int(rate), data.reshape(-1, channels)[:, channel].copy()


def write_wav(path, rate, data):
    pcm = (np.clip(data, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(int(rate))
        f.writeframes(pcm.tobytes())


def demo_signal(rate=48000, seconds=1/125, mode='edges', polarity=1):
    rng = np.random.default_rng(7)
    data = rng.normal(0, .0006, int((seconds + .45) * rate)).astype(np.float32)
    start = int(.15 * rate)
    stop = start + round(seconds * rate)
    if mode == 'edges':
        t = np.arange(int(.06 * rate)) / rate
        pulse = .45 * np.exp(-t / .002)
        data[start:start + len(pulse)] += polarity * pulse[:len(data[start:start + len(pulse)])]
        data[stop:stop + len(pulse)] -= polarity * pulse[:len(data[stop:stop + len(pulse)])]
    else:
        data[start:stop] += polarity * .45
    return data
