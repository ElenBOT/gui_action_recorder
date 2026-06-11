import time
import struct
import os

def play_hid_file(file_path, keyboard_path="/dev/hidg0", mouse_path="/dev/hidg1"):
    """
    Reads and plays back binary .hid macro files by writing to Linux USB HID gadget drivers.
    
    Args:
        file_path (str): Path to the .hid file.
        keyboard_path (str): Linux keyboard simulation gadget node (default: /dev/hidg0).
        mouse_path (str): Linux mouse simulation gadget node (default: /dev/hidg1).
    """
    if not os.path.exists(file_path):
        print(f"Error: .hid file not found: {file_path}")
        return
        
    print(f"Starting macro playback: {file_path} ...")
    
    # Open Linux USB HID emulation nodes (in unbuffered binary write mode)
    kbd_f = None
    mse_f = None
    
    try:
        kbd_f = open(keyboard_path, "wb", buffering=0)
    except PermissionError:
        print(f"Permission Denied: Please run this script with sudo to access {keyboard_path}")
        return
    except Exception as e:
        print(f"Warning: Failed to open keyboard node {keyboard_path} ({e}). Running in test mode (printing only, no physical output).")
        
    try:
        mse_f = open(mouse_path, "wb", buffering=0)
    except Exception as e:
        if kbd_f:
            print(f"Warning: Failed to open mouse node {mouse_path} ({e}).")

    # Read binary data stream
    with open(file_path, "rb") as f:
        while True:
            # Read 6-byte header: [Delay_ms (4B Uint32)] + [DevType (1B)] + [ReportLen (1B)]
            header = f.read(6)
            if not header or len(header) < 6:
                break  # End of file (EOF)
                
            delay_ms, dev_type, report_len = struct.unpack("<IBB", header)
            report_bytes = f.read(report_len)
            
            # Wait for event trigger time
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
                
            # Write to the corresponding driver node based on device type
            if dev_type == 0:  # Keyboard
                if kbd_f:
                    kbd_f.write(report_bytes)
                else:
                    print(f"[Test-Keyboard] Delay: {delay_ms}ms | Report: {report_bytes.hex()}")
            elif dev_type == 1:  # Mouse
                if mse_f:
                    mse_f.write(report_bytes)
                else:
                    print(f"[Test-Mouse] Delay: {delay_ms}ms | Report: {report_bytes.hex()}")

    # Release and restore state to prevent keys from getting stuck
    if kbd_f:
        # Send all-released report
        kbd_f.write(bytes([0x00] * 8))
        kbd_f.close()
        print("All keyboard keys released and keyboard node closed.")
    if mse_f:
        # Send all-released report
        mse_f.write(bytes([0x00] * 5))
        mse_f.close()
        print("All mouse keys released and mouse node closed.")
        
    print("Macro playback finished.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <macro_name.hid>")
        sys.exit(1)
        
    play_hid_file(sys.argv[1])
