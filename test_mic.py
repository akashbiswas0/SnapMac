#!/usr/bin/env python3
"""
Microphone test and diagnostic tool for SnapMac
"""

import sounddevice as sd
import numpy as np
import time
import sys

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
HIGH_FREQ_LOW = 1500
HIGH_FREQ_HIGH = 9000

print("=" * 60)
print("SnapMac Microphone Test")
print("=" * 60)

print("\nAvailable input devices:")
print("-" * 40)
try:
    devices = sd.query_devices()
    default_input = sd.query_devices(kind='input')
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            marker = " <- DEFAULT" if dev == default_input else ""
            print(f"  [{i}] {dev['name']}{marker}")
except Exception as e:
    print(f"Error listing devices: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("Starting audio test...")
print("Make some noise or snap your fingers!")
print("Press Ctrl+C to stop")
print("=" * 60)

detection_count = 0
last_detection = 0
rms_history = []


def audio_callback(indata, frames, time_info, status):
    global detection_count, last_detection
    
    if status:
        print(f"Status: {status}")
    
    samples = indata[:, 0]
    rms = float(np.sqrt(np.mean(samples ** 2)))
    rms_history.append(rms)
    if len(rms_history) > 100:
        rms_history.pop(0)
    
    fft_mag = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / SAMPLE_RATE)
    
    low_band = freqs < HIGH_FREQ_LOW
    snap_band = (freqs >= HIGH_FREQ_LOW) & (freqs <= HIGH_FREQ_HIGH)
    
    low_energy = float(np.sum(fft_mag[low_band]))
    snap_energy = float(np.sum(fft_mag[snap_band]))
    total_energy = float(np.sum(fft_mag)) + 1e-9
    
    snap_ratio = snap_energy / total_energy
    high_to_low = snap_energy / (low_energy + 1e-9)
    
    is_loud = rms > 0.05
    is_high_freq = snap_energy > low_energy * 0.5
    has_good_ratio = snap_ratio > 0.15
    
    is_snap = is_loud and is_high_freq and has_good_ratio
    
    bar_len = min(50, int(rms * 200))
    bar = "=" * bar_len + "-" * (50 - bar_len)
    
    now = time.time()
    snap_marker = ""
    if is_snap and now - last_detection > 0.3:
        detection_count += 1
        last_detection = now
        snap_marker = " <<< SNAP DETECTED!"
    
    sys.stdout.write(f"\r{bar} RMS:{rms:.4f} S:{snap_ratio:.2f} Detected:{detection_count}{snap_marker}      ")
    sys.stdout.flush()


try:
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    )
    stream.start()
    
    while True:
        time.sleep(0.1)
        
except KeyboardInterrupt:
    print("\n\n" + "=" * 60)
    print("Test stopped")
    if rms_history:
        print(f"Average RMS: {np.mean(rms_history):.4f}")
        print(f"Max RMS: {max(rms_history):.4f}")
    print(f"Total snaps detected: {detection_count}")
    print("=" * 60)
    
    if detection_count == 0:
        print("\nWARNING: No snaps detected!")
        print("\nTroubleshooting:")
        print("1. Check microphone permissions in System Settings")
        print("   Privacy & Security -> Microphone")
        print("2. Make sure your microphone is not muted")
        print("3. Try snapping louder or closer to the mic")
        print("4. Try a different sensitivity level")
    else:
        print(f"\nOK: Detected {detection_count} snaps!")
        print("If SnapMac isn't working, run the calibration.")
        
except Exception as e:
    print(f"\nError: {e}")
    print("\nMake sure you have microphone permissions enabled.")
    sys.exit(1)
finally:
    try:
        stream.stop()
        stream.close()
    except:
        pass
