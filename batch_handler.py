import time
import re
import threading
import json
import concurrent.futures
from collections import defaultdict
from typing import List, Dict, Optional
from aqt.qt import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QTextEdit, QThread, pyqtSignal, Qt, QFont
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
        self.setWindowTitle("Processing TTS")
        self.setMinimumWidth(700)
        self.setMinimumHeight(550)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        layout = QVBoxLayout()
        
        # Status Label
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.status_label)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(total_notes)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m Items Processed")
        self.progress_bar.setStyleSheet("QProgressBar { height: 20px; }")
        layout.addWidget(self.progress_bar)
        
        # Stats
        self.stats_label = QLabel("Success: 0 | Skipped: 0 | Failed: 0")
        layout.addWidget(self.stats_label)
        
        self.usage_label = QLabel("Session Usage - Input: 0 | Output: 0")
        self.usage_label.setStyleSheet("color: #666;")
        layout.addWidget(self.usage_label)
        
        # Log Box
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_text.setFont(font)
        layout.addWidget(self.log_text)
        
        self.cancel_btn = QPushButton("Cancel")
        layout.addWidget(self.cancel_btn)
        self.setLayout(layout)
        
    def update_progress(self, current_val: int, status: str, 
                       success: int, failed: int, skipped: int):
        self.progress_bar.setValue(current_val)
        self.status_label.setText(status)
        self.stats_label.setText(f"Success: {success} | Skipped: {skipped} | Failed: {failed}")
        
    def update_usage(self, input_tokens, output_tokens):
        self.usage_label.setText(f"Session Usage - Input: {input_tokens} | Output: {output_tokens}")
        
    def add_log_html(self, html_msg: str):
        self.log_text.append(html_msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        if self.handler_ref and self.handler_ref.worker and self.handler_ref.worker.isRunning():
            self.handler_ref.on_cancel()
            event.ignore()
        else:
            event.accept()


class TTSWorker(QThread):
    """Background worker thread that manages a thread pool for concurrent API requests"""
    
    progress_update = pyqtSignal(int, str, int, int, int)
    max_update = pyqtSignal(int)  # New signal to update progress bar range
    usage_update = pyqtSignal(int, int)
    log_html_update = pyqtSignal(str) 
    finished_signal = pyqtSignal(str, dict)
    
    def __init__(self, note_ids, config, processor):
        super().__init__()
        self.note_ids = note_ids
        self.config = config
        self.processor = processor
        self.is_cancelled = False
        
        # Organize config for fast lookup
        self.note_type_map = defaultdict(list)
        for cfg in config['note_type_configs']:
            if cfg.get('enabled', True):
                self.note_type_map[cfg['note_type']].append(cfg)
        
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0
        
        self.success_ops = 0
        self.failed_ops = 0
        self.skipped_ops = 0
        self.processed_count = 0

    def _run_on_main_sync(self, func):
        """Run a function on the main thread and wait for result"""
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

    def _format_error(self, error_str: str) -> str:
        error_str = str(error_str)
        if len(error_str) > 150:
            return f"{error_str[:150]}..."
        return error_str

    def run(self):
        # 1. Prepare Work Items
        self.log_html_update.emit("Scanning notes...")
        
        work_items = []
        
        def prepare_tasks():
            tasks = []
            for nid in self.note_ids:
                if self.is_cancelled: break
                try:
                    note = mw.col.get_note(nid)
                    model_name = note.note_type()['name']
                    
                    if model_name in self.note_type_map:
                        for map_cfg in self.note_type_map[model_name]:
                            src = map_cfg['source_field']
                            tgt = map_cfg['target_field']
                            
                            if src not in note:
                                continue
                                
                            # Check existing
                            if self.config.get('skip_existing_audio', True):
                                if tgt in note and '[sound:' in note[tgt]:
                                    self.skipped_ops += 1
                                    if self.config.get('verbose_logging', False):
                                        self.log_html_update.emit(f"<span style='color:gray'>Note {nid} ({src}): Skipped (Audio exists)</span>")
                                    continue
                            
                            text = note[src]
                            clean_text = re.sub(r'<[^>]+>', '', text)
                            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                            
                            if not clean_text:
                                self.skipped_ops += 1
                                continue
                                
                            tasks.append({
                                'nid': nid,
                                'src_field': src,
                                'tgt_field': tgt,
                                'text': clean_text,
                                'raw_text': text
                            })
                except Exception:
                    continue
            return tasks

        try:
            work_items = self._run_on_main_sync(prepare_tasks)
        except Exception as e:
            self.log_html_update.emit(f"<span style='color:red'>Error scanning notes: {str(e)}</span>")
            return

        # 2. Update Progress Bar Range
        # Total operations = items to process + items already skipped
        total_ops = len(work_items) + self.skipped_ops
        self.max_update.emit(total_ops)
        
        # Start progress at skipped count
        self.processed_count = self.skipped_ops
        self.progress_update.emit(self.processed_count, "Starting...", self.success_ops, self.failed_ops, self.skipped_ops)
        
        total_items = len(work_items)
        if total_items == 0:
            # If everything was skipped, we are done
            self.progress_update.emit(total_ops, "Done", self.success_ops, self.failed_ops, self.skipped_ops)
            summary = f"<br><b>Processing Complete!</b><br>Skipped: {self.skipped_ops}"
            self.finished_signal.emit(summary, {})
            return

        # 3. Configure Thread Pool
        max_workers = self.config.get('max_concurrent', 1)
        request_wait = self.config.get('request_wait', 0.1)
        tag = self.config.get('tag_on_success', '')
        
        svc_prefix = "elevenlabs" if self.processor.service == "elevenlabs" else "gemini"

        # 4. Execution Function
        def process_item(item):
            if self.is_cancelled: return None
            
            if request_wait > 0:
                time.sleep(request_wait)

            result = {
                'item': item,
                'audio': None,
                'model': '',
                'stats': {},
                'error': None
            }
            
            check_cancel = lambda: self.is_cancelled

            try:
                audio_data, model_info, stats = self.processor.generate_with_fallback(
                    item['text'],
                    self.config.get('primary_model', ''),
                    self.config.get('fallback_model', ''),
                    self.config.get('enable_fallback', True),
                    self.config.get('retry_attempts', 3),
                    self.config.get('retry_delay', 2),
                    self.config.get('retry_on_empty', False),
                    check_cancel
                )
                
                result['audio'] = audio_data
                result['model'] = model_info
                result['stats'] = stats
                
            except Exception as e:
                result['error'] = str(e)
                
            return result

        # 5. Start Processing Loop
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {executor.submit(process_item, item): item for item in work_items}
            
            for future in concurrent.futures.as_completed(future_to_item):
                if self.is_cancelled:
                    break

                try:
                    res = future.result()
                    if not res: continue

                    item = res['item']
                    stats = res.get('stats', {})
                    
                    if stats:
                        self.total_input_tokens += stats.get('input_tokens', 0)
                        self.total_output_tokens += stats.get('output_tokens', 0)
                        if res['audio']:
                            self.total_requests += 1
                        self.usage_update.emit(self.total_input_tokens, self.total_output_tokens)
                    
                    if res['audio']:
                        def save_audio_to_note():
                            try:
                                filename = f"{svc_prefix}_tts_{item['nid']}_{int(time.time()*1000)}.wav"
                                mw.col.media.write_data(filename, res['audio'])
                                
                                n = mw.col.get_note(item['nid'])
                                n[item['tgt_field']] = f"[sound:{filename}]"
                                if tag: n.add_tag(tag)
                                mw.col.update_note(n)
                                return True, None
                            except Exception as e:
                                return False, str(e)

                        saved, save_err = self._run_on_main_sync(save_audio_to_note)
                        
                        if saved:
                            self.success_ops += 1
                            self.log_html_update.emit(
                                f"Note {item['nid']} ({item['src_field']}): "
                                f"<span style='color:green; font-weight:bold'>Success ({res['model']})</span>"
                            )
                        else:
                            self.failed_ops += 1
                            self.log_html_update.emit(f"<span style='color:red'>Note {item['nid']}: Save Error - {save_err}</span>")
                    
                    else:
                        self.failed_ops += 1
                        err_msg = res.get('error') or res.get('model') or "Unknown Error"
                        display_err = self._format_error(err_msg)
                        self.log_html_update.emit(f"Note {item['nid']} ({item['src_field']}): <span style='color:red'>{display_err}</span>")

                except Exception as exc:
                    self.failed_ops += 1
                    self.log_html_update.emit(f"<span style='color:red'>Worker Exception: {str(exc)}</span>")
                
                self.processed_count += 1
                self.progress_update.emit(self.processed_count, "Processing...", self.success_ops, self.failed_ops, self.skipped_ops)

        # 6. Finalize
        summary = f"<br><b>Processing Complete!</b><br>"
        summary += f"<span style='color:green'>Success: {self.success_ops}</span><br>"
        summary += f"<span style='color:gray'>Skipped: {self.skipped_ops}</span><br>"
        summary += f"<span style='color:red'>Failed: {self.failed_ops}</span><br>"
        summary += f"<i>Session Usage: Input {self.total_input_tokens}, Output {self.total_output_tokens}</i>"
        
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
            'service': 'gemini',
            'api_key': '',
            'primary_model': 'gemini-2.5-flash-tts',
            'fallback_model': 'gemini-2.5-flash-tts',
            'enable_fallback': True,
            'voice_name': 'Zephyr',
            'language_code': '',
            'temperature': 1.0,
            'request_wait': 0.5,
            'max_concurrent': 1,
            'retry_on_empty': False,
            'verbose_logging': False,
            'tag_on_success': '',
            'note_type_configs': [],
            'stats': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0},
            'elevenlabs': {
                'api_key': '',
                'voice_id': 'JBFqnCBsd6RMkjVDRZzb', 
                'model_id': 'eleven_turbo_v2_5',
                'stability': 0.5,
                'similarity_boost': 0.75,
                'speed': 1.0,
                'language_code': ''
            }
        }
    
    def validate_config(self):
        service = self.active_config.get('service', 'gemini')
        if service == 'elevenlabs':
            el_cfg = self.active_config.get('elevenlabs', {})
            return bool(el_cfg.get('api_key')) and bool(self.active_config.get('note_type_configs'))
        else:
            return bool(self.active_config.get('api_key')) and bool(self.active_config.get('note_type_configs'))

    def start(self):
        if not self.validate_config():
            dialog = ConfigDialog(self.mw, self.global_config)
            if dialog.exec():
                self.global_config = dialog.get_config()
                self.mw.addonManager.writeConfig(__name__, self.global_config)
                self.__init__(self.mw, self.note_ids)
                if not self.validate_config(): return 
            else:
                return
        
        service = self.active_config.get('service', 'gemini')
        el_config = self.active_config.get('elevenlabs', {})

        processor = TTSProcessor(
            service=service,
            api_key=self.active_config['api_key'],
            voice_name=self.active_config.get('voice_name', 'Zephyr'),
            language_code=self.active_config.get('language_code', ''),
            temperature=self.active_config.get('temperature', 1.0),
            system_instruction=self.active_config.get('system_instruction', ''),
            elevenlabs_api_key=el_config.get('api_key', ''),
            elevenlabs_voice_id=el_config.get('voice_id', ''),
            elevenlabs_model=el_config.get('model_id', 'eleven_turbo_v2_5'),
            elevenlabs_speed=el_config.get('speed', 1.0),
            elevenlabs_language_code=el_config.get('language_code', '')
        )
        
        # Initialize dialog with estimated note count first
        self.dialog = ProgressDialog(self.mw, len(self.note_ids))
        self.dialog.cancel_btn.clicked.connect(self.on_cancel)
        self.dialog.handler_ref = self 
        self.dialog.show()
        
        self.worker = TTSWorker(self.note_ids, self.active_config, processor)
        
        # Connect signals
        self.worker.progress_update.connect(self.dialog.update_progress)
        self.worker.max_update.connect(self.dialog.progress_bar.setMaximum) # Correctly update Range
        self.worker.usage_update.connect(self.dialog.update_usage)
        self.worker.log_html_update.connect(self.dialog.add_log_html)
        self.worker.finished_signal.connect(self.on_finished)
        
        self.worker.start()
        
    def on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.is_cancelled = True
            self.dialog.cancel_btn.setEnabled(False)
            self.dialog.status_label.setText("Cancelling...")
            
    def on_finished(self, summary, session_stats):
        self.dialog.add_log_html(summary)
        self.dialog.status_label.setText("Done")
        
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