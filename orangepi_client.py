import time
import struct
import os

def play_hid_file(file_path, keyboard_path="/dev/hidg0", mouse_path="/dev/hidg1"):
    """
    讀取並播放二進位 .hid 巨集指令檔案，寫入 Linux USB HID gadget 驅動檔案。
    
    參數:
        file_path (str): .hid 檔案路徑。
        keyboard_path (str): Linux 模擬鍵盤驅動節點 (預設為 /dev/hidg0)。
        mouse_path (str): Linux 模擬滑鼠驅動節點 (預設為 /dev/hidg1)。
    """
    if not os.path.exists(file_path):
        print(f"錯誤: 找不到 .hid 檔案: {file_path}")
        return
        
    print(f"正在啟動巨集播放: {file_path} ...")
    
    # 開啟 Linux USB HID 模擬節點 (以非緩衝二進位寫入模式開啟)
    kbd_f = None
    mse_f = None
    
    try:
        kbd_f = open(keyboard_path, "wb", buffering=0)
    except PermissionError:
        print(f"權限不足: 請使用 sudo 執行此腳本以存取 {keyboard_path}")
        return
    except Exception as e:
        print(f"警告: 無法開啟鍵盤節點 {keyboard_path} ({e})。將在測試模式下執行 (僅列印，不實體輸出)。")
        
    try:
        mse_f = open(mouse_path, "wb", buffering=0)
    except Exception as e:
        if kbd_f:
            print(f"警告: 無法開啟滑鼠節點 {mouse_path} ({e})。")

    # 讀取二進位資料串流
    with open(file_path, "rb") as f:
        while True:
            # 讀取 6 位元組標頭: [Delay_ms (4B Uint32)] + [DevType (1B)] + [ReportLen (1B)]
            header = f.read(6)
            if not header or len(header) < 6:
                break  # 檔案讀取結束 (EOF)
                
            delay_ms, dev_type, report_len = struct.unpack("<IBB", header)
            report_bytes = f.read(report_len)
            
            # 等待事件觸發時間
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
                
            # 依據硬體類別寫入對應驅動節點
            if dev_type == 0:  # 鍵盤
                if kbd_f:
                    kbd_f.write(report_bytes)
                else:
                    print(f"[測試-鍵盤] 延遲: {delay_ms}ms | 報告: {report_bytes.hex()}")
            elif dev_type == 1:  # 滑鼠
                if mse_f:
                    mse_f.write(report_bytes)
                else:
                    print(f"[測試-滑鼠] 延遲: {delay_ms}ms | 報告: {report_bytes.hex()}")

    # 釋放與還原狀態 (避免按鍵卡住)
    if kbd_f:
        # 發送全放開報告
        kbd_f.write(bytes([0x00] * 8))
        kbd_f.close()
        print("已釋放所有鍵盤按鍵並關閉節點。")
    if mse_f:
        # 發送全放開報告
        mse_f.write(bytes([0x00] * 5))
        mse_f.close()
        print("已釋放所有滑鼠按鍵並關閉節點。")
        
    print("巨集播放結束。")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("使用說明: python orangepi_client.py <巨集名稱.hid>")
        sys.exit(1)
        
    play_hid_file(sys.argv[1])
