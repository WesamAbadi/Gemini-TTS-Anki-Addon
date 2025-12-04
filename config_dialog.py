"""
Configuration Dialog for Gemini TTS Addon
"""

from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                     QPushButton, QComboBox, QCheckBox, QGroupBox, QFormLayout,
                     QListWidget, QListWidgetItem, QDialogButtonBox, QSpinBox,
                     QDoubleSpinBox)
from aqt.utils import showInfo
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
        
        # Get fields for this note type
        model = mw.col.models.by_name(self.note_type_name)
        if not model:
            showInfo(f"Note type '{self.note_type_name}' not found")
            self.reject()
            return
            
        fields = [f['name'] for f in model['flds']]
        
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
            'target_field': self.target_field.currentText()
        }


class ConfigDialog(QDialog):
    """Main configuration dialog for the addon"""
    
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Gemini TTS Configuration")
        self.setMinimumWidth(500)
        layout = QVBoxLayout()
        
        # API Settings
        api_group = QGroupBox("API Settings")
        api_layout = QFormLayout()
        
        self.api_key = QLineEdit(self.config.get('api_key', ''))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addRow("Gemini API Key:", self.api_key)
        
        self.primary_model = QLineEdit(self.config.get('primary_model', 
                                                       'gemini-2.5-pro-preview-tts'))
        api_layout.addRow("Primary Model:", self.primary_model)
        
        self.fallback_model = QLineEdit(self.config.get('fallback_model',
                                                        'gemini-2.5-flash-preview-tts'))
        api_layout.addRow("Fallback Model:", self.fallback_model)
        
        self.enable_fallback = QCheckBox("Enable fallback on rate limit")
        self.enable_fallback.setChecked(self.config.get('enable_fallback', True))
        api_layout.addRow("", self.enable_fallback)
        
        self.voice_name = QLineEdit(self.config.get('voice_name', 'Zephyr'))
        api_layout.addRow("Voice Name:", self.voice_name)
        
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(self.config.get('temperature', 1.0))
        api_layout.addRow("Temperature:", self.temperature)
        
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        # Processing Settings
        proc_group = QGroupBox("Processing Settings")
        proc_layout = QFormLayout()
        
        self.skip_existing = QCheckBox("Skip notes with existing audio")
        self.skip_existing.setChecked(self.config.get('skip_existing_audio', True))
        proc_layout.addRow("", self.skip_existing)
        
        self.retry_attempts = QSpinBox()
        self.retry_attempts.setRange(1, 10)
        self.retry_attempts.setValue(self.config.get('retry_attempts', 3))
        proc_layout.addRow("Retry Attempts:", self.retry_attempts)
        
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(1, 30)
        self.retry_delay.setValue(self.config.get('retry_delay', 2))
        proc_layout.addRow("Retry Delay (sec):", self.retry_delay)
        
        proc_group.setLayout(proc_layout)
        layout.addWidget(proc_group)
        
        # Note Type Configurations
        note_group = QGroupBox("Note Type Field Mappings")
        note_layout = QVBoxLayout()
        
        self.note_configs = QListWidget()
        self.load_note_configs()
        note_layout.addWidget(self.note_configs)
        
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
        note_layout.addLayout(btn_layout)
        
        note_group.setLayout(note_layout)
        layout.addWidget(note_group)
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        
    def load_note_configs(self):
        self.note_configs.clear()
        for cfg in self.config.get('note_type_configs', []):
            item_text = f"{cfg['note_type']}: {cfg['source_field']} → {cfg['target_field']}"
            item = QListWidgetItem(item_text)
            item.setData(0x0100, cfg)  # Qt.UserRole
            self.note_configs.addItem(item)
            
    def add_note_config(self):
        # Get all note types
        note_types = [m['name'] for m in mw.col.models.all()]
        if not note_types:
            showInfo("No note types found")
            return
            
        # For simplicity, use first note type or let user choose
        from aqt.qt import QInputDialog
        note_type, ok = QInputDialog.getItem(self, "Select Note Type",
                                             "Choose note type:", note_types, 0, False)
        if not ok:
            return
            
        dialog = NoteTypeConfigDialog(self, note_type)
        if dialog.exec():
            cfg = dialog.get_config()
            item_text = f"{cfg['note_type']}: {cfg['source_field']} → {cfg['target_field']}"
            item = QListWidgetItem(item_text)
            item.setData(0x0100, cfg)
            self.note_configs.addItem(item)
            
    def edit_note_config(self):
        current = self.note_configs.currentItem()
        if not current:
            showInfo("Please select a mapping to edit")
            return
            
        cfg = current.data(0x0100)
        dialog = NoteTypeConfigDialog(self, cfg['note_type'], cfg)
        if dialog.exec():
            new_cfg = dialog.get_config()
            item_text = f"{new_cfg['note_type']}: {new_cfg['source_field']} → {new_cfg['target_field']}"
            current.setText(item_text)
            current.setData(0x0100, new_cfg)
            
    def remove_note_config(self):
        current = self.note_configs.currentItem()
        if current:
            self.note_configs.takeItem(self.note_configs.row(current))
            
    def get_config(self):
        """Return updated configuration"""
        note_configs = []
        for i in range(self.note_configs.count()):
            item = self.note_configs.item(i)
            note_configs.append(item.data(0x0100))
            
        return {
            'api_key': self.api_key.text(),
            'primary_model': self.primary_model.text(),
            'fallback_model': self.fallback_model.text(),
            'enable_fallback': self.enable_fallback.isChecked(),
            'voice_name': self.voice_name.text(),
            'temperature': self.temperature.value(),
            'note_type_configs': note_configs,
            'skip_existing_audio': self.skip_existing.isChecked(),
            'retry_attempts': self.retry_attempts.value(),
            'retry_delay': self.retry_delay.value()
        }
