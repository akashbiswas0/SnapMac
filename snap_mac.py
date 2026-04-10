import rumps
import sounddevice as sd
import numpy as np
import threading
import time
import os
import json
import subprocess
import sys
import ctypes
import ctypes.util
from AppKit import (
    NSWorkspace,
    NSApplicationActivateIgnoringOtherApps,
    NSApplication,
    NSImage,
    NSGraphicsContext,
    NSBezierPath,
    NSMakeRect,
    NSCompositingOperationSourceOver,
    NSColor,
)
from Foundation import NSBundle, NSProcessInfo, NSMakeSize

# Constants
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
HIGH_FREQ_LOW = 1500
HIGH_FREQ_HIGH = 9000
CONFIG_PATH = os.path.expanduser("~/.snapmac.json")
PID_PATH = "/tmp/snapmac.pid"

DEFAULT_CONFIG = {
    "snap1_action_type": "app_launch",
    "snap1_action_value": "Spotify",
    "snap2_action_type": "app_launch",
    "snap2_action_value": "Terminal",
    "sensitivity": 0.25,
    "cooldown": 0.6,
    "double_snap_window": 0.5,
    "noise_floor": 0.01,
    "selected_device": None,
    "launch_at_login": False,
}

ACTION_TYPES = [
    "app_launch",
    "shell_command",
    "url_open",
    "media_play_pause",
    "volume_mute",
    "screenshot",
    "lock_screen",
    "dark_mode_toggle",
]


def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception as e:
            log(f"Config load error: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def check_pid_lock():
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            log(f"SnapMac already running (PID {old_pid}). Exiting.")
            raise SystemExit(0)
        except (ProcessLookupError, ValueError):
            pass
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))


def remove_pid_lock():
    if os.path.exists(PID_PATH):
        os.remove(PID_PATH)


def get_installed_apps():
    apps = []
    try:
        for name in os.listdir("/Applications"):
            if name.endswith(".app"):
                apps.append(name[:-4])
    except Exception as e:
        log(f"Error listing apps: {e}")
    return sorted(apps, key=str.lower)


def launch_or_toggle(app_name):
    if not app_name:
        log("No app name provided")
        return False
    
    try:
        workspace = NSWorkspace.sharedWorkspace()
        
        for app in workspace.runningApplications():
            if app.localizedName() == app_name:
                if app.isActive():
                    app.hide()
                    log(f"Hid {app_name}")
                else:
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    log(f"Activated {app_name}")
                return True
        
        success = workspace.launchApplication_(app_name)
        log(f"Launched {app_name}: {success}")
        return success
    except Exception as e:
        log(f"Launch error: {e}")
        return False


def execute_action(action_type, action_value):
    log(f"Executing: {action_type} = {action_value}")
    try:
        if action_type == "app_launch":
            return launch_or_toggle(action_value)

        elif action_type == "shell_command":
            subprocess.Popen(
                action_value,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

        elif action_type == "url_open":
            subprocess.Popen(["open", action_value])
            return True

        elif action_type == "media_play_pause":
            script = '''
            tell application "Spotify"
                if player state is playing then pause else play
            end tell
            '''
            subprocess.Popen(["osascript", "-e", script],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

        elif action_type == "volume_mute":
            script = "set volume output muted not (output muted of (get volume settings))"
            subprocess.Popen(["osascript", "-e", script])
            return True

        elif action_type == "screenshot":
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            path = os.path.expanduser(f"~/Desktop/snap_{timestamp}.png")
            subprocess.Popen(["screencapture", "-i", path])
            return True

        elif action_type == "lock_screen":
            subprocess.Popen([
                "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession",
                "-suspend",
            ])
            return True

        elif action_type == "dark_mode_toggle":
            script = '''
            tell application "System Events"
                tell appearance preferences
                    set dark mode to not dark mode
                end tell
            end tell
            '''
            subprocess.Popen(["osascript", "-e", script])
            return True

    except Exception as e:
        log(f"Action error ({action_type}): {e}")
    return False


def add_login_item(app_path):
    script = f'''
    tell application "System Events"
        make login item at end with properties {{path:"{app_path}", hidden:false}}
    end tell
    '''
    subprocess.run(["osascript", "-e", script])


def remove_login_item():
    script = '''
    tell application "System Events"
        delete (every login item whose name is "SnapMac")
    end tell
    '''
    subprocess.run(["osascript", "-e", script])


def get_app_path():
    exe = os.path.abspath(__file__)
    if ".app/Contents" in exe:
        parts = exe.split(".app/Contents")
        return parts[0] + ".app"
    return None


class SnapDetector:
    def __init__(self, config, on_single, on_double):
        self.config = config
        self.on_single = on_single
        self.on_double = on_double

        self._lock = threading.Lock()
        self._last_snap_time = 0.0
        self._pending_single = False
        self._enabled = True
        self._stream = None
        
        self._recent_rms = []
        self._max_recent_rms = 0.001

    def start(self):
        device = self.config.get("selected_device")
        log(f"Starting audio stream on device: {device or 'default'}")
        
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                channels=1,
                dtype="float32",
                device=device,
                callback=self._audio_callback,
            )
            self._stream.start()
            log("Audio stream started successfully")
            
            self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
            self._watchdog_thread.start()
            
        except Exception as e:
            log(f"Failed to start audio stream: {e}")
            raise

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log(f"Error stopping stream: {e}")
            self._stream = None
            log("Audio stream stopped")

    def restart(self, new_device=None):
        self.stop()
        if new_device is not None:
            self.config["selected_device"] = new_device
        time.sleep(0.3)
        self.start()

    def set_enabled(self, val):
        self._enabled = val
        log(f"Detection {'enabled' if val else 'disabled'}")

    def _watchdog(self):
        while True:
            time.sleep(10)
            if self._stream and not self._stream.active:
                log("Stream died -- restarting...")
                try:
                    self.restart()
                except Exception as e:
                    log(f"Watchdog restart failed: {e}")

    def _is_snap(self, samples):
        rms = float(np.sqrt(np.mean(samples ** 2)))
        
        self._recent_rms.append(rms)
        if len(self._recent_rms) > 50:
            self._recent_rms.pop(0)
        
        if rms > self._max_recent_rms:
            self._max_recent_rms = rms * 0.5 + self._max_recent_rms * 0.5
        
        sensitivity = self.config.get("sensitivity", 0.25)
        noise_floor = self.config.get("noise_floor", 0.01)
        
        threshold = max(sensitivity * 0.1, noise_floor * 3)
        
        if rms < threshold:
            return False, rms
        
        fft_mag = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / SAMPLE_RATE)
        
        low_band = freqs < HIGH_FREQ_LOW
        snap_band = (freqs >= HIGH_FREQ_LOW) & (freqs <= HIGH_FREQ_HIGH)
        
        low_energy = float(np.sum(fft_mag[low_band]))
        snap_energy = float(np.sum(fft_mag[snap_band]))
        total_energy = float(np.sum(fft_mag)) + 1e-9
        
        snap_ratio = snap_energy / total_energy
        high_to_low_ratio = snap_energy / (low_energy + 1e-9)
        
        is_high_freq_dominant = snap_energy > low_energy * 0.5
        has_good_snap_ratio = snap_ratio > 0.15
        is_sharp = high_to_low_ratio > 0.8
        
        is_snap = is_high_freq_dominant and has_good_snap_ratio and is_sharp
        
        return is_snap, rms

    def _audio_callback(self, indata, frames, time_info, status):
        if not self._enabled:
            return
        
        if status:
            log(f"Audio status: {status}")
        
        samples = indata[:, 0]
        is_snap, rms = self._is_snap(samples)
        
        if not is_snap:
            return
        
        now = time.time()
        
        with self._lock:
            elapsed = now - self._last_snap_time
            cooldown = self.config.get("cooldown", 0.6)
            double_window = self.config.get("double_snap_window", 0.5)
            
            if elapsed < cooldown:
                return
            
            if elapsed < 0.15:
                return
            
            if self._pending_single and elapsed < double_window:
                self._pending_single = False
                self._last_snap_time = now
                log("DOUBLE SNAP detected!")
                threading.Thread(target=self.on_double, daemon=True).start()
                return
            
            self._pending_single = True
            self._last_snap_time = now
            captured_time = now
            log("Single snap detected, waiting for double...")
        
        def delayed_single():
            time.sleep(double_window + 0.05)
            with self._lock:
                if self._pending_single and self._last_snap_time == captured_time:
                    self._pending_single = False
                    log("Executing single snap action")
                    threading.Thread(target=self.on_single, daemon=True).start()
        
        threading.Thread(target=delayed_single, daemon=True).start()


class Calibrator:
    def __init__(self, config, on_complete, on_snap_detected=None):
        self.config = config
        self.on_complete = on_complete
        self.on_snap_detected = on_snap_detected
        self._snaps = []
        self._stream = None
        self._target = 5
        self._lock = threading.Lock()
        self._last_detection = 0

    def start(self):
        self._snaps = []
        log("Starting calibration...")
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, time_info, status):
        samples = indata[:, 0]
        rms = float(np.sqrt(np.mean(samples ** 2)))
        
        if rms < 0.03:
            return
        
        now = time.time()
        if now - self._last_detection < 0.3:
            return
        
        fft_mag = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / SAMPLE_RATE)
        
        low_e = float(np.sum(fft_mag[freqs < HIGH_FREQ_LOW]))
        high_e = float(np.sum(fft_mag[
            (freqs >= HIGH_FREQ_LOW) & (freqs <= HIGH_FREQ_HIGH)
        ]))
        
        if high_e <= low_e * 0.3:
            return
        
        with self._lock:
            self._snaps.append(rms)
            count = len(self._snaps)
            self._last_detection = now
        
        if self.on_snap_detected:
            self.on_snap_detected(count)
        
        log(f"Calibration snap {count}/{self._target}: RMS={rms:.4f}")
        
        if count >= self._target:
            self.stop()
            avg_rms = float(np.mean(self._snaps))
            new_sensitivity = max(0.08, round(avg_rms * 0.5, 4))
            self.config["sensitivity"] = new_sensitivity
            self.config["noise_floor"] = float(np.percentile(self._snaps, 25)) * 0.5
            save_config(self.config)
            log(f"Calibration complete. Sensitivity: {new_sensitivity}")
            self.on_complete(new_sensitivity, count)


def _set_process_name(name):
    """Set the OS-level process name so the Dock tooltip shows the correct app name."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library('c'))
        libc.setprogname.argtypes = [ctypes.c_char_p]
        libc.setprogname(name.encode())
    except Exception:
        pass


def _make_menubar_icon(image_path):
    """Return a copy of the icon clipped to a rounded rectangle for the menu bar."""
    src = NSImage.alloc().initWithContentsOfFile_(image_path)
    if src is None:
        return None
    w, h = src.size().width, src.size().height
    radius = min(w, h) * 0.22
    result = NSImage.alloc().initWithSize_(NSMakeSize(w, h))
    result.lockFocus()
    NSGraphicsContext.currentContext().setImageInterpolation_(2)
    NSColor.clearColor().set()
    NSBezierPath.fillRect_(NSMakeRect(0, 0, w, h))
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, w, h), radius, radius
    )
    path.addClip()
    src.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(0, 0, w, h), NSMakeRect(0, 0, w, h), NSCompositingOperationSourceOver, 1.0
    )
    result.unlockFocus()
    return result


def _make_dock_icon(image_path):
    """Return a copy of the image with macOS-style rounded corners and padding."""
    src = NSImage.alloc().initWithContentsOfFile_(image_path)
    orig = src.size()
    w, h = orig.width, orig.height
    pad = 0.12
    ix = w * pad
    iy = h * pad
    iw = w * (1 - 2 * pad)
    ih = h * (1 - 2 * pad)
    radius = min(iw, ih) * 0.225
    icon_rect = NSMakeRect(ix, iy, iw, ih)
    result = NSImage.alloc().initWithSize_(NSMakeSize(w, h))
    result.lockFocus()
    NSGraphicsContext.currentContext().setImageInterpolation_(2)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(icon_rect, radius, radius)
    path.addClip()
    src.drawInRect_fromRect_operation_fraction_(
        icon_rect, NSMakeRect(0, 0, w, h), NSCompositingOperationSourceOver, 1.0
    )
    result.unlockFocus()
    return result


class SnapMacApp(rumps.App):
    def __init__(self):
        self.config = load_config()
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapmac.png")

        # Fix app name shown in Dock — must be set BEFORE NSApplication is created
        _set_process_name("SnapMac")
        NSProcessInfo.processInfo().setProcessName_("SnapMac")
        _bundle_info = NSBundle.mainBundle().infoDictionary()
        if _bundle_info is not None:
            _bundle_info["CFBundleName"] = "SnapMac"
            _bundle_info["CFBundleDisplayName"] = "SnapMac"

        super().__init__("", icon=_icon_path, template=False, quit_button=None)

        # Set custom dock icon with macOS-style rounded corners
        if os.path.exists(_icon_path):
            _image = _make_dock_icon(_icon_path)
            NSApplication.sharedApplication().setApplicationIconImage_(_image)

        # Defer rounded menu bar icon application until run loop starts
        self._icon_path = _icon_path
        _timer = rumps.Timer(self._apply_menubar_icon, 0.05)
        _timer.start()

        self._calibrator = None
        
        self._toggle_item = rumps.MenuItem("Listening: On", callback=self._toggle_listening)
        self._toggle_item.state = True
        
        self._snap1_display = rumps.MenuItem(self._snap_label(1), callback=None)
        self._snap1_display.set_callback(None)
        
        self._snap2_display = rumps.MenuItem(self._snap_label(2), callback=None)
        self._snap2_display.set_callback(None)
        
        self._login_item = rumps.MenuItem("Launch at Login", callback=self._toggle_login)
        self._login_item.state = self.config.get("launch_at_login", False)
        
        self.menu = [
            self._toggle_item,
            None,
            rumps.MenuItem("--- Single Snap ---", callback=None),
            rumps.MenuItem("Set Action...", callback=self._set_snap1),
            self._snap1_display,
            None,
            rumps.MenuItem("--- Double Snap ---", callback=None),
            rumps.MenuItem("Set Action...", callback=self._set_snap2),
            self._snap2_display,
            None,
            rumps.MenuItem("Calibrate", callback=self._calibrate),
            self._build_sensitivity_menu(),
            self._build_mic_menu(),
            None,
            self._login_item,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        
        self.detector = SnapDetector(
            config=self.config,
            on_single=self._on_single,
            on_double=self._on_double,
        )
        
        try:
            self.detector.start()
        except Exception as e:
            rumps.alert("Error", f"Could not start audio: {e}\n\nCheck microphone permissions in System Settings.")
            raise

    def _apply_menubar_icon(self, timer):
        timer.stop()
        if os.path.exists(self._icon_path) and hasattr(self, '_status_item'):
            _img = _make_menubar_icon(self._icon_path)
            if _img:
                self._status_item.button().setImage_(_img)

    def _snap_label(self, slot):
        t = self.config[f"snap{slot}_action_type"]
        v = self.config[f"snap{slot}_action_value"]
        labels = {
            "app_launch": "App",
            "shell_command": "Command",
            "url_open": "URL",
            "media_play_pause": "Play/Pause",
            "volume_mute": "Mute",
            "screenshot": "Screenshot",
            "lock_screen": "Lock",
            "dark_mode_toggle": "Dark Mode",
        }
        label = labels.get(t, t)
        if v and t not in ("media_play_pause", "volume_mute", "screenshot", "lock_screen", "dark_mode_toggle"):
            return f"   {label}: {v[:30]}{'...' if len(v) > 30 else ''}"
        return f"   {label}"

    def _build_sensitivity_menu(self):
        menu = rumps.MenuItem("Sensitivity")
        levels = [
            ("Very High", 0.12),
            ("High", 0.20),
            ("Medium", 0.30),
            ("Low", 0.45),
            ("Very Low", 0.60),
        ]
        for label, value in levels:
            menu[label] = rumps.MenuItem(label,
                callback=lambda _, v=value: self._set_sensitivity(v))
        return menu

    def _build_mic_menu(self):
        menu = rumps.MenuItem("Microphone")
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    name = dev["name"][:40]
                    item = rumps.MenuItem(name,
                        callback=lambda _, idx=i, n=name: self._set_mic(idx, n))
                    menu[name] = item
        except Exception as e:
            log(f"Error listing mics: {e}")
            menu["Error listing devices"] = rumps.MenuItem("Error listing devices")
        return menu

    def _on_single(self):
        self._flash_icon("1")
        success = execute_action(
            self.config["snap1_action_type"],
            self.config["snap1_action_value"],
        )
        if not success:
            self._flash_icon("X")

    def _on_double(self):
        self._flash_icon("2")
        success = execute_action(
            self.config["snap2_action_type"],
            self.config["snap2_action_value"],
        )
        if not success:
            self._flash_icon("X")

    def _flash_icon(self, icon="OK"):
        def flash():
            old_title = self.title
            self.title = icon
            time.sleep(0.4)
            self.title = "Snap" if self._toggle_item.state else "Off"
        threading.Thread(target=flash, daemon=True).start()

    def _toggle_listening(self, sender):
        sender.state = not sender.state
        self.detector.set_enabled(sender.state)
        sender.title = "Listening: On" if sender.state else "Listening: Off"
        self.title = "Snap" if sender.state else "Off"

    def _set_snap(self, slot):
        type_options = "\n".join([f"{i+1}. {t}" for i, t in enumerate(ACTION_TYPES)])
        w1 = rumps.Window(
            title=f"Set Snap {slot} Action",
            message=f"Choose action type:\n\n{type_options}",
            default_text="1",
            ok="Next",
            cancel="Cancel",
        )
        r1 = w1.run()
        if not r1.clicked:
            return
        
        try:
            idx = int(r1.text.strip()) - 1
            action_type = ACTION_TYPES[idx]
        except (ValueError, IndexError):
            rumps.alert("Invalid choice")
            return
        
        no_value = {"media_play_pause", "volume_mute", "screenshot", "lock_screen", "dark_mode_toggle"}
        action_value = ""
        
        if action_type not in no_value:
            if action_type == "app_launch":
                apps = get_installed_apps()
                hint = f"Installed apps ({min(30, len(apps))} shown):\n" + ", ".join(apps[:30])
                msg = f"Enter exact app name:\n\n{hint}"
                default = "Spotify"
            elif action_type == "shell_command":
                msg = "Enter shell command:"
                default = "open -a Calculator"
            elif action_type == "url_open":
                msg = "Enter URL:"
                default = "https://google.com"
            else:
                msg = "Enter value:"
                default = ""
            
            w2 = rumps.Window(
                title="Action Value",
                message=msg,
                default_text=default,
                ok="Save",
                cancel="Cancel",
                dimensions=(320, 24),
            )
            r2 = w2.run()
            if not r2.clicked:
                return
            action_value = r2.text.strip()
        
        self.config[f"snap{slot}_action_type"] = action_type
        self.config[f"snap{slot}_action_value"] = action_value
        save_config(self.config)
        
        if slot == 1:
            self._snap1_display.title = self._snap_label(1)
        else:
            self._snap2_display.title = self._snap_label(2)
        
        rumps.notification("SnapMac", f"Snap {slot} Saved", f"{action_type}: {action_value[:30]}")

    def _set_snap1(self, _):
        self._set_snap(1)

    def _set_snap2(self, _):
        self._set_snap(2)

    def _set_sensitivity(self, value):
        self.config["sensitivity"] = value
        save_config(self.config)
        labels = {0.12: "Very High", 0.20: "High", 0.30: "Medium", 0.45: "Low", 0.60: "Very Low"}
        label = labels.get(value, str(value))
        rumps.notification("SnapMac", "Sensitivity", f"Set to {label} ({value})")

    def _set_mic(self, device_idx, device_name):
        self.config["selected_device"] = device_idx
        save_config(self.config)
        try:
            self.detector.restart(new_device=device_idx)
            rumps.notification("SnapMac", "Microphone", f"Switched to: {device_name[:30]}")
        except Exception as e:
            rumps.alert("Error", f"Could not switch microphone: {e}")

    def _calibrate(self, _):
        if self._calibrator:
            return
        
        self.detector.set_enabled(False)
        
        rumps.alert(
            title="Calibration",
            message="Snap your fingers 5 times at normal strength.\n\nClick OK to start.",
        )
        
        self.title = "CAL"
        count = [0]
        
        def on_snap_detected(c):
            count[0] = c
            self.title = f"CAL {c}/5"
        
        def on_complete(sensitivity, total):
            self._calibrator = None
            self.detector.set_enabled(True)
            self.title = "Snap"
            rumps.notification(
                "SnapMac",
                "Calibration Complete",
                f"Detected {total} snaps. Sensitivity: {sensitivity:.3f}",
            )
        
        self._calibrator = Calibrator(
            config=self.config,
            on_complete=on_complete,
            on_snap_detected=on_snap_detected,
        )
        self._calibrator.start()

    def _toggle_login(self, sender):
        sender.state = not sender.state
        self.config["launch_at_login"] = bool(sender.state)
        save_config(self.config)
        
        if sender.state:
            app_path = get_app_path()
            if app_path:
                add_login_item(app_path)
                rumps.notification("SnapMac", "", "Added to login items")
            else:
                rumps.alert("Not a .app bundle", "Launch at login only works when running as an .app")
                sender.state = False
                self.config["launch_at_login"] = False
                save_config(self.config)
        else:
            remove_login_item()
            rumps.notification("SnapMac", "", "Removed from login items")

    def _quit(self, _):
        self.detector.stop()
        remove_pid_lock()
        rumps.quit_application()


if __name__ == "__main__":
    check_pid_lock()
    try:
        SnapMacApp().run()
    except Exception as e:
        log(f"Fatal error: {e}")
        remove_pid_lock()
        raise
    finally:
        remove_pid_lock()
