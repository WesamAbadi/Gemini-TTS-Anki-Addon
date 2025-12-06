from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                     QPushButton, QComboBox, QCheckBox, QGroupBox, QFormLayout,
                     QListWidget, QListWidgetItem, QDialogButtonBox, QSpinBox,
                     QDoubleSpinBox, QTabWidget, QWidget, QTextEdit, QMessageBox, QInputDialog)
from aqt.utils import showInfo, askUser
from aqt import mw

class NoteTypeConfigDialog(QDialog):
    """Dialog for configuring field mappings for a note type"""
    
    def __init__(self, parent, note_type_name, existing_config=None):
        super().__init__(parent)
        self.note_type_name = note_type_name
        self.config = existing_config or {}
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle(f"Configure: {self.note_type_name}")
        layout = QVBoxLayout()
        
        # Get fields
        model = mw.col.models.by_name(self.note_type_name)
        if not model:
            showInfo(f"Note type '{self.note_type_name}' not found")
            self.reject()
            return
            
        fields = [f['name'] for f in model['flds']]
        
        # Enable Checkbox
        self.enabled_chk = QCheckBox("Enable this mapping")
        self.enabled_chk.setChecked(self.config.get('enabled', True))
        layout.addWidget(self.enabled_chk)
        
        # Source field
        form = QFormLayout()
        self.source_field = QComboBox()
        self.source_field.addItems(fields)
        if self.config.get('source_field'):
            idx = self.source_field.findText(self.config['source_field'])
            if idx >= 0:
                self.source_field.setCurrentIndex(idx)
        form.addRow("Source Text Field:", self.source_field)
        
        # Target field
        self.target_field = QComboBox()
        self.target_field.addItems(fields)
        if self.config.get('target_field'):
            idx = self.target_field.findText(self.config['target_field'])
            if idx >= 0:
                self.target_field.setCurrentIndex(idx)
        form.addRow("Target Audio Field:", self.target_field)
        
        layout.addLayout(form)
        
        # Buttons
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
            'api_key': '',
            'primary_model': 'gemini-2.5-flash-tts',
            'fallback_model': 'gemini-2.5-flash-tts',
            'enable_fallback': True,
            'voice_name': 'Zephyr',
            'temperature': 1.0,
            'system_instruction': '',
            'note_type_configs': [],
            'skip_existing_audio': True,
            'retry_attempts': 3,
            'retry_delay': 2,
            'request_wait': 0.5,
            'tag_on_success': '',
            'stats': {'requests': 0, 'input_tokens': 0, 'output_tokens': 0}
        }
        
    def setup_ui(self):
        self.setWindowTitle("Gemini TTS Configuration")
        self.setMinimumWidth(600)
        self.setMinimumHeight(550)
        
        main_layout = QVBoxLayout()
        
        # --- Profile Management Section ---
        profile_group = QGroupBox("Profiles")
        profile_layout = QHBoxLayout()
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(sorted(self.profiles.keys()))
        self.profile_combo.setCurrentText(self.current_profile_name)
        self.profile_combo.currentTextChanged.connect(self.on_profile_change)
        
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(30)
        add_btn.clicked.connect(self.add_profile)
        
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self.rename_profile)
        
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_profile)
        
        profile_layout.addWidget(QLabel("Current Profile:"))
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(add_btn)
        profile_layout.addWidget(rename_btn)
        profile_layout.addWidget(del_btn)
        
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group)

        # --- Tabs ---
        self.tabs = QTabWidget()
        
        self.tab_api = QWidget()
        self.setup_api_tab()
        self.tabs.addTab(self.tab_api, "API & Voice")
        
        self.tab_notes = QWidget()
        self.setup_notes_tab()
        self.tabs.addTab(self.tab_notes, "Note Mappings")
        
        self.tab_proc = QWidget()
        self.setup_proc_tab()
        self.tabs.addTab(self.tab_proc, "Processing & Stats")
        
        main_layout.addWidget(self.tabs)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        
        self.setLayout(main_layout)

    def setup_api_tab(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal) # Changed from Password
        self.api_key.setPlaceholderText("Enter your Gemini API Key")
        form.addRow("Gemini API Key:", self.api_key)
        
        self.primary_model = QLineEdit()
        form.addRow("Primary Model:", self.primary_model)
        
        self.fallback_model = QLineEdit()
        form.addRow("Fallback Model:", self.fallback_model)
        
        self.enable_fallback = QCheckBox("Enable fallback on rate limit")
        form.addRow("", self.enable_fallback)
        
        self.voice_name = QLineEdit()
        form.addRow("Voice Name:", self.voice_name)
        
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        form.addRow("Temperature:", self.temperature)
        
        layout.addLayout(form)
        
        layout.addWidget(QLabel("System Instructions (Optional):"))
        self.system_instruction = QTextEdit()
        self.system_instruction.setPlaceholderText("E.g., Speak slowly and clearly.")
        self.system_instruction.setMaximumHeight(80)
        layout.addWidget(self.system_instruction)
        
        layout.addStretch()
        self.tab_api.setLayout(layout)

    def setup_notes_tab(self):
        layout = QVBoxLayout()
        
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
        
        group_sets = QGroupBox("Batch Settings")
        form = QFormLayout()
        
        self.skip_existing = QCheckBox("Skip notes with existing audio")
        form.addRow("", self.skip_existing)
        
        self.request_wait = QDoubleSpinBox()
        self.request_wait.setRange(0.0, 10.0)
        self.request_wait.setSingleStep(0.1)
        self.request_wait.setSuffix(" sec")
        form.addRow("Delay between requests:", self.request_wait)
        
        self.tag_on_success = QLineEdit()
        self.tag_on_success.setPlaceholderText("Optional (e.g., tts_generated)")
        form.addRow("Tag note on success:", self.tag_on_success)
        
        self.retry_attempts = QSpinBox()
        self.retry_attempts.setRange(1, 10)
        form.addRow("Retry Attempts:", self.retry_attempts)
        
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(1, 30)
        form.addRow("Retry Delay (sec):", self.retry_delay)
        
        group_sets.setLayout(form)
        layout.addWidget(group_sets)
        
        group_stats = QGroupBox("Profile Statistics")
        stats_layout = QFormLayout()
        self.stat_requests = QLabel("0")
        self.stat_input = QLabel("0")
        self.stat_output = QLabel("0")
        stats_layout.addRow("Total Requests:", self.stat_requests)
        stats_layout.addRow("Input Tokens:", self.stat_input)
        stats_layout.addRow("Output Tokens:", self.stat_output)
        group_stats.setLayout(stats_layout)
        layout.addWidget(group_stats)
        
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

        self.profiles[self.current_profile_name] = {
            'api_key': self.api_key.text(),
            'primary_model': self.primary_model.text(),
            'fallback_model': self.fallback_model.text(),
            'enable_fallback': self.enable_fallback.isChecked(),
            'voice_name': self.voice_name.text(),
            'temperature': self.temperature.value(),
            'system_instruction': self.system_instruction.toPlainText(),
            'note_type_configs': note_configs,
            'skip_existing_audio': self.skip_existing.isChecked(),
            'retry_attempts': self.retry_attempts.value(),
            'retry_delay': self.retry_delay.value(),
            'request_wait': self.request_wait.value(),
            'tag_on_success': self.tag_on_success.text(),
            'stats': current_stats
        }

    def load_profile(self, name):
        p = self.profiles.get(name, self.get_default_profile())
        
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentText(name)
        self.profile_combo.blockSignals(False)
        
        self.api_key.setText(p.get('api_key', ''))
        self.primary_model.setText(p.get('primary_model', 'gemini-2.5-flash-tts'))
        self.fallback_model.setText(p.get('fallback_model', 'gemini-2.5-flash-tts'))
        self.enable_fallback.setChecked(p.get('enable_fallback', True))
        self.voice_name.setText(p.get('voice_name', 'Zephyr'))
        self.temperature.setValue(p.get('temperature', 1.0))
        self.system_instruction.setText(p.get('system_instruction', ''))
        
        self.skip_existing.setChecked(p.get('skip_existing_audio', True))
        self.retry_attempts.setValue(p.get('retry_attempts', 3))
        self.retry_delay.setValue(p.get('retry_delay', 2))
        self.request_wait.setValue(p.get('request_wait', 0.5))
        self.tag_on_success.setText(p.get('tag_on_success', ''))
        
        stats = p.get('stats', {'requests': 0, 'input_tokens': 0, 'output_tokens': 0})
        self.stat_requests.setText(str(stats.get('requests', 0)))
        self.stat_input.setText(str(stats.get('input_tokens', 0)))
        self.stat_output.setText(str(stats.get('output_tokens', 0)))
        
        self.note_configs.clear()
        for cfg in p.get('note_type_configs', []):
            self.add_config_item(cfg)

    def add_config_item(self, cfg):
        status = "[ON] " if cfg.get('enabled', True) else "[OFF] "
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
                showInfo("Profile already exists")
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
            if new_name in self.profiles:
                showInfo("Name taken")
                return
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
        if len(self.profiles) <= 1:
            showInfo("Cannot delete last profile")
            return
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
            status = "[ON] " if new_cfg.get('enabled', True) else "[OFF] "
            item_text = f"{status}{new_cfg['note_type']}: {new_cfg['source_field']} → {new_cfg['target_field']}"
            current.setText(item_text)
            if not new_cfg.get('enabled', True):
                current.setForeground(Qt.GlobalColor.gray)
            else:
                current.setForeground(Qt.GlobalColor.black) # Reset color
            current.setData(0x0100, new_cfg)
            
    def remove_note_config(self):
        current = self.note_configs.currentItem()
        if current:
            self.note_configs.takeItem(self.note_configs.row(current))

    def get_config(self):
        self.save_current_ui_to_memory()
        return {
            'current_profile': self.current_profile_name,
            'profiles': self.profiles
        }