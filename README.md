# GUI Action Recorder

<img width="1347" height="594" alt="image" src="https://github.com/user-attachments/assets/9f7e566f-749b-4ec1-9dfd-3260c46b90e4" />


A lightweight desktop macro automation suite. It allows you to record and execute mouse and keyboard actions, locally or by an Orange Pi One.

This project supports two main execution modes:
1. **Local Playback**: Record keyboard and mouse actions and replay it.
2. **Hardware Emulation (Anti-Cheat Bypass)**: Transpile recorded actions into raw USB HID binary packets and execute them on Orange Pi One (or other SBC), used to bypasses software-level anti-cheat and macro detection mechanisms.

---

## Use it

### Clone the repository:
```bash
git clone https://github.com/ElenBOT/gui_action_recorder.git
cd gui_action_recorder
```

### Create venv and install the required dependencies:

Windows
>```powershell
>python -m venv pimouse
>pimouse\Scripts\activate
>pip install pynput paramiko
># rmdir /s /q pimouse # to remove venv
>```

Linux
>```bash
>python3 -m venv pimouse
>source pimouse/bin/activate
>pip install pynput paramiko
># rm -rf pimouse # to remove venv
>```

### Launch the Application:
```bash
python action_recorder.py
```
then others are easy to see on the GUI panels.

## How
This project leverages USB OTG (On-The-Go) and the Linux USB Gadget (`libcomposite`) framework to turn the Orange Pi One into an emulated keyboard and mouse. If you wish to adapt this project for other SBCs or MCUs, please refer to their respective hardware datasheets to ensure USB OTG or USB Device mode support.