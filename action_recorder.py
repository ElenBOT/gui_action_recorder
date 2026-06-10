import sys
import os

# Fix Windows High-DPI scaling issue (mouse coordinate drift / magnification)
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # 2 = PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pynput import mouse, keyboard
import time

# Import custom modules
from utils import format_time, serialize_events, deserialize_events
from macro_runner import MacroRunner
from translator import compile_macro_to_hid

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# Setup absolute path to the macros directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDED_DIR = os.path.join(BASE_DIR, "recorded")
CONFIG_FILE = os.path.join(BASE_DIR, "opi_config.json")

def load_opi_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                import json
                cfg = json.load(f)
                if "login" in cfg:
                    return cfg
                # Backward compatibility
                host = cfg.get("host", "orangepi.local")
                user = cfg.get("user", "orangepi")
                return {"login": f"{user}@{host}"}
        except Exception:
            pass
    return {"login": "orangepi@orangepi.local"}

def save_opi_config(login):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            import json
            json.dump({"login": login}, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def ensure_app_icon():
    """
    Generates a simple, clean pixel-art style video camera icon in PPM format if it doesn't exist.
    PPM format is natively supported by Tkinter across all platforms without any external libraries.
    """
    icon_path = os.path.join(BASE_DIR, "app_icon.ppm")
    if os.path.exists(icon_path):
        return icon_path
        
    try:
        pixels = bytearray(32 * 32 * 3)
        bg_r, bg_g, bg_b = 240, 240, 240 # Neutral light gray matching title bar background
        cam_r, cam_g, cam_b = 71, 85, 105 # Dark slate gray camera body
        red_r, red_g, red_b = 239, 68, 68 # Red recording dot
        
        for y in range(32):
            for x in range(32):
                idx = (y * 32 + x) * 3
                r, g, b = bg_r, bg_g, bg_b
                
                # Reels (two circles on top)
                if ((x - 10)**2 + (y - 8)**2 <= 16) or ((x - 20)**2 + (y - 8)**2 <= 16):
                    r, g, b = cam_r, cam_g, cam_b
                    
                # Camera body
                if 6 <= x <= 22 and 12 <= y <= 24:
                    r, g, b = cam_r, cam_g, cam_b
                    
                # Red recording dot in center of body
                if 12 <= x <= 16 and 16 <= y <= 20:
                    r, g, b = red_r, red_g, red_b
                    
                # Lens (trapezoid pointing right)
                if 23 <= x <= 28:
                    half_h = 3 + (x - 23) * 1.2
                    if 18 - half_h <= y <= 18 + half_h:
                        r, g, b = cam_r, cam_g, cam_b
                        
                pixels[idx] = r
                pixels[idx+1] = g
                pixels[idx+2] = b
                
        with open(icon_path, 'wb') as f:
            f.write(b"P6\n32 32\n255\n" + pixels)
        return icon_path
    except Exception:
        return None

class MacroApp:
    """
    Action Recorder Main GUI Window.
    Handles layout, event listening, macro replay, and file structure operations.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("GUI Action Recorder")
        # Calculate dynamic window geometry based on system DPI scaling
        base_width = 460
        base_height = 660
        try:
            dpi = self.root.winfo_fpixels('1i')
            scale_factor = dpi / 96.0
        except Exception:
            scale_factor = 1.0
            
        scaled_width = int(base_width * scale_factor)
        scaled_height = int(base_height * scale_factor)
        self.root.geometry(f"{scaled_width}x{scaled_height}")
        self.root.configure(bg="#f8fafc")
        
        # Set window icon
        icon_path = ensure_app_icon()
        if icon_path and os.path.exists(icon_path):
            try:
                self.app_icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self.app_icon)
            except Exception:
                pass
        
        # 1. Window attributes: topmost and alpha transparency (0.85 default)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.85)
        
        # Window close protocol handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # State variables
        self.events = []
        self.is_recording = False
        self.mouse_pressed = False
        self.is_saved = True
        self.start_time = 0
        
        # Recording mode state cache (default False: records all mouse moves)
        self.drag_only_mode = tk.BooleanVar(value=False)
        self.drag_only_mode_val = False
        
        # Orange Pi configuration & state
        opi_cfg = load_opi_config()
        self.opi_login = tk.StringVar(value=opi_cfg.get("login", "orangepi@orangepi.local"))
        self.opi_password = ""
        self.opi_log_buffer = ""
        
        # Hardware runners and listeners
        self.runner = MacroRunner()
        self.m_listener = None
        
        # Lifetime keyboard listener for global F8 hotkey
        self.k_listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.k_listener.start()
        
        # Build UI layout
        self._build_ui()
        
        # Load directories explorer
        self.refresh_explorer()

    def create_btn(self, parent, text, command, bg_color, fg_color, hover_color, font_size=10):
        """
        Creates a modern, premium flat button with dynamic hover visual states.
        """
        btn = tk.Button(
            parent, text=text, command=command, bg=bg_color, fg=fg_color,
            activebackground=hover_color, activeforeground=fg_color,
            font=("Segoe UI", font_size, "bold"), relief="flat", bd=0, padx=8, pady=4
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_color) if btn.cget("state") == tk.NORMAL else None)
        btn.bind("<Leave>", lambda e: btn.config(bg=bg_color) if btn.cget("state") == tk.NORMAL else None)
        return btn

    def _build_ui(self):
        """
        Constructs the modern, segmented card-style GUI.
        """
        # ==========================================
        # Panel 1: Status Panel (Ice Blue) - Left Aligned
        # ==========================================
        self.panel_status = tk.Frame(self.root, bg="#eff6ff", padx=16, pady=10)
        self.panel_status.pack(fill=tk.X)
        
        self.lbl_status = tk.Label(
            self.panel_status, text="Status: Ready", 
            font=("Segoe UI", 10, "bold"), fg="#1e40af", bg="#eff6ff"
        )
        self.lbl_status.pack(anchor=tk.W)
        
        self.lbl_hint = tk.Label(
            self.panel_status, text="[F8]: Start Record / Stop Record / Stop Playback", 
            font=("Segoe UI", 9, "bold"), fg="#b91c1c", bg="#eff6ff"
        )
        self.lbl_hint.pack(anchor=tk.W, pady=(2, 0))

        # ==========================================
        # Panel 2: Recording & Saving Panel (Mint Green, Swapped to Upper Section)
        # ==========================================
        self.panel_record = tk.Frame(self.root, bg="#f0fdf4", padx=16, pady=10)
        self.panel_record.pack(fill=tk.X)
        
        # Record button
        self.btn_record = self.create_btn(self.panel_record, "⏺ Record", self.toggle_record, "#10b981", "#ffffff", "#059669")
        self.btn_record.pack(fill=tk.X, pady=(0, 4))
        
        # Mode Checkbox
        self.chk_drag_only = tk.Checkbutton(
            self.panel_record, text="Record mouse movement only when dragging", variable=self.drag_only_mode,
            bg="#f0fdf4", activebackground="#f0fdf4", fg="#166534", font=("Segoe UI", 9), selectcolor="#ffffff"
        )
        self.chk_drag_only.pack(anchor=tk.W, pady=(0, 4))
        
        # Save Fields Frame
        save_frame = tk.Frame(self.panel_record, bg="#f0fdf4")
        save_frame.pack(fill=tk.X, pady=(4, 0))
        
        lbl_name = tk.Label(save_frame, text="Save Name:", font=("Segoe UI", 9, "bold"), bg="#f0fdf4", fg="#166534")
        lbl_name.pack(side=tk.LEFT)
        
        self.entry_name = tk.Entry(
            save_frame, bd=1, relief="flat", highlightthickness=1,
            highlightbackground="#cbd5e1", highlightcolor="#10b981", font=("Segoe UI", 9), bg="#ffffff"
        )
        self.entry_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6), ipady=3)
        
        self.btn_save = self.create_btn(save_frame, "💾", self.save_recording, "#cbd5e1", "#1e293b", "#94a3b8", font_size=10)
        self.btn_save.pack(side=tk.RIGHT)

        # ==========================================
        # Panel 4: Orange Pi Panel (Warm Orange/Peach)
        # ==========================================
        self.panel_orangepi = tk.Frame(self.root, bg="#fff7ed", padx=16, pady=10)
        self.panel_orangepi.pack(fill=tk.X, side=tk.BOTTOM)
        
        # OPi Login frame (user@host)
        opi_input_frame = tk.Frame(self.panel_orangepi, bg="#fff7ed")
        opi_input_frame.pack(fill=tk.X, pady=(0, 4))
        
        lbl_opi_login = tk.Label(opi_input_frame, text="OPi Login (user@host):", font=("Segoe UI", 9, "bold"), bg="#fff7ed", fg="#c2410c")
        lbl_opi_login.pack(side=tk.LEFT)
        
        self.entry_opi_login = tk.Entry(
            opi_input_frame, textvariable=self.opi_login, bd=1, relief="flat", highlightthickness=1,
            highlightbackground="#cbd5e1", highlightcolor="#ea580c", font=("Segoe UI", 9), bg="#ffffff"
        )
        self.entry_opi_login.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), ipady=3)
        
        # OPi Button Frame
        opi_btn_frame = tk.Frame(self.panel_orangepi, bg="#fff7ed")
        opi_btn_frame.pack(fill=tk.X, pady=(4, 0))
        
        # Compile & Upload Button
        self.btn_opi_upload = self.create_btn(opi_btn_frame, "📤 Compile & Send", self.compile_and_upload_opi, "#f97316", "#ffffff", "#ea580c")
        self.btn_opi_upload.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        
        # Play on OPi Button
        self.btn_opi_play = self.create_btn(opi_btn_frame, "⚡ Play on OPi", self.play_on_opi, "#ea580c", "#ffffff", "#c2410c")
        self.btn_opi_play.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        
        # Toggle Debug Log Button
        self.btn_opi_log = self.create_btn(opi_btn_frame, "📋 SSH Log", self.open_log_window, "#cbd5e1", "#1e293b", "#94a3b8")
        self.btn_opi_log.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ==========================================
        # Panel 3: Explorer & Playback Panel (Light Slate / Light Gray)
        # ==========================================
        self.panel_explore = tk.Frame(self.root, bg="#f8fafc", padx=16, pady=10)
        self.panel_explore.pack(fill=tk.BOTH, expand=True)
        
        explorer_frame = tk.Frame(self.panel_explore, bg="#f8fafc")
        explorer_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left column - Folders List
        left_frame = tk.Frame(explorer_frame, bg="#f8fafc")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        
        lbl_folders = tk.Label(left_frame, text="Folders", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#475569")
        lbl_folders.pack(anchor=tk.W, pady=2)
        
        self.list_folders = tk.Listbox(
            left_frame, bd=1, relief="flat", highlightthickness=1,
            highlightbackground="#cbd5e1", highlightcolor="#3b82f6",
            selectbackground="#3b82f6", selectforeground="#ffffff",
            font=("Segoe UI", 9), fg="#334155", bg="#ffffff",
            exportselection=False  # FIX: Retain selection focus highlight even when other widgets are focused
        )
        self.list_folders.pack(fill=tk.BOTH, expand=True)
        self.list_folders.bind("<<ListboxSelect>>", self.on_folder_selected)
        
        # Right column - Macros List
        right_frame = tk.Frame(explorer_frame, bg="#f8fafc")
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        
        lbl_files = tk.Label(right_frame, text="Macros", font=("Segoe UI", 9, "bold"), bg="#f8fafc", fg="#475569")
        lbl_files.pack(anchor=tk.W, pady=2)
        
        self.list_files = tk.Listbox(
            right_frame, bd=1, relief="flat", highlightthickness=1,
            highlightbackground="#cbd5e1", highlightcolor="#3b82f6",
            selectbackground="#3b82f6", selectforeground="#ffffff",
            font=("Segoe UI", 9), fg="#334155", bg="#ffffff",
            exportselection=False  # FIX: Retain selection focus highlight even when other widgets are focused
        )
        self.list_files.pack(fill=tk.BOTH, expand=True)
        self.list_files.bind("<<ListboxSelect>>", self.on_file_selected)
        self.list_files.bind("<ButtonPress-1>", self.on_drag_start)
        self.list_files.bind("<B1-Motion>", self.on_drag_motion)
        self.list_files.bind("<ButtonRelease-1>", self.on_drag_drop)
        
        # Explorer Toolbar (Unicode Folder+ / Refresh Icons)
        toolbar_frame = tk.Frame(self.panel_explore, bg="#f8fafc")
        toolbar_frame.pack(pady=4, fill=tk.X)
        
        self.btn_new_folder = self.create_btn(toolbar_frame, "📁⁺", self.create_folder, "#e2e8f0", "#475569", "#cbd5e1", font_size=10)
        self.btn_new_folder.pack(side=tk.LEFT, padx=(0, 6))
        
        self.btn_refresh = self.create_btn(toolbar_frame, "🔄", self.refresh_explorer, "#e2e8f0", "#475569", "#cbd5e1", font_size=10)
        self.btn_refresh.pack(side=tk.LEFT, padx=(0, 6))
        
        self.btn_delete = self.create_btn(toolbar_frame, "🗑", self.delete_selected, "#fee2e2", "#b91c1c", "#fca5a5", font_size=10)
        self.btn_delete.pack(side=tk.LEFT)
        
        self.lbl_info = tk.Label(
            toolbar_frame, text="",
            font=("Segoe UI", 8), fg="#64748b", bg="#f8fafc", justify=tk.RIGHT
        )
        self.lbl_info.pack(side=tk.RIGHT, fill=tk.X, expand=True, anchor=tk.E)
        
        # Play Button
        self.btn_play = self.create_btn(self.panel_explore, "▶ Play", self.play_events, "#3b82f6", "#ffffff", "#2563eb")
        self.btn_play.pack(fill=tk.X, pady=(6, 0))

    def set_gui_state(self, state):
        """
        Switches button and input control states depending on active application loop.
        """
        if state == "idle":
            self.btn_record.config(state=tk.NORMAL)
            self.btn_play.config(state=tk.NORMAL)
            self.entry_name.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.NORMAL)
            self.list_folders.config(state=tk.NORMAL)
            self.list_files.config(state=tk.NORMAL)
            self.btn_new_folder.config(state=tk.NORMAL)
            self.btn_refresh.config(state=tk.NORMAL)
            self.btn_delete.config(state=tk.NORMAL)
            self.chk_drag_only.config(state=tk.NORMAL)
            self.entry_opi_login.config(state=tk.NORMAL)
            self.btn_opi_upload.config(state=tk.NORMAL)
            self.btn_opi_play.config(state=tk.NORMAL)
            self.btn_opi_log.config(state=tk.NORMAL)
        elif state == "recording":
            self.btn_record.config(state=tk.NORMAL)
            self.btn_play.config(state=tk.DISABLED)
            self.entry_name.config(state=tk.DISABLED)
            self.btn_save.config(state=tk.DISABLED)
            self.list_folders.config(state=tk.DISABLED)
            self.list_files.config(state=tk.DISABLED)
            self.btn_new_folder.config(state=tk.DISABLED)
            self.btn_refresh.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)
            self.chk_drag_only.config(state=tk.DISABLED)
            self.entry_opi_login.config(state=tk.DISABLED)
            self.btn_opi_upload.config(state=tk.DISABLED)
            self.btn_opi_play.config(state=tk.DISABLED)
            self.btn_opi_log.config(state=tk.NORMAL)
        elif state in ("playing", "opi_running"):
            self.btn_record.config(state=tk.DISABLED)
            self.btn_play.config(state=tk.DISABLED)
            self.entry_name.config(state=tk.DISABLED)
            self.btn_save.config(state=tk.DISABLED)
            self.list_folders.config(state=tk.DISABLED)
            self.list_files.config(state=tk.DISABLED)
            self.btn_new_folder.config(state=tk.DISABLED)
            self.btn_refresh.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)
            self.chk_drag_only.config(state=tk.DISABLED)
            self.entry_opi_login.config(state=tk.DISABLED)
            self.btn_opi_upload.config(state=tk.DISABLED)
            self.btn_opi_play.config(state=tk.DISABLED)
            self.btn_opi_log.config(state=tk.NORMAL)

    def toggle_record(self):
        """
        Toggles recording execution modes.
        """
        if not self.is_recording:
            # Check for unsaved events
            if not self.is_saved and self.events:
                ans = messagebox.askyesnocancel("Warning", "You have unsaved recording events. Do you want to save before starting a new recording?")
                if ans is True:
                    saved = self.save_recording()
                    if not saved:
                        return
                elif ans is False:
                    pass
                else:
                    return
            
            # Start Recording
            self.events = []
            self.is_recording = True
            self.mouse_pressed = False
            self.is_saved = False
            self.start_time = time.time()
            
            # Cache mode state
            self.drag_only_mode_val = self.drag_only_mode.get()
            
            # Transparent window (alpha 0.3)
            self.root.attributes("-alpha", 0.3)
            
            # Switch record button colors to Active Red
            self.btn_record.config(text="⏹ Stop", bg="#ef4444", fg="#ffffff")
            self.btn_record.bind("<Enter>", lambda e: self.btn_record.config(bg="#dc2626") if self.is_recording else None)
            self.btn_record.bind("<Leave>", lambda e: self.btn_record.config(bg="#ef4444") if self.is_recording else None)
            
            # Clear file list highlights
            self.list_files.selection_clear(0, tk.END)
            self.lbl_info.config(text="")
            self.set_gui_state("recording")
            
            # Clear text field
            self.entry_name.delete(0, tk.END)
            
            # Launch mouse listener thread
            self.m_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
            self.m_listener.start()
            
            # Start timer count
            self.update_timer()
        else:
            # Stop Recording
            self.is_recording = False
            if self.m_listener:
                self.m_listener.stop()
                
            # Revert window opacity (0.85)
            self.root.attributes("-alpha", 0.85)
            
            # Revert record button colors to Safe Green
            self.btn_record.config(text="⏺ Record", bg="#10b981", fg="#ffffff")
            self.btn_record.bind("<Enter>", lambda e: self.btn_record.config(bg="#059669") if not self.is_recording else None)
            self.btn_record.bind("<Leave>", lambda e: self.btn_record.config(bg="#10b981") if not self.is_recording else None)
            
            self.set_gui_state("idle")
            
            # Perform post-cleanup of stop clicks
            self.filter_stop_events()
            
            self.lbl_info.config(text=f"Pending Save | {len(self.events)} actions")
            
            import json
            serialized = serialize_events(self.events)
            serialized_str = json.dumps(serialized, ensure_ascii=False)
            size_kb = len(serialized_str.encode('utf-8')) / 1024.0
            
            total_duration = self.events[-1][0] if self.events else 0
            self.lbl_status.config(
                text=f"Status: Recording Ended (Time: {format_time(total_duration)}, {len(self.events)} events, {size_kb:.1f} KB)", 
                fg="#16a34a"
            )

    def update_timer(self):
        """
        Updates active recording time counter dynamically.
        """
        if self.is_recording:
            elapsed = time.time() - self.start_time
            self.lbl_status.config(text=f"Status: Recording... ({format_time(elapsed)})", fg="#dc2626")
            self.root.after(100, self.update_timer)

    def filter_stop_events(self):
        """
        Filters stop clicks and move paths out of self.events stream.
        Called once in the main thread when recording is closed.
        """
        if not self.events:
            return

        try:
            rx = self.btn_record.winfo_rootx()
            ry = self.btn_record.winfo_rooty()
            rw = self.btn_record.winfo_width()
            rh = self.btn_record.winfo_height()
        except Exception:
            return

        def is_on_btn(x, y):
            return rx <= x <= rx + rw and ry <= y <= ry + rh

        filtered = list(self.events)
        while filtered:
            last = filtered[-1]
            etype = last[1]
            
            if etype == 'mouse':
                x, y = last[2], last[3]
                if is_on_btn(x, y):
                    filtered.pop()
                    continue
            elif etype == 'mousemove':
                x, y = last[2], last[3]
                if is_on_btn(x, y):
                    filtered.pop()
                    continue
            break
            
        self.events = filtered

    def handle_hotkey(self):
        """
        Callback router for global F8 clicks.
        """
        self.root.after(0, self._process_hotkey)

    def _process_hotkey(self):
        """
        Determines current state and processes hotkey actions.
        """
        if self.runner.is_playing:
            self.runner.stop()
            self.lbl_status.config(text="Status: Aborted by Hotkey", fg="#b91c1c")
        else:
            self.toggle_record()

    def on_click(self, x, y, button, pressed):
        """
        Mouse listener click hook.
        """
        if self.is_recording:
            self.mouse_pressed = pressed
            delay = time.time() - self.start_time
            self.events.append((delay, 'mouse', x, y, button, pressed))

    def on_move(self, x, y):
        """
        Mouse listener movement hook.
        """
        if self.is_recording:
            if not self.drag_only_mode_val or self.mouse_pressed:
                delay = time.time() - self.start_time
                self.events.append((delay, 'mousemove', x, y))

    def on_press(self, key):
        """
        Keyboard listener press hook. Intercepts F8.
        """
        if key == keyboard.Key.f8:
            self.handle_hotkey()
            return

        if self.is_recording:
            delay = time.time() - self.start_time
            self.events.append((delay, 'keydown', key))

    def on_release(self, key):
        """
        Keyboard listener release hook. Intercepts F8.
        """
        if key == keyboard.Key.f8:
            return

        if self.is_recording:
            delay = time.time() - self.start_time
            self.events.append((delay, 'keyup', key))

    def create_folder(self):
        """
        Prompts dialog to create a new folder under recorded/.
        """
        folder_name = simpledialog.askstring("Create Folder", "Enter new folder name:")
        if not folder_name:
            return
            
        folder_name = folder_name.strip()
        if not folder_name:
            return
            
        folder_path = os.path.join(RECORDED_DIR, folder_name)
        if os.path.exists(folder_path):
            messagebox.showwarning("Warning", f"Folder '{folder_name}' already exists!")
            return
            
        try:
            os.makedirs(folder_path)
            messagebox.showinfo("Success", f"Folder '{folder_name}' created successfully.")
            self.refresh_explorer()
            
            # Auto-highlight new folder
            folders = self.list_folders.get(0, tk.END)
            if folder_name in folders:
                idx = folders.index(folder_name)
                self.list_folders.selection_clear(0, tk.END)
                self.list_folders.selection_set(idx)
                self.list_folders.activate(idx)
                self.load_files_for_folder(folder_name)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create folder: {str(e)}")

    def delete_folder(self):
        """
        Deletes the currently selected folder and all its contents after user confirmation.
        """
        sel = self.list_folders.curselection()
        if not sel:
            messagebox.showwarning("Warning", "Please select a folder to delete first!")
            return
            
        folder_name = self.list_folders.get(sel[0])
        folder_path = os.path.join(RECORDED_DIR, folder_name)
        
        # Confirm deletion
        confirm = messagebox.askyesno(
            "Confirm Delete Folder", 
            f"Are you sure you want to delete folder '{folder_name}' and ALL its macro files?\nThis action cannot be undone."
        )
        if not confirm:
            return
            
        try:
            import shutil
            shutil.rmtree(folder_path)
            messagebox.showinfo("Success", f"Folder '{folder_name}' deleted successfully.")
            self.lbl_info.config(text="") # Clear details
            self.refresh_explorer()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete folder: {str(e)}")

    def delete_file(self):
        """
        Deletes the currently selected macro file after user confirmation.
        """
        sel_folder = self.list_folders.curselection()
        sel_file = self.list_files.curselection()
        if not sel_folder or not sel_file:
            messagebox.showwarning("Warning", "Please select a macro file to delete first!")
            return
            
        folder_name = self.list_folders.get(sel_folder[0])
        file_name = self.list_files.get(sel_file[0])
        file_path = os.path.join(RECORDED_DIR, folder_name, file_name)
        
        confirm = messagebox.askyesno(
            "Confirm Delete File", 
            f"Are you sure you want to delete macro '{file_name}' from folder '{folder_name}'?"
        )
        if not confirm:
            return
            
        try:
            os.remove(file_path)
            messagebox.showinfo("Success", f"File '{file_name}' deleted successfully.")
            
            # Reset event state if the deleted file was the one currently loaded
            loaded_name = self.entry_name.get().strip()
            if not loaded_name.endswith(".json"):
                loaded_name += ".json"
            if loaded_name == file_name:
                self.events = []
                self.is_saved = True
                self.entry_name.delete(0, tk.END)
                self.lbl_status.config(text="Status: Ready", fg="#1e40af")
                
            self.lbl_info.config(text="") # Clear details
            self.refresh_explorer()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete file: {str(e)}")

    def delete_selected(self):
        """
        Deletes the currently selected file (if any) or folder (if no file is selected) after confirmation.
        """
        sel_file = self.list_files.curselection()
        if sel_file:
            self.delete_file()
            return
            
        sel_folder = self.list_folders.curselection()
        if sel_folder:
            self.delete_folder()
            return
            
        messagebox.showwarning("Warning", "Please select a folder or macro file to delete first!")

    def on_drag_start(self, event):
        """
        Triggered when a drag operation starts on the files listbox.
        """
        index = self.list_files.nearest(event.y)
        if 0 <= index < self.list_files.size():
            self.dragged_file = self.list_files.get(index)
            self.list_files.config(cursor="no")  # Default to 'no-drop' cursor initially
        else:
            self.dragged_file = None

    def on_drag_motion(self, event):
        """
        Provides cursor visual feedback when dragging over widgets.
        Prevents default listbox selection change by returning 'break'.
        """
        if hasattr(self, 'dragged_file') and self.dragged_file:
            x, y = self.root.winfo_pointerxy()
            widget = self.root.winfo_containing(x, y)
            if widget == self.list_folders:
                local_y = y - self.list_folders.winfo_rooty()
                folder_idx = self.list_folders.nearest(local_y)
                if 0 <= folder_idx < self.list_folders.size():
                    # Pointing hand cursor indicates dropping is allowed on folder
                    self.list_files.config(cursor="hand2")
                else:
                    self.list_files.config(cursor="no")
            else:
                self.list_files.config(cursor="no")
        return "break"

    def on_drag_drop(self, event):
        """
        Handles drop event to move file.
        """
        self.list_files.config(cursor="")
        self.list_folders.config(cursor="")
        
        if not hasattr(self, 'dragged_file') or not self.dragged_file:
            return
            
        file_name = self.dragged_file
        self.dragged_file = None
        
        x, y = self.root.winfo_pointerxy()
        widget = self.root.winfo_containing(x, y)
        
        if widget == self.list_folders:
            local_y = y - self.list_folders.winfo_rooty()
            folder_idx = self.list_folders.nearest(local_y)
            if 0 <= folder_idx < self.list_folders.size():
                target_folder = self.list_folders.get(folder_idx)
                
                sel_folder = self.list_folders.curselection()
                if not sel_folder:
                    return
                current_folder = self.list_folders.get(sel_folder[0])
                
                if target_folder == current_folder:
                    return
                    
                self.execute_move_file(current_folder, file_name, target_folder)

    def execute_move_file(self, current_folder, file_name, target_folder):
        """
        Performs the file move operation from current_folder to target_folder.
        """
        file_path = os.path.join(RECORDED_DIR, current_folder, file_name)
        target_path = os.path.join(RECORDED_DIR, target_folder, file_name)
        
        # Confirm move
        confirm = messagebox.askyesno(
            "Confirm Move File", 
            f"Are you sure you want to move macro '{file_name}' to folder '{target_folder}'?"
        )
        if not confirm:
            return
            
        # Check overwrite
        if os.path.exists(target_path):
            overwrite = messagebox.askyesno("Confirm Overwrite", f"File '{file_name}' already exists in target folder '{target_folder}'. Overwrite?")
            if not overwrite:
                return
                
        try:
            import shutil
            shutil.move(file_path, target_path)
            messagebox.showinfo("Success", f"Moved '{file_name}' to folder '{target_folder}'.")
            
            # Refresh list explorer, keeping target folder active
            self.refresh_explorer()
            
            # Let's find target folder and select it
            folders_list = self.list_folders.get(0, tk.END)
            if target_folder in folders_list:
                t_idx = folders_list.index(target_folder)
                self.list_folders.selection_clear(0, tk.END)
                self.list_folders.selection_set(t_idx)
                self.list_folders.activate(t_idx)
                self.load_files_for_folder(target_folder, select_file=file_name)
                
                # Update details display
                self.update_file_info_display(target_path, len(self.events))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to move file: {str(e)}")

    def refresh_explorer(self):
        """
        Scans directory layouts and refreshes UI explorer lists.
        """
        if not os.path.exists(RECORDED_DIR):
            os.makedirs(RECORDED_DIR)
            
        # Cache active selections
        prev_folder = None
        f_sel = self.list_folders.curselection()
        if f_sel:
            prev_folder = self.list_folders.get(f_sel[0])
            
        prev_file = None
        file_sel = self.list_files.curselection()
        if file_sel:
            prev_file = self.list_files.get(file_sel[0])
            
        # Refresh folders
        self.list_folders.delete(0, tk.END)
        folders = [d for d in os.listdir(RECORDED_DIR) if os.path.isdir(os.path.join(RECORDED_DIR, d))]
        folders.sort()
        
        for f in folders:
            self.list_folders.insert(tk.END, f)
            
        if folders:
            # Restore selection if exists, else highlight first folder
            target_idx = 0
            if prev_folder in folders:
                target_idx = folders.index(prev_folder)
                
            self.list_folders.selection_set(target_idx)
            self.list_folders.activate(target_idx)
            self.load_files_for_folder(folders[target_idx], select_file=prev_file)
            
            if prev_file:
                file_path = os.path.join(RECORDED_DIR, folders[target_idx], prev_file)
                if os.path.exists(file_path):
                    self.update_file_info_display(file_path, len(self.events))
                else:
                    self.lbl_info.config(text="")
            else:
                self.lbl_info.config(text="")
        else:
            self.list_files.delete(0, tk.END)
            self.lbl_info.config(text="")

    def load_files_for_folder(self, folder_name, select_file=None):
        """
        Refreshes files column.
        """
        self.list_files.delete(0, tk.END)
        folder_path = os.path.join(RECORDED_DIR, folder_name)
        if not os.path.exists(folder_path):
            return
            
        files = [f for f in os.listdir(folder_path) if f.endswith(".json")]
        files.sort()
        
        for file in files:
            self.list_files.insert(tk.END, file)
            
        if select_file and select_file in files:
            f_idx = files.index(select_file)
            self.list_files.selection_set(f_idx)
            self.list_files.activate(f_idx)

    def on_folder_selected(self, event):
        """
        Triggered when folder selection changes.
        """
        sel = self.list_folders.curselection()
        if not sel:
            return
        folder_name = self.list_folders.get(sel[0])
        self.load_files_for_folder(folder_name)
        self.lbl_info.config(text="")

    def on_file_selected(self, event):
        """
        Triggered when file selection changes. Loads macro into memory.
        """
        sel_folder = self.list_folders.curselection()
        sel_file = self.list_files.curselection()
        if not sel_folder or not sel_file:
            return
            
        folder_name = self.list_folders.get(sel_folder[0])
        file_name = self.list_files.get(sel_file[0])
        
        file_path = os.path.join(RECORDED_DIR, folder_name, file_name)
        if not os.path.exists(file_path):
            messagebox.showwarning("Warning", f"Macro file '{file_name}' not found!")
            self.refresh_explorer()
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import json
                serialized = json.load(f)
            self.events = deserialize_events(serialized)
            self.is_saved = True
            
            # Populate entry field
            name_without_ext = os.path.splitext(file_name)[0]
            self.entry_name.delete(0, tk.END)
            self.entry_name.insert(0, name_without_ext)
            
            self.lbl_status.config(text=f"Status: Loaded [{folder_name} / {file_name}]", fg="#1e40af")
            self.update_file_info_display(file_path, len(serialized))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load: {str(e)}")

    def update_file_info_display(self, file_path, action_count):
        """
        Calculates file size and modification time, and displays file description in the toolbar label.
        """
        if not file_path or not os.path.exists(file_path):
            self.lbl_info.config(text="")
            return
            
        try:
            import datetime
            size_bytes = os.path.getsize(file_path)
            size_kb = size_bytes / 1024.0
            
            mtime = os.path.getmtime(file_path)
            dt = datetime.datetime.fromtimestamp(mtime)
            
            am_pm = "AM" if dt.hour < 12 else "PM"
            hour = dt.hour % 12
            if hour == 0:
                hour = 12
            time_str = f"{dt.year}/{dt.month}/{dt.day} {am_pm} {hour:02d}:{dt.minute:02d}"
            
            self.lbl_info.config(text=f"{size_kb:.1f} KB | {action_count} actions | {time_str}")
        except Exception:
            self.lbl_info.config(text="")

    def save_recording(self):
        """
        Saves macro to active subdirectory.
        """
        sel_folder = self.list_folders.curselection()
        if not sel_folder:
            messagebox.showwarning("Warning", "Please select a target folder on the left first!\n(Create one with the '📁⁺' button if needed)")
            return False
            
        folder_name = self.list_folders.get(sel_folder[0])
        filename = self.entry_name.get().strip()
        if not filename:
            messagebox.showwarning("Warning", "Please enter a filename!")
            return False
        if not self.events:
            messagebox.showwarning("Warning", "No recorded events to save!")
            return False
            
        if not filename.endswith(".json"):
            filename += ".json"
            
        file_path = os.path.join(RECORDED_DIR, folder_name, filename)
        
        # Overwrite confirm
        if os.path.exists(file_path):
            confirm = messagebox.askyesno("Confirm Overwrite", f"File '{filename}' in folder '{folder_name}' already exists. Overwrite?")
            if not confirm:
                return False
                
        try:
            serialized = serialize_events(self.events)
            with open(file_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(serialized, f, indent=4, ensure_ascii=False)
                
            messagebox.showinfo("Success", f"Saved to [{folder_name} / {filename}]")
            self.is_saved = True
            
            # Reload files
            self.load_files_for_folder(folder_name, select_file=filename)
            self.update_file_info_display(file_path, len(serialized))
            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {str(e)}")
            return False

    def play_events(self):
        """
        Plays current events.
        """
        if not self.events:
            messagebox.showwarning("Warning", "No macro events to play!")
            return
            
        # Update thread callbacks
        def on_start():
            self.root.after(0, lambda: self.set_gui_state("playing"))
            
        def on_progress(elapsed, total_time):
            self.root.after(0, lambda: self.lbl_status.config(
                text=f"Status: Playing... ({format_time(elapsed)} / {format_time(total_time)})", 
                fg="#d97706"
            ))
            
        def on_finish(total_time):
            self.root.after(0, lambda: self.set_gui_state("idle"))
            
            # Only update status if playback wasn't manually aborted by hotkey
            current_status = self.lbl_status.cget("text")
            if "Aborted" not in current_status:
                self.root.after(0, lambda: self.lbl_status.config(
                    text=f"Status: Playback Finished ({format_time(total_time)} / {format_time(total_time)})", 
                    fg="#16a34a"
                ))
            
        # Play events
        self.runner.play(self.events, on_start, on_progress, on_finish)

    def log_message(self, message):
        """
        Appends a message to the debug log text area.
        Runs safely in the Tkinter main thread.
        """
        self.root.after(0, lambda: self._write_log(message))

    def _write_log(self, message):
        self.opi_log_buffer += message + "\n"
        if hasattr(self, 'log_window') and self.log_window.winfo_exists():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

    def _append_raw_log(self, text):
        clean_text = text
        if self.opi_password and self.opi_password in clean_text:
            clean_text = clean_text.replace(self.opi_password, "********")
            
        self.opi_log_buffer += clean_text
        if hasattr(self, 'log_window') and self.log_window.winfo_exists():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, clean_text)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

    def _create_log_window(self):
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Orange Pi SSH Debug Log")
        
        # Scale log window geometry based on monitor DPI
        base_w, base_h = 550, 380
        try:
            dpi = self.log_window.winfo_fpixels('1i')
            scale = dpi / 96.0
        except Exception:
            scale = 1.0
        scaled_w = int(base_w * scale)
        scaled_h = int(base_h * scale)
        self.log_window.geometry(f"{scaled_w}x{scaled_h}")
        
        self.log_window.configure(bg="#1e293b")
        
        # Scrolled Text
        from tkinter import scrolledtext
        self.log_text = scrolledtext.ScrolledText(
            self.log_window, bg="#0f172a", fg="#38bdf8", 
            insertbackground="#ffffff", font=("Consolas", 10), relief="flat"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Pre-populate logs
        self.log_text.insert(tk.END, self.opi_log_buffer)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.log_window.attributes("-topmost", True)

    def open_log_window(self):
        """
        Manually opens the SSH Debug Log Window and populates it with the cached logs.
        """
        if not hasattr(self, 'log_window') or not self.log_window.winfo_exists():
            self._create_log_window()
        else:
            self.log_window.lift() # Bring to front if already open

    def compile_and_upload_opi(self):
        """
        Compiles the selected macro to a local .hid file and uploads it to Orange Pi via SFTP.
        """
        if not HAS_PARAMIKO:
            messagebox.showerror("Error", "Paramiko library is not installed. Orange Pi features are unavailable.")
            return

        # Get selected folder and file
        sel_folder = self.list_folders.curselection()
        sel_file = self.list_files.curselection()
        if not sel_folder or not sel_file:
            messagebox.showwarning("Warning", "Please select a macro file to upload first!")
            return

        folder_name = self.list_folders.get(sel_folder[0])
        file_name = self.list_files.get(sel_file[0])
        
        # Clear previous logs
        self.opi_log_buffer = ""
        if hasattr(self, 'log_window') and self.log_window.winfo_exists():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state=tk.DISABLED)
        
        login = self.opi_login.get().strip()
        if not login:
            messagebox.showwarning("Warning", "Please enter your Orange Pi user@host login details.")
            return

        if '@' in login:
            user, host = login.split('@', 1)
        else:
            user = "orangepi"
            host = login

        # Save config
        save_opi_config(login)

        # Get password
        if not self.opi_password:
            password = simpledialog.askstring("Password Required", f"Enter SSH password for {user}@{host}:", show='*')
            if not password:
                return
            self.opi_password = password
            
        json_path = os.path.join(RECORDED_DIR, folder_name, file_name)
        name_without_ext = os.path.splitext(file_name)[0]
        local_hid_path = os.path.join(RECORDED_DIR, folder_name, name_without_ext + ".hid")
        remote_file_name = name_without_ext + ".hid"

        # Set UI state to running
        self.set_gui_state("opi_running")
        self.lbl_status.config(text="Status: Compiling macro...", fg="#ea580c")
        
        # Open log window and write header
        self.log_message(f"=== Compile & Upload Macro to {user}@{host} ===")
        self.log_message(f"Local Macro: {json_path}")
        self.log_message(f"Local HID Binary: {local_hid_path}")

        def upload_worker():
            try:
                # 1. Compile
                self.log_message("\n[Local] Compiling JSON macro to HID binary format...")
                success = compile_macro_to_hid(json_path, local_hid_path)
                if not success:
                    raise Exception("Failed to compile macro to HID binary using translator.")
                self.log_message("[Local] Compilation successful.")
                    
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Connecting to Orange Pi...", fg="#ea580c"))
                self.log_message(f"[SSH] Connecting to {user}@{host} via SSH...")

                # 2. SSH/SFTP connection
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, username=user, password=self.opi_password, timeout=10)
                self.log_message("[SSH] SSH Connection established successfully.")
                
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Creating remote folders...", fg="#ea580c"))
                
                # Get home directory
                stdin, stdout, stderr = ssh.exec_command("echo $HOME")
                home_dir = stdout.read().decode().strip()
                if not home_dir:
                    home_dir = f"/home/{user}"
                self.log_message(f"[SSH] Detected home directory: {home_dir}")
                    
                # Create remote directory
                remote_dir = f"{home_dir}/pi_mouse/recorded"
                self.log_message(f"[SSH] Ensuring remote directory exists: {remote_dir}")
                ssh.exec_command(f"mkdir -p {remote_dir}")
                
                # Initialize SFTP
                self.log_message("[SFTP] Opening SFTP channel...")
                sftp = ssh.open_sftp()
                
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Uploading file...", fg="#ea580c"))
                
                remote_file_path = f"{remote_dir}/{remote_file_name}"
                self.log_message(f"[SFTP] Uploading: {local_hid_path} -> {remote_file_path}")
                sftp.put(local_hid_path, remote_file_path)
                self.log_message("[SFTP] File uploaded successfully.")
                
                sftp.close()
                ssh.close()
                self.log_message("[SSH] SSH connection closed.")
                
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Compile & Upload successful", fg="#16a34a"))
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Macro successfully compiled and uploaded to {user}@{host}:{remote_file_path}"))
                
            except paramiko.AuthenticationException:
                self.opi_password = "" # Clear cached wrong password
                self.log_message("\n[ERROR] SSH authentication failed. Please verify credentials.")
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: SSH Authentication Failed", fg="#dc2626"))
                self.root.after(0, lambda: messagebox.showerror("Authentication Error", "SSH login failed. Please verify your password and username."))
            except Exception as e:
                self.opi_password = "" # Might be connection issue or wrong password
                self.log_message(f"\n[ERROR] Operation failed: {str(e)}")
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Connection Failed", fg="#dc2626"))
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to upload to Orange Pi:\n{str(e)}"))

        import threading
        threading.Thread(target=upload_worker, daemon=True).start()

    def play_on_opi(self):
        """
        Connects to Orange Pi via SSH and plays the uploaded macro using 'sudo /usr/bin/python3 /home/<user>/pi_mouse/play.py ...'.
        """
        if not HAS_PARAMIKO:
            messagebox.showerror("Error", "Paramiko library is not installed. Orange Pi features are unavailable.")
            return

        # Get selected folder and file to know the macro name
        sel_folder = self.list_folders.curselection()
        sel_file = self.list_files.curselection()
        if not sel_folder or not sel_file:
            messagebox.showwarning("Warning", "Please select a macro file to play first!")
            return

        folder_name = self.list_folders.get(sel_folder[0])
        file_name = self.list_files.get(sel_file[0])
        name_without_ext = os.path.splitext(file_name)[0]
        remote_file_name = name_without_ext + ".hid"

        # Clear previous logs
        self.opi_log_buffer = ""
        if hasattr(self, 'log_window') and self.log_window.winfo_exists():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state=tk.DISABLED)

        login = self.opi_login.get().strip()
        if not login:
            messagebox.showwarning("Warning", "Please enter your Orange Pi user@host login details.")
            return

        if '@' in login:
            user, host = login.split('@', 1)
        else:
            user = "orangepi"
            host = login

        # Save config
        save_opi_config(login)

        # Get password
        if not self.opi_password:
            password = simpledialog.askstring("Password Required", f"Enter SSH password for {user}@{host}:", show='*')
            if not password:
                return
            self.opi_password = password

        # Set UI state to running
        self.set_gui_state("opi_running")
        self.lbl_status.config(text="Status: Connecting to Orange Pi...", fg="#ea580c")
        
        self.log_message(f"=== Play Macro on {user}@{host} ===")
        self.log_message(f"Remote Macro HID: {remote_file_name}")

        def play_worker():
            try:
                self.log_message(f"[SSH] Connecting to {user}@{host}...")
                # Connect
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host, username=user, password=self.opi_password, timeout=10)
                self.log_message("[SSH] SSH Connection established.")
                
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Playing macro on Orange Pi...", fg="#d97706"))

                # Get home directory
                stdin, stdout, stderr = ssh.exec_command("echo $HOME")
                home_dir = stdout.read().decode().strip()
                if not home_dir:
                    home_dir = f"/home/{user}"
                self.log_message(f"[SSH] Detected home directory: {home_dir}")

                # Execute command with sudo -S to feed the password
                cmd = f"sudo -S /usr/bin/python3 {home_dir}/pi_mouse/play.py {home_dir}/pi_mouse/recorded/{remote_file_name}"
                self.log_message(f"[SSH] Executing: {cmd}")
                
                # We use get_pty=True so that sudo -S can receive input on the pseudo-terminal
                stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
                
                self.log_message("[SSH] --- Command Output Stream Start ---")
                
                password_sent = False
                
                # Read output
                while True:
                    if stdout.channel.recv_ready():
                        data = stdout.channel.recv(1024)
                        if not data:
                            break
                        chunk = data.decode('utf-8', errors='ignore')
                        self.root.after(0, lambda c=chunk: self._append_raw_log(c))
                        
                        # Check if sudo is asking for password
                        chunk_lower = chunk.lower()
                        if not password_sent and ("password" in chunk_lower or "密碼" in chunk_lower or "password:" in chunk_lower):
                            self.log_message("\n[SSH] Password prompt detected, sending sudo password...")
                            stdin.write(self.opi_password + "\n")
                            stdin.flush()
                            password_sent = True
                    elif stdout.channel.exit_status_ready():
                        break
                    time.sleep(0.05)
                    
                # Final drain
                while stdout.channel.recv_ready():
                    data = stdout.channel.recv(1024)
                    if data:
                        chunk = data.decode('utf-8', errors='ignore')
                        self.root.after(0, lambda c=chunk: self._append_raw_log(c))
                        
                # Close connection
                exit_status = stdout.channel.recv_exit_status()
                self.log_message(f"\n[SSH] Command completed with exit code: {exit_status}")
                
                ssh.close()
                self.log_message("[SSH] Connection closed.")
                
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Remote Playback Finished", fg="#16a34a"))
                
                # Check for file missing error in output log buffer
                full_output = self.opi_log_buffer
                is_file_missing = ("找不到" in full_output and ".hid" in full_output) or ("錯誤: 找不到" in full_output)
                
                if is_file_missing:
                    self.root.after(0, lambda: messagebox.showwarning(
                        "Warning", 
                        f"Orange Pi error: Macro file not found on device!\n\nPath: {home_dir}/pi_mouse/recorded/{remote_file_name}\n\nPlease run 'Compile & Send' first."
                    ))
                elif exit_status == 0:
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Playback finished successfully on Orange Pi!"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Playback Error", f"Playback failed on Orange Pi with exit code {exit_status}.\nCheck SSH Debug Log window for errors."))
                
            except paramiko.AuthenticationException:
                self.opi_password = "" # Clear cached wrong password
                self.log_message("\n[ERROR] SSH authentication failed. Please verify credentials.")
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: SSH Authentication Failed", fg="#dc2626"))
                self.root.after(0, lambda: messagebox.showerror("Authentication Error", "SSH login failed. Please verify your password and username."))
            except Exception as e:
                self.log_message(f"\n[ERROR] Operation failed: {str(e)}")
                self.root.after(0, lambda: self.set_gui_state("idle"))
                self.root.after(0, lambda: self.lbl_status.config(text="Status: Playback Failed", fg="#dc2626"))
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to execute playback on Orange Pi:\n{str(e)}"))

        import threading
        threading.Thread(target=play_worker, daemon=True).start()

    def on_close(self):
        """
        Triggered when closing window. Clean hooks up.
        """
        if not self.is_saved and self.events:
            ans = messagebox.askyesnocancel("Warning", "You have unsaved recording events. Do you want to save before closing?")
            if ans is True:
                saved = self.save_recording()
                if saved:
                    if self.k_listener:
                        self.k_listener.stop()
                    self.root.destroy()
            elif ans is False:
                if self.k_listener:
                    self.k_listener.stop()
                self.root.destroy()
            else:
                return
        else:
            if self.k_listener:
                self.k_listener.stop()
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MacroApp(root)
    root.mainloop()
