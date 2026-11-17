# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572

import tempfile
import unittest
from pathlib import Path
import wave
import numpy as np
from core import Config, Detector, SampleBuffer, demo_signal, read_wav, write_wav, nominal

FIXTURES = Path(__file__).resolve().parent / "fixtures"

class DetectionTests(unittest.TestCase):
    def test_block_boundaries_and_polarity(self):
        for mode in ('edges', 'level'):
            for polarity in (-1, 1):
                data = demo_signal(mode=mode, polarity=polarity)
                expected = Detector(Config(mode=mode)).feed(data)
                for size in (1, 127, 383, 1024):
                    d = Detector(Config(mode=mode))
                    result = []
                    for i in range(0, len(data), size):
                        result.extend(d.feed(data[i:i + size]))
                    self.assertEqual(result, expected)
                    self.assertEqual(len(result), 1)
                    self.assertAlmostEqual(result[0].seconds, .008, delta=2 / 48000)
                    self.assertEqual(result[0].polarity, polarity)

    def test_range_and_sampling_rates(self):
        for rate in (44100, 48000, 96000):
            for exposure in (1/8000, 1/1000, 1/125, 1/30, .5, 2.):
                for mode in ('edges', 'level'):
                    r = Detector(Config(rate=rate, mode=mode)).feed(demo_signal(rate, exposure, mode))
                    self.assertEqual(len(r), 1, (rate, exposure, mode))
                    self.assertAlmostEqual(r[0].seconds, exposure, delta=2 / rate)

    def test_noise_and_slow_ac_tail_not_exposure(self):
        rate = 48000
        t = np.arange(2 * rate) / rate
        x = .002 * np.sin(2 * np.pi * 19000 * t) + .08 * np.sin(2 * np.pi * 2 * t)
        self.assertFalse(Detector(Config()).feed(x))

    def test_clipped_pulse_is_rejected(self):
        x = demo_signal(mode='level')
        x[7200:7584] = 1.
        d = Detector(Config(mode='level'))
        self.assertFalse(d.feed(x))
        self.assertTrue(any('削顶' in m for m in d.messages))

    def test_incomplete_exposure_and_timeout(self):
        x = np.zeros(48000, np.float32)
        x[4800:4900] = .4
        d = Detector(Config(maximum_s=.2))
        self.assertFalse(d.feed(x))
        self.assertTrue(any('超时' in m for m in d.messages))
        d = Detector(Config())
        self.assertFalse(d.feed(x[:5000]))
        self.assertIsNotNone(d.start)

    def test_minimum_duration_and_wrong_polarity(self):
        self.assertFalse(Detector(Config(minimum_ms=10)).feed(demo_signal()))
        self.assertFalse(Detector(Config(polarity=-1)).feed(demo_signal()))

    def test_sub_sample_interpolation(self):
        x = np.zeros(6000, np.float32)
        x[1000:1100] = .2
        x[1100] = .1
        d = Detector(Config(mode='level', threshold=.1))
        result = d.feed(x)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].start, 999.5)
        self.assertAlmostEqual(result[0].end, 1100.)

    def test_level_mode_slow_rise(self):
        x = np.zeros(6000, np.float32)
        x[1000:1200] = np.linspace(0, .4, 200)
        x[1200:1400] = .4
        x[1400:1600] = np.linspace(.4, 0, 200)
        self.assertEqual(len(Detector(Config(mode='level')).feed(x)), 1)

    def test_ac_continuous_signal_without_silent_preamble(self):
        rate = 48000
        t = np.arange(rate) / rate
        x = np.where((t * 13) % 1 < .45, .4, -.4).astype(np.float32)
        d = Detector(Config(polarity=-1))
        r = d.feed(x)
        self.assertGreaterEqual(len(r), 12)
        self.assertAlmostEqual(float(np.median(np.diff([m.start for m in r]))) / rate, 1/13, delta=2/rate)

    def test_startup_warmup(self):
        x = demo_signal()
        d = Detector(Config());d.ready_at = 48000
        self.assertFalse(d.feed(x))

    def test_invalid_configuration(self):
        for values in ({'threshold':0}, {'maximum_s':0}, {'minimum_ms':10001}, {'rate':0}, {'edge_slope':-1}, {'threshold':float('nan')}, {'cooldown_s':-1}):
            with self.assertRaises(ValueError):Config(**values)

    def test_nominal_error_sign(self):
        name, percent, ev = nominal(.009)
        self.assertEqual(name, '1/125 s')
        self.assertAlmostEqual(percent, 12.5)
        self.assertGreater(ev, 0)

class NoiseRecoveryTests(unittest.TestCase):
    def test_two_single_sample_spikes_do_not_mask_real_shutter(self):
        x=np.zeros(5000,np.float32)
        x[1000]=-.08;x[1010]=.08
        x[1050:1070]=-.4;x[1530:1550]=.4
        d=Detector(Config(polarity=-1));r=d.feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/48000)
        self.assertAlmostEqual(r[0].start,1049.0625)

    def test_single_sample_false_close_does_not_shorten_exposure(self):
        x=np.zeros(5000,np.float32)
        x[1000:1020]=-.4;x[1100]=.08;x[1480:1500]=.4
        r=Detector(Config(polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/48000)

    def test_stronger_real_opening_replaces_weak_false_start(self):
        x=np.zeros(5000,np.float32)
        x[1000:1005]=-.04;x[1200:1220]=-.4;x[1680:1700]=.4
        d=Detector(Config(polarity=-1));r=d.feed(x)
        self.assertEqual(len(r),1)
        self.assertEqual(d.reanchored,1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/48000)

    def test_rejected_short_pulse_has_no_cooldown(self):
        x=np.zeros(5000,np.float32)
        x[1000:1005]=-.4;x[1010:1015]=.4
        x[1050:1070]=-.4;x[1530:1550]=.4
        d=Detector(Config(polarity=-1,expected_s=.01));r=d.feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/48000)
        self.assertGreater(d.rejected,0)

    def test_target_only_filters_does_not_snap_measured_time(self):
        r=Detector(Config(expected_s=.01)).feed(demo_signal(seconds=.012))
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.012,delta=2/48000)
        self.assertEqual(r[0].expected_s,.01)

    def test_bad_start_times_out_soon_with_target(self):
        x=np.zeros(10000,np.float32)
        x[1000:1005]=-.04;x[3500:3520]=-.4;x[3980:4000]=.4
        d=Detector(Config(polarity=-1,expected_s=.01));r=d.feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/48000)
        self.assertTrue(any('超时' in m for m in d.messages))

    def test_confirmation_crosses_audio_blocks(self):
        x=demo_signal(seconds=.01,polarity=-1)
        d=Detector(Config(polarity=-1,expected_s=.01));r=[]
        for a,b in [(0,7201),(7201,7202),(7202,7681),(7681,7682),(7682,len(x))]:
            r.extend(d.feed(x[a:b]))
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=2/48000)

    def test_invalid_confirmation_and_target(self):
        for kw in ({'confirm_samples':0},{'confirm_samples':2.5},{'confirm_samples':33},{'expected_s':-1},{'expected_s':float('nan')},{'expected_s':.01,'minimum_ms':50}):
            with self.assertRaises(ValueError):Config(**kw)

class PhotopulseTests(unittest.TestCase):
    def test_asymmetric_close_below_positive_trigger_still_measured(self):
        rate=48000;x=np.zeros(6000,np.float32)
        x[1000:1480]=-.2;x[1480:1900]=.02
        # Old AC requires a +.05 excursion and its single-sample slope gate.
        self.assertFalse(Detector(Config(threshold=.05,polarity=-1)).feed(x))
        d=Detector(Config(mode='pulse',threshold=.05,polarity=-1));r=d.feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.01,delta=1/rate)

    def test_slow_lighting_change_is_rejected(self):
        rate=48000;t=np.arange(rate)/rate
        x=(-.2*np.exp(-((t-.5)/.05)**2)).astype(np.float32)
        d=Detector(Config(mode='pulse',threshold=.05,polarity=-1))
        self.assertFalse(d.feed(x));self.assertGreater(d.rejected,0)

    def test_weak_peak_with_trigger_above_half_height(self):
        x=np.zeros(6000,np.float32)
        x[1000:1020]=np.linspace(0,-.06,20)
        x[1020:1480]=-.06;x[1480:1500]=np.linspace(-.06,0,20)
        r=Detector(Config(mode='pulse',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].samples,480,delta=1)

    def test_single_sample_noise_does_not_move_half_width_markers(self):
        x=np.zeros(6000,np.float32)
        x[950]=-.8;x[1000:1480]=-.2;x[1200]=.1
        r=Detector(Config(mode='pulse',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].samples,480,delta=.01)

    def test_pulse_streaming_block_invariance_and_rates(self):
        for rate in (44100,48000,96000):
            for pol in (-1,1):
                data=demo_signal(rate=rate,mode='pulse',polarity=pol)
                c=Config(rate=rate,mode='pulse',polarity=pol)
                expected=Detector(c).feed(data)
                self.assertEqual(len(expected),1)
                self.assertAlmostEqual(expected[0].seconds,.008,delta=2/rate)
                for block in (1,127,512):
                    d=Detector(c);actual=[]
                    for i in range(0,len(data),block):actual.extend(d.feed(data[i:i+block]))
                    self.assertEqual(actual,expected)

    def test_camera_file_contains_five_independent_pulses(self):
        path=FIXTURES/'camera_fast_44k.wav'
        if not path.exists():self.skipTest('User camera WAV not present')
        rate,data=read_wav(path)
        d=Detector(Config(rate=rate,mode='pulse',threshold=.05,polarity=-1))
        results=[]
        for i in range(0,len(data),1024):results.extend(d.feed(data[i:i+1024]))
        self.assertEqual(len(results),5)
        for m,t,duration in zip(results,[8.2582,13.7846,18.0906,29.8855,34.4585],[.012973,.012954,.012891,.006232,.004527]):
            self.assertAlmostEqual(m.start/rate,t,delta=.0001)
            self.assertAlmostEqual(m.seconds,duration,delta=.00003)
        self.assertTrue(any('缓慢' in message for message in d.messages))

class FastSlowShutterTests(unittest.TestCase):
    @staticmethod
    def ac_signal(rate, duration, tau=.08):
        t=np.arange(round((duration+.7)*rate))/rate
        start=.15;end=start+duration
        a=np.maximum(t-start,0);b=np.maximum(t-end,0)
        x=np.where(t>=start,-.3*np.exp(-a/tau),0)+np.where(t>=end,.3*np.exp(-b/tau),0)
        return x.astype(np.float32)

    def test_short_and_long_ac_exposures(self):
        for rate in (44100,48000,96000):
            for duration in (.008,.2,.5,1.7):
                d=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1))
                r=d.feed(self.ac_signal(rate,duration))
                self.assertEqual(len(r),1,(rate,duration))
                self.assertAlmostEqual(r[0].seconds,duration,delta=2/rate)

    def test_waits_through_return_to_zero(self):
        rate=48000;x=self.ac_signal(rate,2.)
        d=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1))
        self.assertFalse(d.feed(x[:round(1.8*rate)]))
        self.assertIsNotNone(d.start)
        r=d.feed(x[round(1.8*rate):])
        self.assertEqual(len(r),1);self.assertAlmostEqual(r[0].seconds,2.,delta=2/rate)

    def test_fast_ac_recovery_is_not_a_closing_edge(self):
        rate=48000;x=self.ac_signal(rate,.5,tau=.002)
        r=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.5,delta=2/rate)

    def test_overshoot_is_not_closure(self):
        x=np.zeros(20000,np.float32)
        x[4800:4810]=-.4;x[4810:9600]=-.3
        r=Detector(Config(mode='transition',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.1,delta=2/48000)

    def test_closing_need_not_cross_zero(self):
        x=np.zeros(20000,np.float32);x[4800:9600]=-.3;x[9600:]=-.1
        r=Detector(Config(mode='transition',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,.1,delta=2/48000)

    def test_sub_millisecond_and_block_invariance(self):
        for duration in (1/8000,1/1000,.2):
            data=demo_signal(seconds=duration,mode='transition',polarity=-1)
            c=Config(mode='transition',polarity=-1)
            expected=Detector(c).feed(data)
            self.assertEqual(len(expected),1)
            self.assertAlmostEqual(expected[0].seconds,duration,delta=2/48000)
            for block in (1,127,512):
                d=Detector(c);actual=[]
                for i in range(0,len(data),block):actual.extend(d.feed(data[i:i+block]))
                self.assertEqual(actual,expected)

    def test_spikes_during_bulb_exposure_do_not_close_it(self):
        x=self.ac_signal(48000,1.)
        x[20000]=.8;x[25000:25002]=.7
        r=Detector(Config(mode='transition',threshold=.05,polarity=-1)).feed(x)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[0].seconds,1.,delta=2/48000)

    def test_twelve_second_bulb(self):
        x=self.ac_signal(48000,12.)
        r=Detector(Config(mode='transition',threshold=.05,polarity=-1,maximum_s=30)).feed(x)
        self.assertEqual(len(r),1);self.assertAlmostEqual(r[0].seconds,12.,delta=2/48000)

    def test_new_bulb_recording_has_six_pairs(self):
        path=FIXTURES/'bulb_44k.wav'
        if not path.exists():self.skipTest('Archived B-mode recording not present')
        rate,data=read_wav(path)
        d=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1,maximum_s=30))
        r=[]
        for i in range(0,len(data),1024):r.extend(d.feed(data[i:i+1024]))
        self.assertEqual(len(r),6)
        for m,start,end in zip(r,[1.1433,5.7328,9.8699,13.8262,18.4157,20.6742],[1.6432,6.4042,10.0550,15.5250,18.5182,20.7507]):
            self.assertAlmostEqual(m.start/rate,start,delta=.0002)
            self.assertAlmostEqual(m.end/rate,end,delta=.0002)

    def test_fast_recording_still_has_five_pairs(self):
        path=FIXTURES/'camera_fast_44k.wav'
        if not path.exists():self.skipTest('Archived camera recording not present')
        rate,data=read_wav(path)
        r=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1)).feed(data)
        self.assertEqual(len(r),5)
        for m,duration in zip(r,[.013086,.013063,.012984,.006273,.004558]):
            self.assertAlmostEqual(m.seconds,duration,delta=.00003)

    def test_strobe_ringing_does_not_produce_tiny_exposures(self):
        path=FIXTURES/'strobe_realtek_48k_retry.wav'
        if not path.exists():self.skipTest('Archived strobe not present')
        rate,data=read_wav(path)
        d=Detector(Config(rate=rate,mode='transition',threshold=.05,polarity=-1));d.ready_at=int(.3*rate)
        r=d.feed(data)
        self.assertEqual(len(r),79)
        for m in r:self.assertAlmostEqual(m.seconds,.03514,delta=.00012)

    def test_invalid_edge_ratios(self):
        for kw in ({'minimum_edge_ratio':-1},{'minimum_edge_ratio':1.1},{'minimum_step_ratio':-1},{'minimum_step_ratio':float('nan')}):
            with self.assertRaises(ValueError):Config(**kw)

class StorageTests(unittest.TestCase):
    def test_ring_limits_and_slicing(self):
        b = SampleBuffer(10)
        for i in range(0, 24, 3):b.append(np.arange(i, i+3))
        start, x = b.get()
        self.assertEqual(start, 14)
        np.testing.assert_array_equal(x, np.arange(14,24))
        start, x = b.get(16,20)
        self.assertEqual(start,16)
        np.testing.assert_array_equal(x,np.arange(16,20))

    def test_wav_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'测试.wav'
            x=demo_signal();write_wav(p,48000,x)
            rate,y=read_wav(p)
            self.assertEqual(rate,48000)
            np.testing.assert_allclose(x,y,atol=2/32768)
            with self.assertRaises(ValueError):read_wav(p,1)

    def test_24bit_stereo_and_8bit(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'24.wav'
            vals=[-8388608, 8388607, -1, 0, 0, -8388608]
            raw=b''.join((v & 0xffffff).to_bytes(3,'little') for v in vals)
            with wave.open(str(p),'wb') as f:
                f.setnchannels(2);f.setsampwidth(3);f.setframerate(96000);f.writeframes(raw)
            rate,y=read_wav(p,1)
            np.testing.assert_allclose(y,[8388607/8388608,0,-1])
            with wave.open(str(p),'wb') as f:
                f.setnchannels(1);f.setsampwidth(1);f.setframerate(44100);f.writeframes(bytes([0,128,255]))
            _,y=read_wav(p)
            np.testing.assert_allclose(y,[-1,0,127/128])

class HardwareReplayTests(unittest.TestCase):
    def test_saved_beacon(self):
        p=FIXTURES/'beacon_realtek_48k.wav'
        if not p.exists():self.skipTest('Local hardware sample not included')
        rate,x=read_wav(p);d=Detector(Config(rate=rate));d.ready_at=int(.3*rate);r=d.feed(x)
        self.assertEqual(len(r),2)
        for m in r:self.assertAlmostEqual(m.seconds,.05073,delta=.0001)
        self.assertAlmostEqual((r[1].start-r[0].start)/rate,3.0919,delta=.001)

    def test_noise_calibration_still_detects_both_real_samples(self):
        p=FIXTURES/'beacon_realtek_48k.wav'
        if not p.exists():self.skipTest('Local hardware sample not included')
        rate,x=read_wav(p);quiet=x[-rate//2:];base=float(np.median(quiet))
        sigma=float(np.median(abs(quiet-base)))*1.4826
        threshold=max(.002,sigma*8,float(np.quantile(abs(quiet-base),.995))*1.8)
        slope=max(10.,float(np.quantile(abs(np.diff(quiet)),.995))*2*rate)
        for name,count in [('beacon_realtek_48k.wav',2),('strobe_realtek_48k_retry.wav',79)]:
            _,data=read_wav(FIXTURES/name)
            d=Detector(Config(rate=rate,baseline=base,threshold=threshold,edge_slope=slope));d.ready_at=int(.3*rate)
            self.assertEqual(len(d.feed(data)),count)

    def test_saved_strobe_no_missed_cycles(self):
        p=FIXTURES/'strobe_realtek_48k_retry.wav'
        if not p.exists():self.skipTest('Local hardware sample not included')
        rate,x=read_wav(p);d=Detector(Config(rate=rate));d.ready_at=int(.3*rate);r=d.feed(x)
        self.assertEqual(len(r),79)
        for m in r:self.assertAlmostEqual(m.seconds,.03514,delta=.0001)
        for a,b in zip(r,r[1:]):self.assertAlmostEqual((b.start-a.start)/rate,.07209,delta=.0002)
        self.assertFalse(d.messages)

if __name__=='__main__':unittest.main()
