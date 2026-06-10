import os
import sys
import json
import struct
from pynput import mouse
from utils import deserialize_events

# 1. 鍵盤對應 USB HID Scancodes 表
# 參考 USB HID Usage Tables (Keyboard/Keypad Page 0x07)
KEY_TO_HID = {
    # 字母
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09, 'g': 0x0a,
    'h': 0x0b, 'i': 0x0c, 'j': 0x0d, 'k': 0x0e, 'l': 0x0f, 'm': 0x10, 'n': 0x11,
    'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15, 's': 0x16, 't': 0x17, 'u': 0x18,
    'v': 0x19, 'w': 0x1a, 'x': 0x1b, 'y': 0x1c, 'z': 0x1d,
    
    # 數字
    '1': 0x1e, '2': 0x1f, '3': 0x20, '4': 0x21, '5': 0x22, '6': 0x23, '7': 0x24,
    '8': 0x25, '9': 0x26, '0': 0x27,
    
    # 常用功能與特殊鍵
    'enter': 0x28, 'space': 0x2c, 'tab': 0x2b, 'escape': 0x29, 'backspace': 0x2a,
    'caps_lock': 0x39,
    
    # 方向鍵
    'right': 0x4f, 'left': 0x50, 'down': 0x51, 'up': 0x52,
    
    # F系列
    'f1': 0x3a, 'f2': 0x3b, 'f3': 0x3c, 'f4': 0x3d, 'f5': 0x3e, 'f6': 0x3f,
    'f7': 0x40, 'f8': 0x41, 'f9': 0x42, 'f10': 0x43, 'f11': 0x44, 'f12': 0x45,
}

# 修飾鍵與 HID 遮罩的對應 (Modifier Byte)
MODIFIER_MASKS = {
    'ctrl': 0x01, 'ctrl_l': 0x01, 'ctrl_r': 0x10,
    'shift': 0x02, 'shift_l': 0x02, 'shift_r': 0x20,
    'alt': 0x04, 'alt_l': 0x04, 'alt_r': 0x40,
    'cmd': 0x08, 'cmd_l': 0x08, 'cmd_r': 0x80, # Win鍵 / Command 鍵
}

def get_hid_scancode(key):
    """
    將 pynput 產生的按鍵物件或名稱對應為 USB HID Scancode 以及修飾鍵 Byte。
    """
    if isinstance(key, str):
        key_str = key.lower()
    elif hasattr(key, 'name') and key.name:
        key_str = key.name.lower()
    elif hasattr(key, 'char') and key.char:
        key_str = key.char
    else:
        return None, 0

    # 檢查是否為修飾鍵
    if key_str in MODIFIER_MASKS:
        return None, MODIFIER_MASKS[key_str]

    # 處理大寫字母，需自動補上 Shift 修飾鍵
    shift_mask = 0
    if len(key_str) == 1 and 'A' <= key_str <= 'Z':
        shift_mask = 0x02  # Left Shift
        key_str = key_str.lower()

    scancode = KEY_TO_HID.get(key_str)
    return scancode, shift_mask

def compile_macro_to_hid(json_path, output_bin_path, screen_width=1920, screen_height=1080):
    """
    讀取 JSON 巨集檔案並轉譯輸出為 OrangePi 可執行的二進位檔案 (.hid)。
    """
    if not os.path.exists(json_path):
        print(f"錯誤: 找不到來源檔案 {json_path}")
        return False
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            serialized = json.load(f)
        events = deserialize_events(serialized)
    except Exception as e:
        print(f"解析 JSON 錯誤: {e}")
        return False

    print(f"正在載入巨集 {json_path} ... 共 {len(events)} 個事件。設定解析度: {screen_width}x{screen_height}")
    
    # 追蹤硬體狀態
    # 鍵盤狀態
    active_modifiers = 0
    active_keys = set()
    
    # 滑鼠按鍵狀態遮罩 (追蹤當前是否有按住滑鼠按鍵)
    current_button_mask = 0x00
    
    # 輸出指令集
    # 指令結構為: (delay_ms, dev_type, report_bytes)
    # dev_type: 0 代表鍵盤 (/dev/hidg0), 1 代表滑鼠 (/dev/hidg1)
    instructions = []
    
    # 絕對座標觸控螢幕/繪圖板不需要相對位移校準，直接移除舊的 40 次 (-127, -127) 移動
    
    last_event_time = 0.0

    for i, event in enumerate(events):
        event_time = event[0]
        event_type = event[1]
        
        # 計算與上一個事件的時間差 (毫秒)
        delay_sec = event_time - last_event_time
        delay_ms = int(max(0, delay_sec * 1000))
        last_event_time = event_time

        if event_type == 'mouse':
            # 滑鼠按鍵事件
            _, _, x, y, button, pressed = event
            
            # 1. 更新當前的按鍵狀態遮罩
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
                
            # 2. 計算絕對座標 (對應到 HID 的 0 ~ 32767)
            hid_x = int(max(0, min(32767, (x / screen_width) * 32767)))
            hid_y = int(max(0, min(32767, (y / screen_height) * 32767)))
            
            # 3. 產生 5 位元組絕對滑鼠報告: [buttons, abs_x_low, abs_x_high, abs_y_low, abs_y_high]
            report = struct.pack("<BHH", current_button_mask, hid_x, hid_y)
            instructions.append((delay_ms, 1, report))

        elif event_type == 'mousemove':
            # 滑鼠移動事件
            _, _, x, y = event
            
            # 1. 計算絕對座標
            hid_x = int(max(0, min(32767, (x / screen_width) * 32767)))
            hid_y = int(max(0, min(32767, (y / screen_height) * 32767)))
            
            # 2. 產生 5 位元組絕對滑鼠報告
            report = struct.pack("<BHH", current_button_mask, hid_x, hid_y)
            instructions.append((delay_ms, 1, report))

        elif event_type in ('keydown', 'keyup'):
            # 鍵盤事件
            _, _, key = event
            scancode, shift_mask = get_hid_scancode(key)
            
            if scancode is None and shift_mask == 0:
                # 檢查是否為特殊修飾鍵
                modifier_code, _ = get_hid_scancode(key)
                # 重新查詢修飾鍵
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
                # 一般按鍵
                if scancode is not None:
                    if event_type == 'keydown':
                        active_keys.add(scancode)
                        # 如果輸入字元需要 Shift
                        if shift_mask > 0:
                            active_modifiers |= shift_mask
                    else:
                        active_keys.discard(scancode)
            
            # 產生 8 位元鍵盤報告結構:
            # [Modifier, Reserved(0), Key1, Key2, Key3, Key4, Key5, Key6]
            report_list = [active_modifiers, 0x00]
            # 最多支援 6 鍵並行
            pressed_keys_list = list(active_keys)[:6]
            # 補足到 6 鍵
            pressed_keys_list += [0x00] * (6 - len(pressed_keys_list))
            report_list.extend(pressed_keys_list)
            
            report = bytes(report_list)
            instructions.append((delay_ms, 0, report))

    # 將所有指令編譯寫入二進位檔 (.hid)
    try:
        with open(output_bin_path, 'wb') as bin_file:
            for instr in instructions:
                delay, dev_type, report = instr
                header = struct.pack("<IBB", delay, dev_type, len(report))
                bin_file.write(header + report)
        print(f"成功編譯至二進位檔 {output_bin_path}")
        print(f"原始事件數: {len(events)} | 編譯後 HID 指令數: {len(instructions)} | 檔案大小: {os.path.getsize(output_bin_path)} Bytes")
        return True
    except Exception as e:
        print(f"寫入二進位檔錯誤: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用說明: python translator.py <錄製的JSON檔案路徑> [輸出的二進位檔案路徑] [螢幕寬度] [螢幕高度]")
        sys.exit(1)
        
    json_in = sys.argv[1]
    bin_out = None
    width = 1920
    height = 1080
    
    # 解析參數
    args = sys.argv[2:]
    if args:
        # 如果第一個參數是純數字，代表它是寬度，否則它是輸出二進位路徑
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
