import os
from pynput import mouse, keyboard

def format_time(seconds):
    """
    將秒數格式化為 mm:ss 格式。
    
    參數:
        seconds (float): 總秒數。
        
    回傳:
        str: 格式化後的字串，例如 "01:23"。
    """
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"

def serialize_events(events):
    """
    將 pynput 的事件序列化為超輕量「緊湊列表格式」(Shorthand List JSON)。
    
    格式細節:
        滑鼠點擊: [delay, "m", x, y, button_id, pressed_id]
            button_id: 0(left), 1(right), 2(middle)
            pressed_id: 0(release), 1(press)
        滑鼠拖曳移動: [delay, "mm", x, y]
        按鍵: [delay, "kd"/"ku", key_class, key_value]
            event: "kd"(keydown), "ku"(keyup)
            key_class: 0(Key 名稱), 1(KeyCode 字元), 2(KeyCode VK虛擬鍵碼), 3(未知/字串)
    """
    serialized = []
    for event in events:
        delay = event[0]
        event_type = event[1]
        
        if event_type == 'mouse':
            _, _, x, y, button, pressed = event
            btn_id = 0
            if button == mouse.Button.left:
                btn_id = 0
            elif button == mouse.Button.right:
                btn_id = 1
            elif button == mouse.Button.middle:
                btn_id = 2
            serialized.append([delay, 'm', x, y, btn_id, 1 if pressed else 0])
            
        elif event_type == 'mousemove':
            _, _, x, y = event
            serialized.append([delay, 'mm', x, y])
            
        elif event_type in ('keydown', 'keyup'):
            _, _, key = event
            type_code = 'kd' if event_type == 'keydown' else 'ku'
            
            if isinstance(key, keyboard.Key):
                serialized.append([delay, type_code, 0, key.name])
            elif isinstance(key, keyboard.KeyCode):
                if key.char is not None:
                    serialized.append([delay, type_code, 1, key.char])
                elif key.vk is not None:
                    serialized.append([delay, type_code, 2, key.vk])
                else:
                    serialized.append([delay, type_code, 3, ''])
            else:
                serialized.append([delay, type_code, 3, str(key)])
                
    return serialized

def deserialize_events(serialized):
    """
    將序列化後的資料還原為 pynput 事件。
    支援向下相容（可解析舊版 Verbose 字典格式的 JSON）。
    """
    events = []
    for item in serialized:
        # 向下相容：解析舊版 Verbose 字典格式
        if isinstance(item, dict):
            delay = item['delay']
            event_type = item['type']
            if event_type == 'mouse':
                btn_name = item['button']
                try:
                    button = mouse.Button[btn_name]
                except KeyError:
                    button = mouse.Button.left
                events.append((delay, 'mouse', item['x'], item['y'], button, item['pressed']))
            elif event_type in ('keydown', 'keyup'):
                key_data = item['key']
                cls = key_data.get('class')
                if cls == 'Key':
                    name = key_data['value']
                    try:
                        key = keyboard.Key[name]
                    except KeyError:
                        key = keyboard.Key.space
                elif cls == 'KeyCode':
                    char = key_data.get('char')
                    vk = key_data.get('vk')
                    if char is not None:
                        key = keyboard.KeyCode.from_char(char)
                    elif vk is not None:
                        key = keyboard.KeyCode(vk=vk)
                    else:
                        key = keyboard.KeyCode()
                else:
                    key = keyboard.KeyCode.from_char(key_data.get('value', ''))
                events.append((delay, event_type, key))
            continue

        # 解析新版輕量列表格式 [delay, type_code, ...]
        delay = item[0]
        event_type = item[1]
        
        if event_type == 'm':
            x = item[2]
            y = item[3]
            btn_id = item[4]
            pressed = bool(item[5])
            
            if btn_id == 0:
                button = mouse.Button.left
            elif btn_id == 1:
                button = mouse.Button.right
            elif btn_id == 2:
                button = mouse.Button.middle
            else:
                button = mouse.Button.left
            events.append((delay, 'mouse', x, y, button, pressed))
            
        elif event_type == 'mm':
            x = item[2]
            y = item[3]
            events.append((delay, 'mousemove', x, y))
            
        elif event_type in ('kd', 'ku'):
            pynput_type = 'keydown' if event_type == 'kd' else 'keyup'
            key_class = item[2]
            val = item[3]
            
            if key_class == 0:
                try:
                    key = keyboard.Key[val]
                except KeyError:
                    key = keyboard.Key.space
            elif key_class == 1:
                key = keyboard.KeyCode.from_char(val)
            elif key_class == 2:
                key = keyboard.KeyCode(vk=val)
            else:
                key = keyboard.KeyCode.from_char(str(val))
                
            events.append((delay, pynput_type, key))
            
    return events
