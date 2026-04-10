# SnapMac

Snap your fingers to trigger actions on your Mac — launch apps, run commands, toggle dark mode, and more. Lives quietly in your menu bar.

---

## Install

1. Go to the [Releases](../../releases) page
2. Download `SnapMac.zip`
3. Unzip it and drag **SnapMac.app** into your `/Applications` folder
4. Double-click to open

> **First launch blocked?** macOS may say the app can't be verified.
> Right-click **SnapMac.app** → **Open** → click **Open** again. You only need to do this once.

5. When prompted, allow **Microphone** access in System Settings → Privacy & Security → Microphone

---

## How to Use

Once running, a small icon appears in your **menu bar**. Click it to configure.

| What you do | What happens |
|---|---|
| Snap once | Triggers your **Single Snap** action |
| Snap twice quickly | Triggers your **Double Snap** action |

**Set your actions:**
- Click the menu bar icon
- Click **Set Action...** under Single Snap or Double Snap
- Choose from: App Launch, URL, Shell Command, Screenshot, Dark Mode toggle, Lock Screen, Mute, and more

---

## Calibration (optional)

If snaps aren't being detected reliably:

1. Click the menu bar icon → **Calibrate**
2. Snap your fingers 5 times at normal strength
3. Done — sensitivity is auto-adjusted for your environment

---

## Troubleshooting

**Nothing happens when I snap**
- System Settings → Privacy & Security → Microphone → enable SnapMac
- Try **Calibrate** from the menu
- Switch to a different microphone via the **Microphone** menu

**It triggers too easily / not enough**
- Use the **Sensitivity** menu to adjust (Very High → quieter rooms, Low → noisy environments)

---

## Launch at Login

Click the menu bar icon → enable **Launch at Login** to start SnapMac automatically when you log in.

## First Time Opening

macOS Gatekeeper may block the app:
```bash
xattr -cr /Applications/SnapMac.app
```

Or right-click -> Open -> Open Anyway.

## Tips

- **Calibrate first** - Run calibration for best accuracy
- **App names** - Must match exactly (e.g., "Spotify" not "spotify")
- **Double snaps** - Snap twice within 0.5 seconds
