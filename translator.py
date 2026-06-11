import os
import sys
import json
import struct
from pynput import mouse
from utils import deserialize_events

# 1. Keyboard mapping to USB HID Scancodes table
# Ref: USB HID Usage Tables (Keyboard/Keypad Page 0x07)
KEY_TO_HID = {
    # Letters
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09, 'g': 0x0a,
    'h': 0x0b, 'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f, 'm': 0x10, 'n': 0x11,
    'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15, 's': 0x16, 't': 0x17, 'u': 0x18,
    'v': 0x19, 'w': 0x1a, 'x': 0x1b, 'y': 0x1c, 'z': 0x1d,
    
    # Numbers
    '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21, '5': 0x22, '6': 0x23, '7': 0x24,
    '8': 0x25, '9': 0x26, '0': 0x27,
    
    # Common functional and special keys
    'enter': 0x28, 'space': 0x2c, 'tab': 0x2b, 'escape': 0x29, 'backspace': 0x2a,
    'caps_lock': 0x39,
    
    # Arrow keys
    'right': 0x4f, 'left': 0x50, 'down': 0x51, 'up': 0x52,
    
    # F keys
    'f1': 0x3a, 'f2': 0x3b, 'f3': 0x3c, 'f4': 0x3d, 'f5': 0x3e, 'f6': 0x3f,
    'f7': 0x40, 'f8': 0x41, 'f9': 0x42, 'f10': 0x43, 'f11': 0x44, 'f12': 0x45,
}

# Modifier keys mapping to HID masks (Modifier Byte)
MODIFIER_MASKS = {
    'ctrl': 0x01, 'ctrl_l': 0x01, 'ctrl_r': 0x10,
    'shift': 0x02, 'shift_l': 0x02, 'shift_r': 0x20,
    'alt': 0x04, 'alt_l': 0x04, 'alt_r': 0x40,
    'cmd': 0x08, 'cmd_l': 0x08, 'cmd_r': 0x80, # Win key / Command key
}

def get_hid_scancode(key):
    """
    Maps pynput key objects or names to USB HID Scancodes and modifier bytes.
    """
    if isinstance(key, str):
        key_str = key.lower()
    elif hasattr(key, 'name') and key.name:
        key_str = key.name.lower()
    elif hasattr(key, 'char') and key.char:
        key_str = key.char
    else:
        return None, 0

    # Check if it is a modifier key
    if key_str in MODIFIER_MASKS:
        return None, MODIFIER_MASKS[key_str]

    # Handle uppercase letters, automatically adding the Shift modifier
    shift_mask = 0
    if len(key_str) == 1 and 'A' <= key_str <= 'Z':
        shift_mask = 0x02  # Left Shift
        key_str = key_str.lower()

    scancode = KEY_TO_HID.get(key_str)
    return scancode, shift_mask

def compile_macro_to_hid(json_path, output_bin_path, screen_width=1920, screen_height=1080):
    """
    Reads a JSON macro file and compiles it to a binary file (.hid) executable by Orange Pi.
    """
    if not os.path.exists(json_path):
        print(f"Error: Source file not found: {json_path}")
        return False
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            serialized = json.load(f)
        events = deserialize_events(serialized)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return False

    print(f"Loading macro {json_path} ... {len(events)} events. Resolution set to: {screen_width}x{screen_height}")
    
    # Track hardware states
    # Keyboard state
    active_modifiers = 0
    active_keys = set()
    
    # Mouse button state mask (track whether mouse buttons are currently pressed)
    current_button_mask = 0x00
    
    # Output instructions set
    # Instruction structure: (delay_ms, dev_type, report_bytes)
    # dev_type: 0 for keyboard (/dev/hidg0), 1 for mouse (/dev/hidg1)
    instructions = []
    
    # Absolute coordinate touchscreen/tablet does not need relative mouse calibration, old 40 times (-127, -127) movement removed
    
    last_event_time = 0.0

    for i, event in enumerate(events):
        event_time = event[0]
        event_type = event[1]
        
        # Calculate the delay from the previous event (ms)
        delay_sec = event_time - last_event_time
        delay_ms = int(max(0, delay_sec * 1000))
        last_event_time = event_time

        if event_type == 'mouse':
            # Mouse button event
            _, _, x, y, button, pressed = event
            
            # 1. Update the current button state mask
            button_mask = 0
            if button == mouse.Button.left:
                button_mask = 0x01
            elif button == mouse.Button.right:
                button_mask = 0x02
            elif button == mouse.Button.middle:
                button_mask = 0x04
                
            if pressed:
                current_button_mask |= button_mask
            else:
                current_button_mask &= ~button_mask
                
            # 2. Calculate absolute coordinates (mapping to HID range 0 ~ 32767)
            hid_x = int(max(0, min(32767, (x / screen_width) * 32767)))
            hid_y = int(max(0, min(32767, (y / screen_height) * 32767)))
            
            # 3. Generate 5-byte absolute mouse report: [buttons, abs_x_low, abs_x_high, abs_y_low, abs_y_high]
            report = struct.pack("<BHH", current_button_mask, hid_x, hid_y)
            instructions.append((delay_ms, 1, report))

        elif event_type == 'mousemove':
            # Mouse move event
            _, _, x, y = event
            
            # 1. Calculate absolute coordinates
            hid_x = int(max(0, min(32767, (x / screen_width) * 32767)))
            hid_y = int(max(0, min(32767, (y / screen_height) * 32767)))
            
            # 2. Generate 5-byte absolute mouse report
            report = struct.pack("<BHH", current_button_mask, hid_x, hid_y)
            instructions.append((delay_ms, 1, report))

        elif event_type in ('keydown', 'keyup'):
            # Keyboard event
            _, _, key = event
            scancode, shift_mask = get_hid_scancode(key)
            
            if scancode is None and shift_mask == 0:
                # Check if it is a special modifier key
                modifier_code, _ = get_hid_scancode(key)
                # Re-query the modifier key
                key_str = ""
                if isinstance(key, str):
                    key_str = key.lower()
                elif hasattr(key, 'name') and key.name:
                    key_str = key.name.lower()
                
                modifier_mask = MODIFIER_MASKS.get(key_str, 0)
                
                if modifier_mask > 0:
                    if event_type == 'keydown':
                        active_modifiers |= modifier_mask
                    else:
                        active_modifiers &= ~modifier_mask
            else:
                # Regular keys
                if scancode is not None:
                    if event_type == 'keydown':
                        active_keys.add(scancode)
                        # If the input character requires Shift
                        if shift_mask > 0:
                            active_modifiers |= shift_mask
                    else:
                        active_keys.discard(scancode)
            
            # Generate 8-byte keyboard report structure:
            # [Modifier, Reserved(0), Key1, Key2, Key3, Key4, Key5, Key6]
            report_list = [active_modifiers, 0x00]
            # Support up to 6 keys concurrently
            pressed_keys_list = list(active_keys)[:6]
            # Pad to 6 keys
            pressed_keys_list += [0x00] * (6 - len(pressed_keys_list))
            report_list.extend(pressed_keys_list)
            
            report = bytes(report_list)
            instructions.append((delay_ms, 0, report))

    # Compile and write all instructions to a binary file (.hid)
    try:
        with open(output_bin_path, 'wb') as bin_file:
            for instr in instructions:
                delay, dev_type, report = instr
                header = struct.pack("<IBB", delay, dev_type, len(report))
                bin_file.write(header + report)
        print(f"Successfully compiled to binary file: {output_bin_path}")
        print(f"Original events: {len(events)} | Compiled HID instructions: {len(instructions)} | File size: {os.path.getsize(output_bin_path)} Bytes")
        return True
    except Exception as e:
        print(f"Error writing binary file: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <recorded_json_path> [output_hid_path] [screen_width] [screen_height]")
        sys.exit(1)
        
    json_in = sys.argv[1]
    bin_out = None
    width = 1920
    height = 1080
    
    # Parse arguments
    args = sys.argv[2:]
    if args:
        # If the first argument is numeric, it is the width; otherwise, it is the output binary path
        if args[0].isdigit():
            width = int(args[0])
            if len(args) >= 2 and args[1].isdigit():
                height = int(args[1])
        else:
            bin_out = args[0]
            if len(args) >= 2 and args[1].isdigit():
                width = int(args[1])
            if len(args) >= 3 and args[2].isdigit():
                height = int(args[2])
                
    if not bin_out:
        base_name, _ = os.path.splitext(json_in)
        bin_out = base_name + ".hid"
        
    compile_macro_to_hid(json_in, bin_out, width, height)
