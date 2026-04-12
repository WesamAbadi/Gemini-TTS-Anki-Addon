from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                     QPushButton, QComboBox, QCheckBox, QGroupBox, QFormLayout,
                     QListWidget, QListWidgetItem, QDialogButtonBox, QSpinBox,
                     QDoubleSpinBox, QTabWidget, QWidget, QTextEdit, QMessageBox, 
                     QInputDialog, Qt, QCursor, QDesktopServices, QUrl)
from aqt.utils import showInfo, askUser
from aqt import mw

# --- Helper UI Components ---

class HelpLabel(QLabel):
    """Clickable label that opens a URL"""
    def __init__(self, text, url, parent=None):
        super().__init__(text, parent)
        self.url = url
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("color: #2196F3; text-decoration: underline; margin-left: 5px;")
        self.setToolTip(f"Open {url}")

    def mousePressEvent(self, event):
        QDesktopServices.openUrl(QUrl(self.url))

class SectionHeader(QLabel):
    """Styled header for sections"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("font-weight: bold; font-size: 12px; color: #555; margin-top: 10px; margin-bottom: 5px;")

# --- Dialogs ---

class NoteTypeConfigDialog(QDialog):
    """Dialog for configuring field mappings for a note type"""
    
    def __init__(self, parent, note_type_name, existing_config=None):
        super().__init__(parent)
        self.note_type_name = note_type_name
        self.config = existing_config or {}
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle(f"Mapping: {self.note_type_name}")
        self.setMinimumWidth(400)
        layout = QVBoxLayout()
        
        model = mw.col.models.by_name(self.note_type_name)
        if not model:
            showInfo(f"Note type '{self.note_type_name}' not found")
            self.reject()
            return
            
        fields = [f['name'] for f in model['flds']]
        
        self.enabled_chk = QCheckBox("Enable this mapping")
        self.enabled_chk.setChecked(self.config.get('enabled', True))
        layout.addWidget(self.enabled_chk)
        
        form = QFormLayout()
        self.source_field = QComboBox()
        self.source_field.addItems(fields)
        if self.config.get('source_field'):
            idx = self.source_field.findText(self.config['source_field'])
            if idx >= 0: self.source_field.setCurrentIndex(idx)
        form.addRow("Source (Text):", self.source_field)
        
        self.target_field = QComboBox()
        self.target_field.addItems(fields)
        if self.config.get('target_field'):
            idx = self.target_field.findText(self.config['target_field'])
            if idx >= 0: self.target_field.setCurrentIndex(idx)
        form.addRow("Target (Audio):", self.target_field)
        
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)
        
    def get_config(self):
        return {
            'note_type': self.note_type_name,
            'source_field': self.source_field.currentText(),
            'target_field': self.target_field.currentText(),
            'enabled': self.enabled_chk.isChecked()
        }


class ConfigDialog(QDialog):
    """Main configuration dialog with Profiles support"""
    
    def __init__(self, parent, global_config):
        super().__init__(parent)
        self.global_config = global_config
        
        if 'profiles' not in self.global_config:
            self.global_config = {
                'current_profile': 'Default',
                'profiles': {'Default': self.global_config}
            }
            
        self.current_profile_name = self.global_config.get('current_profile', 'Default')
        self.profiles = self.global_config.get('profiles', {})
        
        if not self.profiles:
            self.profiles['Default'] = self.get_default_profile()
            self.current_profile_name = 'Default'

        self.setup_ui()
        self.load_profile(self.current_profile_name)
        
    def get_default_profile(self):
        return {
            'service': 'gemini',
            'api_key': '',
            'primary_model': 'gemini-2.5-flash-tts',
            'fallback_model': 'gemini-2.5-flash-tts',
            'enable_fallback': True,
            'voice_name': 'Zephyr',
            'language_code': '',
            'temperature': 1.0,
            'system_instruction': '',
            'elevenlabs': {
                'api_key': '',
                'voice_id': 'JBFqnCBsd6RMkjVDRZzb',
                'model_id': 'eleven_turbo_v2_5',
                'stability': 0.5,
                'similarity_boost': 0.75,
                'speed': 1.0,
                'language_code': ''
            },
            'note_type_configs': [],
            'skip_existing_audio': True,
            'retry_attempts': 3,
            'retry_delay': 2,
            'request_wait': 0.5,
            'max_concurrent': 1,
            'tag_on_success': '',
            'retry_on_empty': False,
            'verbose_logging': False,
            'stats': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
        }
        
    def setup_ui(self):
        self.setWindowTitle("Batch TTS Configuration")
        self.setMinimumWidth(650)
        self.setMinimumHeight(600)
        
        main_layout = QVBoxLayout()
        
        # Profile Header
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Profile:"))
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(sorted(self.profiles.keys()))
        self.profile_combo.setCurrentText(self.current_profile_name)
        self.profile_combo.currentTextChanged.connect(self.on_profile_change)
        top_bar.addWidget(self.profile_combo, 1)
        
        btn_style = "QPushButton { padding: 3px 8px; }"
        add_btn = QPushButton("+")
        add_btn.setStyleSheet(btn_style)
        add_btn.clicked.connect(self.add_profile)
        
        rename_btn = QPushButton("Rename")
        rename_btn.setStyleSheet(btn_style)
        rename_btn.clicked.connect(self.rename_profile)
        
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(btn_style)
        del_btn.clicked.connect(self.delete_profile)
        
        top_bar.addWidget(add_btn)
        top_bar.addWidget(rename_btn)
        top_bar.addWidget(del_btn)
        
        main_layout.addLayout(top_bar)
        main_layout.addSpacing(10)

        # Tabs
        self.tabs = QTabWidget()
        
        self.tab_api = QWidget()
        self.setup_api_tab()
        self.tabs.addTab(self.tab_api, "Service & API")
        
        self.tab_notes = QWidget()
        self.setup_notes_tab()
        self.tabs.addTab(self.tab_notes, "Note Mappings")
        
        self.tab_proc = QWidget()
        self.setup_proc_tab()
        self.tabs.addTab(self.tab_proc, "Performance & Settings")
        
        main_layout.addWidget(self.tabs)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        self.setLayout(main_layout)

    def _create_info_row(self, label_text, widget, help_url=None, help_text="Get Info"):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setMinimumWidth(100)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        if help_url:
            row.addWidget(HelpLabel(help_text, help_url))
        return row

    def setup_api_tab(self):
        layout = QVBoxLayout()
        
        # Service Selector
        top_h = QHBoxLayout()
        top_h.addWidget(QLabel("<b>TTS Service:</b>"))
        self.service_combo = QComboBox()
        self.service_combo.addItems(["Gemini", "ElevenLabs"])
        self.service_combo.currentTextChanged.connect(self.on_service_change)
        top_h.addWidget(self.service_combo, 1)
        layout.addLayout(top_h)
        layout.addSpacing(15)
        
        # --- GEMINI SETTINGS ---
        self.gemini_group = QWidget()
        g_layout = QVBoxLayout(self.gemini_group)
        g_layout.setContentsMargins(0,0,0,0)
        
        g_layout.addWidget(SectionHeader("Credentials"))
        
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal)
        self.api_key.setPlaceholderText("Enter Gemini API Key")
        g_layout.addLayout(self._create_info_row("API Key:", self.api_key, "https://aistudio.google.com/app/apikey", "(?) Get Key"))
        
        g_layout.addWidget(SectionHeader("Models & Voice"))
        
        self.primary_model = QLineEdit()
        g_layout.addLayout(self._create_info_row("Primary Model:", self.primary_model, "https://ai.google.dev/gemini-api/docs/models/gemini", "(?) Models"))
        
        self.fallback_model = QLineEdit()
        g_layout.addLayout(self._create_info_row("Fallback Model:", self.fallback_model))
        
        self.enable_fallback = QCheckBox("Enable fallback on rate limit (429)")
        g_layout.addWidget(self.enable_fallback)
        
        self.voice_name = QLineEdit()
        g_layout.addLayout(self._create_info_row("Voice Name:", self.voice_name))

        self.language_code = QLineEdit()
        self.language_code.setPlaceholderText("e.g. en-US")
        g_layout.addLayout(self._create_info_row("Language Code:", self.language_code))
        
        g_layout.addWidget(SectionHeader("Generation Parameters"))
        
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        g_layout.addLayout(self._create_info_row("Temperature:", self.temperature))

        self.system_instruction = QTextEdit()
        self.system_instruction.setPlaceholderText("E.g., Speak slowly. Pronounce clearly.")
        self.system_instruction.setMaximumHeight(60)
        g_layout.addWidget(QLabel("System Instructions:"))
        g_layout.addWidget(self.system_instruction)
        
        layout.addWidget(self.gemini_group)
        
        # --- ELEVENLABS SETTINGS ---
        self.eleven_group = QWidget()
        e_layout = QVBoxLayout(self.eleven_group)
        e_layout.setContentsMargins(0,0,0,0)
        
        e_layout.addWidget(SectionHeader("Credentials"))
        
        self.el_api_key = QLineEdit()
        self.el_api_key.setPlaceholderText("Enter ElevenLabs API Key")
        e_layout.addLayout(self._create_info_row("API Key:", self.el_api_key, "https://elevenlabs.io/app/settings/api-keys", "(?) Get Key"))
        
        e_layout.addWidget(SectionHeader("Voice Configuration"))

        self.el_voice_id = QLineEdit()
        self.el_voice_id.setPlaceholderText("e.g. 21m00Tcm4TlvDq8ikWAM")
        e_layout.addLayout(self._create_info_row("Voice ID:", self.el_voice_id, "https://elevenlabs.io/app/voice-lab", "(?) Voices"))
        
        self.el_model_id = QLineEdit()
        self.el_model_id.setPlaceholderText("e.g. eleven_turbo_v2_5")
        e_layout.addLayout(self._create_info_row("Model ID:", self.el_model_id, "https://elevenlabs.io/docs/api-reference/text-to-speech/convert", "(?) Models"))
        
        self.el_language_code = QLineEdit()
        self.el_language_code.setPlaceholderText("e.g. en")
        e_layout.addLayout(self._create_info_row("Language Code:", self.el_language_code))

        self.el_speed = QDoubleSpinBox()
        self.el_speed.setRange(0.7, 1.2)
        self.el_speed.setSingleStep(0.1)
        e_layout.addLayout(self._create_info_row("Speed:", self.el_speed))
        
        layout.addWidget(self.eleven_group)
        
        layout.addStretch()
        self.tab_api.setLayout(layout)

    def on_service_change(self, service_name):
        is_gemini = (service_name == "Gemini")
        self.gemini_group.setVisible(is_gemini)
        self.eleven_group.setVisible(not is_gemini)

    def setup_notes_tab(self):
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Map Source Text fields to Target Audio fields per Note Type."))
        
        self.note_configs = QListWidget()
        layout.addWidget(self.note_configs)
        
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Mapping")
        add_btn.clicked.connect(self.add_note_config)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self.edit_note_config)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_note_config)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(remove_btn)
        layout.addLayout(btn_layout)
        self.tab_notes.setLayout(layout)

    def setup_proc_tab(self):
        layout = QVBoxLayout()
        
        # Performance Settings
        layout.addWidget(SectionHeader("Performance & Concurrency"))
        
        perf_form = QFormLayout()
        
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 10)
        self.max_concurrent.setToolTip("Higher values are faster but may hit rate limits sooner.")
        perf_form.addRow("Max Concurrent Requests:", self.max_concurrent)
        
        self.request_wait = QDoubleSpinBox()
        self.request_wait.setRange(0.0, 10.0)
        self.request_wait.setSingleStep(0.1)
        self.request_wait.setSuffix(" sec")
        perf_form.addRow("Delay after request:", self.request_wait)
        
        layout.addLayout(perf_form)
        
        # Batch Logic
        layout.addWidget(SectionHeader("Batch Processing Logic"))
        
        self.skip_existing = QCheckBox("Skip notes with existing audio in target field")
        layout.addWidget(self.skip_existing)
        
        self.retry_on_empty = QCheckBox("Retry on 'No audio generated' error")
        layout.addWidget(self.retry_on_empty)

        self.verbose_logging = QCheckBox("Verbose logging (show skipped notes)")
        layout.addWidget(self.verbose_logging)

        logic_form = QFormLayout()
        self.tag_on_success = QLineEdit()
        self.tag_on_success.setPlaceholderText("Optional (e.g., tts_generated)")
        logic_form.addRow("Tag on Success:", self.tag_on_success)
        
        self.retry_attempts = QSpinBox()
        self.retry_attempts.setRange(1, 10)
        logic_form.addRow("Retry Attempts:", self.retry_attempts)
        
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(1, 30)
        logic_form.addRow("Retry Delay (sec):", self.retry_delay)
        
        layout.addLayout(logic_form)
        
        # Stats
        layout.addWidget(SectionHeader("Usage Statistics (This Profile)"))
        stats_layout = QFormLayout()
        self.stat_requests = QLabel("0")
        self.stat_input = QLabel("0")
        self.stat_output = QLabel("0")
        stats_layout.addRow("Total Requests:", self.stat_requests)
        stats_layout.addRow("Total Input (chars/tokens):", self.stat_input)
        stats_layout.addRow("Total Output:", self.stat_output)
        layout.addLayout(stats_layout)
        
        layout.addStretch()
        self.tab_proc.setLayout(layout)

    # --- Profile Logic ---
    def on_profile_change(self, new_name):
        if not new_name: return
        self.save_current_ui_to_memory()
        self.current_profile_name = new_name
        self.load_profile(new_name)

    def save_current_ui_to_memory(self):
        if self.current_profile_name not in self.profiles: return
        current_stats = self.profiles[self.current_profile_name].get('stats', {'requests': 0, 'input_tokens': 0, 'output_tokens': 0})
        
        note_configs = []
        for i in range(self.note_configs.count()):
            item = self.note_configs.item(i)
            note_configs.append(item.data(0x0100))

        # Save Gemini settings
        profile_data = {
            'service': self.service_combo.currentText().lower(),
            'api_key': self.api_key.text(),
            'primary_model': self.primary_model.text(),
            'fallback_model': self.fallback_model.text(),
            'enable_fallback': self.enable_fallback.isChecked(),
            'voice_name': self.voice_name.text(),
            'language_code': self.language_code.text(),
            'temperature': self.temperature.value(),
            'system_instruction': self.system_instruction.toPlainText(),
            'note_type_configs': note_configs,
            'skip_existing_audio': self.skip_existing.isChecked(),
            'retry_attempts': self.retry_attempts.value(),
            'retry_delay': self.retry_delay.value(),
            'request_wait': self.request_wait.value(),
            'max_concurrent': self.max_concurrent.value(),
            'tag_on_success': self.tag_on_success.text(),
            'retry_on_empty': self.retry_on_empty.isChecked(),
            'verbose_logging': self.verbose_logging.isChecked(),
            'stats': current_stats
        }

        # Save ElevenLabs settings
        profile_data['elevenlabs'] = {
            'api_key': self.el_api_key.text(),
            'voice_id': self.el_voice_id.text(),
            'model_id': self.el_model_id.text(),
            'stability': self.profiles[self.current_profile_name].get('elevenlabs', {}).get('stability', 0.5),
            'similarity_boost': self.profiles[self.current_profile_name].get('elevenlabs', {}).get('similarity_boost', 0.75),
            'speed': self.el_speed.value(),
            'language_code': self.el_language_code.text()
        }

        self.profiles[self.current_profile_name] = profile_data

    def load_profile(self, name):
        p = self.profiles.get(name, self.get_default_profile())
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentText(name)
        self.profile_combo.blockSignals(False)
        
        # Load Service
        svc = p.get('service', 'gemini').title()
        if svc not in ["Gemini", "Elevenlabs"]: svc = "Gemini"
        if svc == "Elevenlabs": svc = "ElevenLabs"
        
        self.service_combo.setCurrentText(svc)
        self.on_service_change(svc)
        
        # Load Gemini
        self.api_key.setText(p.get('api_key', ''))
        self.primary_model.setText(p.get('primary_model', 'gemini-2.5-flash-tts'))
        self.fallback_model.setText(p.get('fallback_model', 'gemini-2.5-flash-tts'))
        self.enable_fallback.setChecked(p.get('enable_fallback', True))
        self.voice_name.setText(p.get('voice_name', 'Zephyr'))
        self.language_code.setText(p.get('language_code', ''))
        self.temperature.setValue(p.get('temperature', 1.0))
        self.system_instruction.setText(p.get('system_instruction', ''))
        
        # Load ElevenLabs
        el = p.get('elevenlabs', {})
        self.el_api_key.setText(el.get('api_key', ''))
        self.el_voice_id.setText(el.get('voice_id', 'JBFqnCBsd6RMkjVDRZzb'))
        self.el_model_id.setText(el.get('model_id', 'eleven_turbo_v2_5'))
        self.el_language_code.setText(el.get('language_code', ''))
        self.el_speed.setValue(el.get('speed', 1.0))
        
        # Common
        self.skip_existing.setChecked(p.get('skip_existing_audio', True))
        self.retry_attempts.setValue(p.get('retry_attempts', 3))
        self.retry_delay.setValue(p.get('retry_delay', 2))
        self.request_wait.setValue(p.get('request_wait', 0.5))
        self.max_concurrent.setValue(p.get('max_concurrent', 1))
        self.tag_on_success.setText(p.get('tag_on_success', ''))
        self.retry_on_empty.setChecked(p.get('retry_on_empty', False))
        self.verbose_logging.setChecked(p.get('verbose_logging', False))
        
        stats = p.get('stats', {'requests': 0, 'input_tokens': 0, 'output_tokens': 0})
        self.stat_requests.setText(str(stats.get('requests', 0)))
        self.stat_input.setText(str(stats.get('input_tokens', 0)))
        self.stat_output.setText(str(stats.get('output_tokens', 0)))
        
        self.note_configs.clear()
        for cfg in p.get('note_type_configs', []):
            self.add_config_item(cfg)

    def add_config_item(self, cfg):
        status = "✅ " if cfg.get('enabled', True) else "❌ "
        item_text = f"{status}{cfg['note_type']}: {cfg['source_field']} → {cfg['target_field']}"
        item = QListWidgetItem(item_text)
        if not cfg.get('enabled', True):
            item.setForeground(Qt.GlobalColor.gray)
        item.setData(0x0100, cfg)
        self.note_configs.addItem(item)

    def add_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Profile Name:")
        if ok and name:
            if name in self.profiles:
                showInfo("Profile exists!")
                return
            self.save_current_ui_to_memory()
            new_profile = self.profiles[self.current_profile_name].copy()
            new_profile['stats'] = {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
            self.profiles[name] = new_profile
            self.profile_combo.addItem(name)
            self.on_profile_change(name)

    def rename_profile(self):
        current = self.current_profile_name
        new_name, ok = QInputDialog.getText(self, "Rename Profile", "New Name:", text=current)
        if ok and new_name and new_name != current:
            if new_name in self.profiles: return
            self.save_current_ui_to_memory()
            data = self.profiles.pop(current)
            self.profiles[new_name] = data
            self.current_profile_name = new_name
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItems(sorted(self.profiles.keys()))
            self.profile_combo.setCurrentText(new_name)
            self.profile_combo.blockSignals(False)

    def delete_profile(self):
        if len(self.profiles) <= 1: return
        if askUser(f"Delete '{self.current_profile_name}'?"):
            del self.profiles[self.current_profile_name]
            new_name = sorted(self.profiles.keys())[0]
            self.on_profile_change(new_name)
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItems(sorted(self.profiles.keys()))
            self.profile_combo.setCurrentText(new_name)
            self.profile_combo.blockSignals(False)

    # --- Note Config Helpers ---
    def add_note_config(self):
        note_types = [m['name'] for m in mw.col.models.all()]
        if not note_types: return
        note_type, ok = QInputDialog.getItem(self, "Select Note Type", "Type:", note_types, 0, False)
        if not ok: return
        dialog = NoteTypeConfigDialog(self, note_type)
        if dialog.exec():
            self.add_config_item(dialog.get_config())
            
    def edit_note_config(self):
        current = self.note_configs.currentItem()
        if not current: return
        cfg = current.data(0x0100)
        dialog = NoteTypeConfigDialog(self, cfg['note_type'], cfg)
        if dialog.exec():
            new_cfg = dialog.get_config()
            status = "✅ " if new_cfg.get('enabled', True) else "❌ "
            item_text = f"{status}{new_cfg['note_type']}: {new_cfg['source_field']} → {new_cfg['target_field']}"
            current.setText(item_text)
            if not new_cfg.get('enabled', True):
                current.setForeground(Qt.GlobalColor.gray)
            else:
                current.setForeground(Qt.GlobalColor.black)
            current.setData(0x0100, new_cfg)
            
    def remove_note_config(self):
        current = self.note_configs.currentItem()
        if current: self.note_configs.takeItem(self.note_configs.row(current))

    def get_config(self):
        self.save_current_ui_to_memory()
        return {
            'current_profile': self.current_profile_name,
            'profiles': self.profiles
        }