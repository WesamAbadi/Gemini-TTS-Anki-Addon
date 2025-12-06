import time
import re
import threading
from collections import defaultdict
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
        self.setMinimumWidth(600)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        self.status_label = QLabel("Initializing...")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(total_notes)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m Notes") 
        layout.addWidget(self.progress_bar)
        
        # Updated Stats Label to include Skipped
        self.stats_label = QLabel("Fields Generated: 0 | Skipped: 0 | Failed: 0")
        layout.addWidget(self.stats_label)
        
        self.usage_label = QLabel("Session Usage - Input: 0 | Output: 0")
        layout.addWidget(self.usage_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(300)
        layout.addWidget(self.log_text)
        
        self.cancel_btn = QPushButton("Cancel")
        layout.addWidget(self.cancel_btn)
        self.setLayout(layout)
        
    def update_progress(self, current_note_idx: int, status: str, 
                       success: int, failed: int, skipped: int):
        self.progress_bar.setValue(current_note_idx)
        self.status_label.setText(status)
        self.stats_label.setText(f"Fields Generated: {success} | Skipped: {skipped} | Failed: {failed}")
        
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
    
    # note_idx, status_text, success_ops, failed_ops, skipped_ops
    progress_update = pyqtSignal(int, str, int, int, int)
    usage_update = pyqtSignal(int, int)
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal(str, dict)
    
    def __init__(self, note_ids, config, processor):
        super().__init__()
        self.note_ids = note_ids
        self.config = config
        self.processor = processor
        self.is_cancelled = False
        
        # Organize configs: { 'Note Type Name': [ {cfg1}, {cfg2} ] }
        self.note_type_map = defaultdict(list)
        for cfg in config['note_type_configs']:
            if cfg.get('enabled', True): # Only add enabled configs
                self.note_type_map[cfg['note_type']].append(cfg)
        
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
        success_ops = 0
        failed_ops = 0
        skipped_ops = 0
        consecutive_errors = 0
        
        total_notes = len(self.note_ids)
        request_wait = self.config.get('request_wait', 0.5)
        tag_on_success = self.config.get('tag_on_success', '')

        for idx, note_id in enumerate(self.note_ids):
            if self.is_cancelled:
                self.log_update.emit("Processing cancelled by user.")
                break
                
            if consecutive_errors >= 5:
                self.log_update.emit("Aborting: Too many consecutive errors.")
                break

            # --- 1. Get Note and identify Model ---
            def get_note_basic():
                try:
                    note = mw.col.get_note(note_id)
                    return note, note.note_type()['name']
                except: return None, None
            
            try:
                note_obj, model_name = self._run_on_main_sync(get_note_basic)
            except:
                note_obj = None

            if not note_obj:
                self.log_update.emit(f"Note {note_id}: Skipped (Deleted/Error)")
                continue

            # Check if we have configs for this model
            if model_name not in self.note_type_map:
                # Log only if verbose, otherwise silent skip implies no config
                continue

            configs = self.note_type_map[model_name]
            note_success = False

            # --- 2. Iterate through all mappings for this note ---
            for map_cfg in configs:
                if self.is_cancelled: break

                src = map_cfg['source_field']
                tgt = map_cfg['target_field']

                # Read fields
                if src not in note_obj:
                    self.log_update.emit(f"Note {note_id}: Field '{src}' missing")
                    failed_ops += 1
                    continue

                text = note_obj[src]
                
                # Check existing
                if self.config.get('skip_existing_audio', True):
                    if tgt in note_obj and '[sound:' in note_obj[tgt]:
                        self.log_update.emit(f"Note {note_id} ({src}): Skipped (Audio exists)")
                        skipped_ops += 1
                        self.progress_update.emit(idx + 1, "Skipping...", success_ops, failed_ops, skipped_ops)
                        continue

                # Clean Text
                clean_text = re.sub(r'<[^>]+>', '', text)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()

                if not clean_text:
                    self.log_update.emit(f"Note {note_id} ({src}): Skipped (Empty text)")
                    skipped_ops += 1
                    continue

                # Apply delay before request
                if request_wait > 0:
                    time.sleep(request_wait)

                # --- 3. Generate Audio ---
                self.progress_update.emit(idx + 1, f"Generating {src}...", success_ops, failed_ops, skipped_ops)
                
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
                    
                    if stats:
                        self.total_input_tokens += stats.get('input_tokens', 0)
                        self.total_output_tokens += stats.get('output_tokens', 0)
                        if audio_data:
                            self.total_requests += 1
                        self.usage_update.emit(self.total_input_tokens, self.total_output_tokens)
                
                except Exception as e:
                    model_info = str(e)

                # --- 4. Save Audio ---
                if audio_data:
                    consecutive_errors = 0 # Reset error counter
                    
                    def save_result(nid=note_id, t_field=tgt, data=audio_data, tag=tag_on_success):
                        filename = f"gemini_tts_{nid}_{int(time.time()*1000)}.wav" # added millis to avoid collision
                        mw.col.media.write_data(filename, data)
                        try:
                            n = mw.col.get_note(nid)
                            n[t_field] = f"[sound:{filename}]"
                            if tag:
                                n.add_tag(tag)
                            mw.col.update_note(n)
                            return True, filename
                        except: return False, "Note deleted"

                    try:
                        success, msg = self._run_on_main_sync(save_result)
                        if success:
                            success_ops += 1
                            note_success = True
                            self.log_update.emit(f"Note {note_id} ({src}): Success")
                        else:
                            failed_ops += 1
                            self.log_update.emit(f"Note {note_id} ({src}): Save Error - {msg}")
                    except Exception as e:
                        failed_ops += 1
                        self.log_update.emit(f"Note {note_id}: Save Future Error - {str(e)}")
                else:
                    consecutive_errors += 1
                    failed_ops += 1
                    self.log_update.emit(f"Note {note_id} ({src}): API Error - {model_info}")

            # End of Note Loop
            self.progress_update.emit(idx + 1, "Waiting...", success_ops, failed_ops, skipped_ops)

        summary = f"\nProcessing Complete!\nSuccess (Fields): {success_ops}\nSkipped: {skipped_ops}\nFailed: {failed_ops}\n"
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
        
        self.profile_name = self.global_config.get('current_profile', 'Default')
        profiles = self.global_config.get('profiles', {})
        
        if not profiles and 'api_key' in self.global_config:
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
            'request_wait': 0.5, # Default delay
            'tag_on_success': '',
            'note_type_configs': [],
            'stats': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
        }
        
    def start(self):
        if not self.active_config.get('api_key') or not self.active_config.get('note_type_configs'):
            dialog = ConfigDialog(self.mw, self.global_config)
            if dialog.exec():
                self.global_config = dialog.get_config()
                self.mw.addonManager.writeConfig(__name__, self.global_config)
                self.__init__(self.mw, self.note_ids)
                if not self.active_config.get('api_key'): return 
            else:
                return
                
        processor = TTSProcessor(
            api_key=self.active_config['api_key'],
            voice_name=self.active_config.get('voice_name', 'Zephyr'),
            temperature=self.active_config.get('temperature', 1.0),
            system_instruction=self.active_config.get('system_instruction', '')
        )
        
        self.dialog = ProgressDialog(self.mw, len(self.note_ids))
        self.dialog.cancel_btn.clicked.connect(self.on_cancel)
        self.dialog.handler_ref = self 
        self.dialog.show()
        
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
        
        current_stats = self.active_config.get('stats', {'requests': 0, 'input_tokens': 0, 'output_tokens': 0})
        current_stats['requests'] = current_stats.get('requests', 0) + session_stats['requests']
        current_stats['input_tokens'] = current_stats.get('input_tokens', 0) + session_stats['input_tokens']
        current_stats['output_tokens'] = current_stats.get('output_tokens', 0) + session_stats['output_tokens']
        
        self.active_config['stats'] = current_stats
        
        if 'profiles' not in self.global_config:
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