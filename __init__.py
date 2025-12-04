"""
Gemini TTS Batch Addon for Anki
"""

import os
import sys

# --- LIBS PATH FIX ---
addon_dir = os.path.dirname(__file__)
libs_dir = os.path.join(addon_dir, 'libs')
if libs_dir not in sys.path:
    sys.path.insert(0, libs_dir)
# ---------------------

from aqt import mw, gui_hooks
from aqt.qt import QAction
from aqt.utils import showInfo
from .batch_handler import BatchTTSHandler
from .config_dialog import ConfigDialog

def get_config():
    """Helper to get config"""
    config = mw.addonManager.getConfig(__name__)
    if not config:
        config = {}
    return config

def get_active_api_key(config):
    """Helper to find API key regardless of config structure (Flat vs Profiles)"""
    if 'profiles' in config:
        # New Profile Structure
        current = config.get('current_profile', 'Default')
        profile = config['profiles'].get(current, {})
        return profile.get('api_key')
    else:
        # Old Flat Structure
        return config.get('api_key')

def on_open_settings():
    """Opened from Tools -> Gemini TTS Configuration"""
    config = get_config()
    
    # Open the configuration dialog
    dialog = ConfigDialog(mw, config)
    if dialog.exec():
        # Save changes if user clicked OK
        new_config = dialog.get_config()
        mw.addonManager.writeConfig(__name__, new_config)

def on_batch_tts(browser):
    """Opened from Browser -> Notes -> Add Gemini TTS"""
    # 1. Validate selection
    selected = browser.selectedNotes()
    if not selected:
        showInfo("Please select at least one note.", parent=browser)
        return

    # 2. Check if API key is set
    config = get_config()
    api_key = get_active_api_key(config)
    
    if not api_key:
        showInfo("Please configure your API Key in 'Tools > Gemini TTS Configuration' first.", parent=browser)
        return

    # 3. Start processing
    handler = BatchTTSHandler(mw, selected)
    handler.start()

def setup_browser_menu(browser):
    """Add menu entry to the Browser's 'Notes' menu"""
    action = QAction("Add Gemini TTS to Selected", browser)
    action.triggered.connect(lambda: on_batch_tts(browser))
    
    # Add to the "Notes" dropdown menu in the browser
    # We try to add it after "Add Tags" or similar, or just append
    browser.form.menu_Notes.addSeparator()
    browser.form.menu_Notes.addAction(action)

def setup_main_menu():
    """Add menu entry to the Main Window's 'Tools' menu"""
    action = QAction("Gemini TTS Configuration", mw)
    action.triggered.connect(on_open_settings)
    mw.form.menuTools.addAction(action)

# 1. Setup Main Window Menu (Configuration)
setup_main_menu()

# 2. Setup Browser Menu (Batch Processing)
gui_hooks.browser_menus_did_init.append(setup_browser_menu)