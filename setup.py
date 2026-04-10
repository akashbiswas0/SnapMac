from setuptools import setup

APP = ["snap_mac.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "snapmac.png",
    "plist": {
        "CFBundleName": "SnapMac",
        "CFBundleDisplayName": "SnapMac",
        "CFBundleIdentifier": "com.snapmac.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "SnapMac listens for finger snaps to trigger actions.",
    },
    "packages": ["rumps", "sounddevice", "numpy"],
}

setup(
    app=APP,
    name="SnapMac",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
