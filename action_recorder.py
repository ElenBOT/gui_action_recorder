import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pynput import mouse, keyboard
import time
import os

# Import custom modules
from utils import format_time, serialize_events, deserialize_events
from macro_runner import MacroRunner

# Setup absolute path to the macros directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDED_DIR = os.path.join(BASE_DIR, "recorded")

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
        self.root.geometry("450x540")  # Taller geometry to support panels cleanly
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
        elif state == "playing":
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
