"""
Batch TTS Processing Handler
"""

import time
import re
import threading
from typing import List, Dict
from aqt.qt import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QTextEdit, QThread, pyqtSignal, Qt
from aqt import mw
from .config_dialog import ConfigDialog
from .tts_processor import TTSProcessor


class ProgressDialog(QDialog):
    """Dialog showing batch processing progress"""
    
    def __init__(self, parent, total_notes: int):
        super().__init__(parent)
        self.setup_ui(total_notes)
        self.handler_ref = None
        
    def setup_ui(self, total_notes: int):
        self.setWindowTitle("Processing Gemini TTS")
        self.setMinimumWidth(500)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        self.status_label = QLabel("Initializing...")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(total_notes)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m") 
        layout.addWidget(self.progress_bar)
        
        self.stats_label = QLabel("Processed: 0 | Success: 0 | Failed: 0")
        layout.addWidget(self.stats_label)
        
        self.usage_label = QLabel("Session Usage - Input: 0 | Output: 0")
        layout.addWidget(self.usage_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        layout.addWidget(self.log_text)
        
        self.cancel_btn = QPushButton("Cancel")
        layout.addWidget(self.cancel_btn)
        self.setLayout(layout)
        
    def update_progress(self, current: int, status: str, processed: int, 
                       success: int, failed: int):
        self.progress_bar.setValue(current)
        self.status_label.setText(status)
        self.stats_label.setText(f"Processed: {processed} | Success: {success} | Failed: {failed}")
        
    def update_usage(self, input_tokens, output_tokens):
        self.usage_label.setText(f"Session Usage - Input: {input_tokens} | Output: {output_tokens}")
        
    def add_log(self, message: str):
        self.log_text.append(message)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        if self.handler_ref and self.handler_ref.worker and self.handler_ref.worker.isRunning():
            self.handler_ref.on_cancel()
            event.ignore()
        else:
            event.accept()


class TTSWorker(QThread):
    """Background worker thread"""
    
    progress_update = pyqtSignal(int, str, int, int, int)
    usage_update = pyqtSignal(int, int)
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal(str, dict) # Return summary and final stats
    
    def __init__(self, note_ids, config, processor):
        super().__init__()
        self.note_ids = note_ids
        self.config = config
        self.processor = processor
        self.is_cancelled = False
        self.note_type_map = {cfg['note_type']: cfg for cfg in config['note_type_configs']}
        
        # Session Stats
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    def _run_on_main_sync(self, func):
        container = {'result': None, 'error': None}
        event = threading.Event()
        def wrapper():
            try:
                container['result'] = func()
            except Exception as e:
                container['error'] = e
            finally:
                event.set()
        mw.taskman.run_on_main(wrapper)
        if not event.wait(timeout=30):
            raise TimeoutError("Main thread operation timed out")
        if container['error']:
            raise container['error']
        return container['result']

    def run(self):
        success_count = 0
        failed_count = 0
        processed_count = 0
        total = len(self.note_ids)
        
        for idx, note_id in enumerate(self.note_ids):
            if self.is_cancelled:
                self.log_update.emit("Processing cancelled by user.")
                break

            # --- READ DATA ---
            def get_note_data():
                try:
                    note = mw.col.get_note(note_id)
                except: return None, "deleted"

                model = note.note_type()['name']
                if model not in self.note_type_map: return None, "skip_model"
                    
                cfg = self.note_type_map[model]
                src = cfg['source_field']
                tgt = cfg['target_field']
                if src not in note: return None, f"Field '{src}' missing"
                    
                text = note[src]
                if self.config.get('skip_existing_audio', True):
                    if tgt in note and '[sound:' in note[tgt]:
                        return None, "exists"
                return (text, src, tgt), "ok"

            try:
                data, status = self._run_on_main_sync(get_note_data)
            except Exception as e:
                data, status = None, f"Read Error: {str(e)}"
            
            if status != "ok":
                processed_count += 1
                if status == "skip_model": self.log_update.emit(f"Note {note_id}: Skipped (No config)")
                elif status == "exists": self.log_update.emit(f"Note {note_id}: Skipped (Audio exists)")
                elif status == "deleted": self.log_update.emit(f"Note {note_id}: Skipped (Deleted)")
                else:
                    failed_count += 1
                    self.log_update.emit(f"Note {note_id}: Error - {status}")
                self.progress_update.emit(processed_count, "Skipped...", processed_count, success_count, failed_count)
                continue

            text, src_field, tgt_field = data
            clean_text = re.sub(r'<[^>]+>', '', text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            if not clean_text:
                processed_count += 1
                failed_count += 1
                self.log_update.emit(f"Note {note_id}: Failed (Empty text)")
                self.progress_update.emit(processed_count, "Empty text...", processed_count, success_count, failed_count)
                continue

            # --- CALL API ---
            self.progress_update.emit(processed_count, f"Generating ({idx+1}/{total})...", processed_count, success_count, failed_count)
            
            audio_data = None
            model_info = ""
            stats = {}
            
            try:
                audio_data, model_info, stats = self.processor.generate_with_fallback(
                    clean_text,
                    self.config['primary_model'],
                    self.config['fallback_model'],
                    self.config.get('enable_fallback', True),
                    self.config.get('retry_attempts', 3),
                    self.config.get('retry_delay', 2)
                )
                
                # Update Session Stats
                if stats:
                    self.total_input_tokens += stats.get('input_tokens', 0)
                    self.total_output_tokens += stats.get('output_tokens', 0)
                    if audio_data:
                        self.total_requests += 1
                    self.usage_update.emit(self.total_input_tokens, self.total_output_tokens)
                    
            except Exception as e:
                model_info = str(e)

            # --- WRITE DATA ---
            if audio_data:
                def save_result():
                    filename = f"gemini_tts_{note_id}_{int(time.time())}.wav"
                    mw.col.media.write_data(filename, audio_data)
                    try:
                        note = mw.col.get_note(note_id)
                        note[tgt_field] = f"[sound:{filename}]"
                        mw.col.update_note(note)
                        return True, filename
                    except: return False, "Note deleted before save"

                try:
                    success, msg = self._run_on_main_sync(save_result)
                    if success:
                        success_count += 1
                        used_model_str = f" ({model_info})" if model_info != self.config['primary_model'] else ""
                        self.log_update.emit(f"Note {note_id}: Success{used_model_str}")
                    else:
                        failed_count += 1
                        self.log_update.emit(f"Note {note_id}: Save Error - {msg}")
                except Exception as e:
                    failed_count += 1
                    self.log_update.emit(f"Note {note_id}: Save Future Error - {str(e)}")
            else:
                failed_count += 1
                self.log_update.emit(f"Note {note_id}: API Error - {model_info}")

            processed_count += 1
            self.progress_update.emit(processed_count, "Waiting...", processed_count, success_count, failed_count)

        summary = f"\nProcessing Complete!\nTotal: {total}\nSuccess: {success_count}\nFailed: {failed_count}\n"
        summary += f"Session Tokens: Input {self.total_input_tokens}, Output {self.total_output_tokens}"
        
        final_stats = {
            'requests': self.total_requests,
            'input_tokens': self.total_input_tokens,
            'output_tokens': self.total_output_tokens
        }
        self.finished_signal.emit(summary, final_stats)


class BatchTTSHandler:
    """Handles batch TTS processing for selected notes"""
    
    def __init__(self, mw, note_ids: List[int]):
        self.mw = mw
        self.note_ids = note_ids
        self.global_config = mw.addonManager.getConfig(__name__) or {}
        
        # Determine active profile config
        self.profile_name = self.global_config.get('current_profile', 'Default')
        profiles = self.global_config.get('profiles', {})
        
        # If structure is old, wrap it or use default
        if not profiles and 'api_key' in self.global_config:
            # Old config format detected, treat as default profile
            self.active_config = self.global_config
        else:
            self.active_config = profiles.get(self.profile_name, self.get_default_config())

        self.dialog = None
        self.worker = None
            
    def get_default_config(self):
        return {
            'api_key': '',
            'primary_model': 'gemini-2.5-flash-tts',
            'fallback_model': 'gemini-2.5-flash-tts',
            'enable_fallback': True,
            'voice_name': 'Zephyr',
            'temperature': 1.0,
            'system_instruction': '',
            'note_type_configs': [],
            'stats': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
        }
        
    def start(self):
        # 1. Check configuration
        if not self.active_config.get('api_key') or not self.active_config.get('note_type_configs'):
            dialog = ConfigDialog(self.mw, self.global_config)
            if dialog.exec():
                self.global_config = dialog.get_config()
                self.mw.addonManager.writeConfig(__name__, self.global_config)
                # Re-init with new config
                self.__init__(self.mw, self.note_ids)
                if not self.active_config.get('api_key'): return 
            else:
                return
                
        # 2. Setup Processor
        processor = TTSProcessor(
            api_key=self.active_config['api_key'],
            voice_name=self.active_config.get('voice_name', 'Zephyr'),
            temperature=self.active_config.get('temperature', 1.0),
            system_instruction=self.active_config.get('system_instruction', '')
        )
        
        # 3. Setup Dialog
        self.dialog = ProgressDialog(self.mw, len(self.note_ids))
        self.dialog.cancel_btn.clicked.connect(self.on_cancel)
        self.dialog.handler_ref = self 
        self.dialog.show()
        
        # 4. Setup Worker
        self.worker = TTSWorker(self.note_ids, self.active_config, processor)
        self.worker.progress_update.connect(self.dialog.update_progress)
        self.worker.usage_update.connect(self.dialog.update_usage)
        self.worker.log_update.connect(self.dialog.add_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()
        
    def on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.is_cancelled = True
            self.dialog.cancel_btn.setEnabled(False)
            self.dialog.status_label.setText("Cancelling...")
            
    def on_finished(self, summary, session_stats):
        self.dialog.add_log(summary)
        self.dialog.status_label.setText("Done")
        self.dialog.progress_bar.setValue(len(self.note_ids))
        
        self.dialog.cancel_btn.setText("Close")
        self.dialog.cancel_btn.setEnabled(True)
        try: self.dialog.cancel_btn.clicked.disconnect()
        except: pass
        self.dialog.cancel_btn.clicked.connect(self.close_and_cleanup)
        
        # --- Update Persistent Stats ---
        # We need to reload the global config from disk in case it changed elsewhere,
        # but for simplicity we rely on the object we have + updates
        current_stats = self.active_config.get('stats', {'requests': 0, 'input_tokens': 0, 'output_tokens': 0})
        
        current_stats['requests'] = current_stats.get('requests', 0) + session_stats['requests']
        current_stats['input_tokens'] = current_stats.get('input_tokens', 0) + session_stats['input_tokens']
        current_stats['output_tokens'] = current_stats.get('output_tokens', 0) + session_stats['output_tokens']
        
        # Save back to active config object
        self.active_config['stats'] = current_stats
        
        # Update the specific profile in global config
        if 'profiles' not in self.global_config:
            # Migration path if config was flat
            self.global_config = {
                'current_profile': 'Default',
                'profiles': {'Default': self.active_config}
            }
        else:
            self.global_config['profiles'][self.profile_name] = self.active_config
            
        self.mw.addonManager.writeConfig(__name__, self.global_config)
        
        self.mw.reset()
        
    def close_and_cleanup(self):
        self.dialog.accept()
        self.dialog.handler_ref = None