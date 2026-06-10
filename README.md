# GUI Action Recorder

A lightweight, premium, and clean Python desktop application to record, manage, and play back mouse and keyboard macros. Built with standard Tkinter using modern layout design systems, Segoe UI typography, and smart thread handling.

This project also includes a transpiler to compile recorded macro paths to relative binary `.hid` format for bare-metal hardware execution on an Orange Pi single-board computer, enabling OTG hardware mouse and keyboard simulation.

---

## Key Features

- **Modern Segmented Card UI**: Styled using custom ice blue, mint green, and light slate card layouts.
- **Asynchronous Execution & Hotkey**: Integrated global keyboard listener using `[F8]` to asynchronously **Start Recording**, **Stop Recording**, or **Abort Playback** at any time.
- **Shorthand List JSON Format**: Optimizes file size by ~90% by serializing raw event tracking into a compact array list structure.
- **Dynamic File Explorer**: A two-column folder and file browser (Left: Folders, Right: Macros) displaying details at a glance. Supports `exportselection=False` to retain double selection highlights.
- **File Metadata Details**: Displays live estimated file size in KB, actions count, and local modification timestamps (e.g. `2026/6/10 PM 04:24`) for saved or recorded events.
- **Intelligent Drag-to-Move**: Drag macro files directly from the right-hand listbox and drop them onto target directories in the left listbox to organize files.
- **Unified Deletion**: One combined delete button (`🗑`) dynamically deletes files or folders depending on active selections.
- **Self-Contained Icon Generator**: Automatically generates and loads a retro camera pixel-art window icon (`app_icon.ppm`) on launch, requiring no external assets or packages.
- **Orange Pi Hardware Emulation Integration**:
  - `translator.py`: Compiles recorded JSON actions into relative coordinates and USB HID reports.
  - `orangepi_client.py`: Bare-metal executor client for the `/dev/hidg0` (keyboard) and `/dev/hidg1` (mouse) Linux nodes.

---

## Directory Structure

```text
├── action_recorder.py    # Main GUI Window & event bindings
├── macro_runner.py       # Asynchronous playback controller
├── utils.py              # Serialization formats & time helpers
├── translator.py         # JSON macro to binary .hid compiler
├── orangepi_client.py    # Linux hardware emulator client
├── .gitignore            # Version control exclusions
└── recorded/             # User macro directories
    └── main/             # Sample macro folders
```

---

## Installation & Setup

1. Clone the repository to your local workspace:
   ```bash
   git clone https://github.com/[your-username]/gui_action_recorder.git
   cd gui_action_recorder
   ```

2. Make sure Python 3.x is installed. Install package dependencies:
   ```bash
   pip install pynput
   ```

---

## Usage

### 1. Launching the GUI
Run the main script from your terminal:
```bash
python action_recorder.py
```

- **Record Actions**: Click `⏺ Record` or press `[F8]`. The window will automatically go semi-transparent. Press `[F8]` or click `⏹ Stop` to finish.
- **Save Macro**: Enter a name in the `Save Name` field and select a folder on the left, then click the `💾` save icon.
- **Replay Macro**: Select a folder and click a macro file, then click `▶ Play` or press `[F8]`. Press `[F8]` to abort playback instantly.
- **Drag-to-Move**: Hold left-click on a file in the right column, drag it over to any folder in the left column, and release.
- **Delete**: Select a file or folder and click the `🗑` button.

### 2. Orange Pi OTG Translation
To transpile a recorded JSON macro to the binary USB HID format:
```bash
python translator.py recorded/main/macro_name.json
```
This will compile and generate `recorded/main/macro_name.hid`. Copy this file alongside `orangepi_client.py` to your Orange Pi board, and execute:
```bash
sudo python orangepi_client.py recorded/main/macro_name.hid
```

---

## License

Distributed under the MIT License. See `LICENSE` for more information.
