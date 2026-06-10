import time
import threading
from pynput import mouse, keyboard

class MacroRunner:
    """
    負責巨集播放與硬體模擬輸入的核心控制類別。
    它使用獨立執行緒執行巨集播放，並透過 Callback 函數更新 GUI 狀態。
    """
    def __init__(self):
        self.m_ctrl = mouse.Controller()
        self.k_ctrl = keyboard.Controller()
        self.is_playing = False
        self._thread = None

    def play(self, events, on_start=None, on_progress=None, on_finish=None):
        """
        在背景執行緒中非同步播放錄製的巨集事件。
        
        參數:
            events (list): 事件列表。
            on_start (callable): 開始播放時的回調。
            on_progress (callable): 播放計時器更新時的回調，傳入 (elapsed, total_time)。
            on_finish (callable): 播放結束時的回調，傳入 (total_time)。
            
        回傳:
            bool: 成功啟動播放回傳 True，否則回傳 False。
        """
        if not events:
            return False
            
        if self.is_playing:
            return False
            
        self.is_playing = True
        total_time = events[-1][0] if events else 0
        
        def run_playback():
            if on_start:
                on_start()
                
            start_play_time = time.time()
            
            # 進度監控計時器迴圈，每 100 毫秒觸發一次進度回調
            def progress_loop():
                while self.is_playing:
                    elapsed = time.time() - start_play_time
                    if elapsed >= total_time:
                        break
                    if on_progress:
                        on_progress(elapsed, total_time)
                    time.sleep(0.1)
            
            if on_progress:
                threading.Thread(target=progress_loop, daemon=True).start()
                
            # 遍歷所有事件並執行
            for event in events:
                if not self.is_playing:
                    break
                    
                target_time = start_play_time + event[0]
                
                # 精確等待直到事件觸發點
                while time.time() < target_time and self.is_playing:
                    time.sleep(0.001)
                    
                if not self.is_playing:
                    break
                    
                event_type = event[1]
                if event_type == 'mouse':
                    _, _, x, y, button, pressed = event
                    # 移動滑鼠並執行按鍵
                    self.m_ctrl.position = (x, y)
                    if pressed:
                        self.m_ctrl.press(button)
                    else:
                        self.m_ctrl.release(button)
                elif event_type == 'mousemove':
                    _, _, x, y = event
                    # 在拖曳狀態下更新滑鼠座標
                    self.m_ctrl.position = (x, y)
                elif event_type == 'keydown':
                    try:
                        self.k_ctrl.press(event[2])
                    except:
                        pass
                elif event_type == 'keyup':
                    try:
                        self.k_ctrl.release(event[2])
                    except:
                        pass
                        
            self.is_playing = False
            if on_finish:
                on_finish(total_time)
                
        self._thread = threading.Thread(target=run_playback, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """
        強制中斷當前正在播放的巨集。
        """
        self.is_playing = False
