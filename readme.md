# Gemini TTS Batch Addon for Anki

Batch add Text-to-Speech to Anki notes using Google Gemini API with automatic fallback handling.

## Features

- **Batch Processing**: Add TTS to multiple selected notes at once
- **Automatic Fallback**: Switches from `gemini-2.5-pro-preview-tts` to `gemini-2.5-flash-preview-tts` on rate limits
- **Field Mapping**: Configure source text field → target audio field per note type
- **Smart Skipping**: Skip notes that already have audio
- **Error Handling**: Automatic retries with exponential backoff
- **Progress Tracking**: Real-time progress bar with detailed logging
- **Cancellable**: Stop processing mid-batch

## Installation

1. Download/clone this addon
2. Install dependencies:
   ```bash
   pip install google-genai
   ```
3. Copy addon folder to Anki's addon directory
4. Restart Anki

## Setup

1. Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
2. In Anki, select notes in the browser
3. Go to **Tools → Gemini TTS Batch Add**
4. Configure:
   - Enter your API key
   - Add note type mappings (which fields to read from/write to)
   - Adjust settings as needed
5. Click OK to start processing

## Configuration

### API Settings
- **API Key**: Your Gemini API key
- **Primary Model**: `gemini-2.5-pro-preview-tts` (default)
- **Fallback Model**: `gemini-2.5-flash-preview-tts` (default)
- **Enable Fallback**: Auto-switch on rate limits
- **Voice Name**: Voice to use (default: Zephyr)
- **Temperature**: Speech variation (0.0-2.0)

### Processing Settings
- **Skip Existing Audio**: Don't regenerate if audio exists
- **Retry Attempts**: Number of retries on errors (default: 3)
- **Retry Delay**: Seconds between retries (default: 2)

### Note Type Mappings
Configure which fields to use for each note type:
- **Source Field**: Field containing text to convert
- **Target Field**: Field where audio will be stored

## Usage

1. Open Card Browser
2. Select notes you want to add TTS to
3. **Tools → Gemini TTS Batch Add**
4. Watch progress dialog
5. Review success/failure log
6. Audio files saved as `[sound:gemini_tts_NOTEID_TIMESTAMP.wav]`

## Error Handling

The addon handles:
- **Rate Limits (429)**: Automatic fallback to flash model
- **API Errors (500/503)**: Retries with exponential backoff
- **Network Issues**: Configurable retry attempts
- **Invalid Input**: Skips and logs problematic notes

## File Structure

```
anki_gemini_tts/
├── __init__.py           # Entry point
├── config.json           # Default settings
├── manifest.json         # Addon metadata
├── config_dialog.py      # Configuration UI
├── tts_processor.py      # TTS generation logic
├── batch_handler.py      # Batch processing
└── requirements.txt      # Dependencies
```

## Troubleshooting

**No audio generated**: Check API key and internet connection

**Rate limit errors**: Enable fallback model or reduce batch size

**Wrong voice**: Change voice name in settings (available: Zephyr, Puck, Charon, Kore, Fenrir, Aoede)

## License

MIT License - See LICENSE file for details