"""
Batch TTS Processing Handler
"""

import time
import re
import threading
from typing import List
from aqt.qt import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QTextEdit, QThread, pyqtSignal, Qt
from aqt import mw
from .config_dialog import ConfigDialog
from .tts_processor import TTSProcessor


class ProgressDialog(QDialog):
    """Dialog showing batch processing progress"""
    
    def __init__(self, parent, total_notes: int):
        super().__init__(parent)
        self.setup_ui(total_notes)
        # Keep a reference to the worker/handler so they aren't garbage collected
        self.handler_ref = None
        
    def setup_ui(self, total_notes: int):
        self.setWindowTitle("Processing Gemini TTS")
        self.setMinimumWidth(500)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Prevent dialog from closing to ensure proper cleanup
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        
        self.status_label = QLabel("Initializing...")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(total_notes)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        self.stats_label = QLabel("Processed: 0 | Success: 0 | Failed: 0")
        layout.addWidget(self.stats_label)
        
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
        
    def add_log(self, message: str):
        self.log_text.append(message)
        # Auto-scroll to bottom
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        # Ensure we don't close if thread is running unless forcing cancel
        if self.handler_ref and self.handler_ref.worker and self.handler_ref.worker.isRunning():
            self.handler_ref.on_cancel()
            event.ignore()
        else:
            event.accept()


class TTSWorker(QThread):
    """Background worker thread to prevent UI freezing"""
    
    # Signals to update UI from background thread
    progress_update = pyqtSignal(int, str, int, int, int)
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal(str)
    
    def __init__(self, note_ids, config, processor):
        super().__init__()
        self.note_ids = note_ids
        self.config = config
        self.processor = processor
        self.is_cancelled = False
        
        # Pre-calculate map for efficiency
        self.note_type_map = {cfg['note_type']: cfg for cfg in config['note_type_configs']}

    def _run_on_main_sync(self, func):
        """Helper to run a function on the main thread and wait for result"""
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
        
        # Wait for main thread to finish (with timeout to prevent infinite hang)
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

            # --- STEP 1: READ DATA (Must run on main thread) ---
            def get_note_data():
                # Check if note still exists
                try:
                    note = mw.col.get_note(note_id)
                except:
                    return None, "deleted"

                model = note.note_type()['name']
                
                if model not in self.note_type_map:
                    return None, "skip_model"
                    
                cfg = self.note_type_map[model]
                src = cfg['source_field']
                tgt = cfg['target_field']
                
                if src not in note:
                    return None, f"Field '{src}' missing"
                    
                text = note[src]
                
                # Check existing audio
                if self.config.get('skip_existing_audio', True):
                    if tgt in note and '[sound:' in note[tgt]:
                        return None, "exists"
                        
                return (text, src, tgt), "ok"

            try:
                data, status = self._run_on_main_sync(get_note_data)
            except Exception as e:
                data, status = None, f"Read Error: {str(e)}"
            
            # Handle checks
            if status != "ok":
                processed_count += 1
                if status == "skip_model":
                    self.log_update.emit(f"Note {note_id}: Skipped (No config)")
                elif status == "exists":
                    self.log_update.emit(f"Note {note_id}: Skipped (Audio exists)")
                elif status == "deleted":
                    self.log_update.emit(f"Note {note_id}: Skipped (Deleted)")
                else:
                    failed_count += 1
                    self.log_update.emit(f"Note {note_id}: Error - {status}")
                
                self.progress_update.emit(idx + 1, "Skipped...", processed_count, success_count, failed_count)
                continue

            text, src_field, tgt_field = data
            
            # Strip HTML
            clean_text = re.sub(r'<[^>]+>', '', text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            if not clean_text:
                processed_count += 1
                failed_count += 1
                self.log_update.emit(f"Note {note_id}: Failed (Empty text)")
                self.progress_update.emit(idx + 1, "Empty text...", processed_count, success_count, failed_count)
                continue

            # --- STEP 2: CALL API (Runs in background) ---
            self.progress_update.emit(idx + 1, f"Generating ({idx+1}/{total})...", processed_count, success_count, failed_count)
            
            audio_data = None
            model_info = ""
            
            try:
                audio_data, model_info = self.processor.generate_with_fallback(
                    clean_text,
                    self.config['primary_model'],
                    self.config['fallback_model'],
                    self.config.get('enable_fallback', True),
                    self.config.get('retry_attempts', 3),
                    self.config.get('retry_delay', 2)
                )
            except Exception as e:
                model_info = str(e)

            # --- STEP 3: WRITE DATA (Must run on main thread) ---
            if audio_data:
                def save_result():
                    filename = f"gemini_tts_{note_id}_{int(time.time())}.wav"
                    # Use Anki's media writer
                    mw.col.media.write_data(filename, audio_data)
                    
                    # Update note
                    try:
                        note = mw.col.get_note(note_id)
                        note[tgt_field] = f"[sound:{filename}]"
                        mw.col.update_note(note)
                        return True, filename
                    except:
                        return False, "Note deleted before save"

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
            self.progress_update.emit(idx + 1, "Waiting...", processed_count, success_count, failed_count)

        # Finished loop
        summary = f"\nProcessing Complete!\nTotal: {total}\nSuccess: {success_count}\nFailed: {failed_count}"
        self.finished_signal.emit(summary)


class BatchTTSHandler:
    """Handles batch TTS processing for selected notes"""
    
    def __init__(self, mw, note_ids: List[int]):
        self.mw = mw
        self.note_ids = note_ids
        self.config = mw.addonManager.getConfig(__name__)
        if not self.config:
            self.config = self.get_default_config()
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
            'note_type_configs': [],
            'skip_existing_audio': True,
            'retry_attempts': 3,
            'retry_delay': 2
        }
        
    def start(self):
        # 1. Check configuration
        if not self.config.get('api_key') or not self.config.get('note_type_configs'):
            dialog = ConfigDialog(self.mw, self.config)
            if dialog.exec():
                self.config = dialog.get_config()
                self.mw.addonManager.writeConfig(__name__, self.config)
            else:
                return
                
        # 2. Setup Processor
        processor = TTSProcessor(
            api_key=self.config['api_key'],
            voice_name=self.config.get('voice_name', 'Zephyr'),
            temperature=self.config.get('temperature', 1.0)
        )
        
        # 3. Setup Dialog
        self.dialog = ProgressDialog(self.mw, len(self.note_ids))
        self.dialog.cancel_btn.clicked.connect(self.on_cancel)
        
        # Attach 'self' to the dialog to prevent Garbage Collection of the worker/handler
        self.dialog.handler_ref = self 
        
        self.dialog.show()
        
        # 4. Setup and Start Worker Thread
        self.worker = TTSWorker(self.note_ids, self.config, processor)
        
        # Connect signals
        self.worker.progress_update.connect(self.dialog.update_progress)
        self.worker.log_update.connect(self.dialog.add_log)
        self.worker.finished_signal.connect(self.on_finished)
        
        # Start the background thread
        self.worker.start()
        
    def on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.is_cancelled = True
            self.dialog.cancel_btn.setEnabled(False)
            self.dialog.status_label.setText("Cancelling... finishing last item...")
            
    def on_finished(self, summary):
        self.dialog.add_log(summary)
        self.dialog.status_label.setText("Done")
        self.dialog.progress_bar.setValue(len(self.note_ids))
        
        # Change Cancel button to Close
        self.dialog.cancel_btn.setText("Close")
        self.dialog.cancel_btn.setEnabled(True)
        # Reconnect click to close the dialog
        try:
            self.dialog.cancel_btn.clicked.disconnect()
        except:
            pass
            
        self.dialog.cancel_btn.clicked.connect(self.close_and_cleanup)
        
        # Refresh Anki UI
        self.mw.reset()
        
    def close_and_cleanup(self):
        self.dialog.accept()
        # Remove circular reference to allow GC
        self.dialog.handler_ref = None