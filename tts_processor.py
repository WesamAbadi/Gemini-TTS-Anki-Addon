import struct
import time
import mimetypes
from typing import Optional, Tuple, Dict, Callable
from google import genai
from google.genai import types

class RateLimitError(Exception):
    pass

class EmptyResponseError(Exception):
    pass

class TTSProcessor:
    """Handles TTS generation via Gemini API"""
    
    def __init__(self, api_key: str, voice_name: str = "Zephyr", temperature: float = 1.0, system_instruction: str = None):
        self.api_key = api_key
        self.voice_name = voice_name
        self.temperature = temperature
        self.system_instruction = system_instruction
        self.client = None
        
    def initialize_client(self):
        """Initialize Gemini client"""
        if not self.client:
            self.client = genai.Client(api_key=self.api_key)
            
    def generate_audio(self, text: str, model: str, max_retries: int = 3, 
                      retry_delay: int = 2, retry_on_empty: bool = False,
                      check_cancel: Callable[[], bool] = None) -> Tuple[Optional[bytes], Dict]:
        """
        Generate audio and return data + usage stats
        """
        self.initialize_client()
        usage_stats = {'input_tokens': 0, 'output_tokens': 0}
        
        if not text or not text.strip():
            return None, usage_stats

        final_text = text
        if self.system_instruction and self.system_instruction.strip():
            final_text = f"{self.system_instruction.strip()}\n{text}"

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=final_text)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            temperature=self.temperature,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
        )
        
        for attempt in range(max_retries):
            if check_cancel and check_cancel():
                return None, usage_stats

            try:
                audio_chunks = []
                mime_type = None
                
                # We can't interrupt the generator easily once it starts, but it yields chunks
                for chunk in self.client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=generate_content_config,
                ):
                    if check_cancel and check_cancel():
                        return None, usage_stats

                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        usage_stats['input_tokens'] = chunk.usage_metadata.prompt_token_count or 0
                        usage_stats['output_tokens'] = chunk.usage_metadata.candidates_token_count or 0

                    if (chunk.candidates and 
                        chunk.candidates[0].content and 
                        chunk.candidates[0].content.parts):
                        
                        part = chunk.candidates[0].content.parts[0]
                        
                        if part.inline_data and part.inline_data.data:
                            audio_chunks.append(part.inline_data.data)
                            if not mime_type:
                                mime_type = part.inline_data.mime_type
                                
                if audio_chunks:
                    audio_data = b''.join(audio_chunks)
                    ext = mimetypes.guess_extension(mime_type) if mime_type else None
                    if ext is None or 'wav' not in str(ext).lower():
                        final_audio = self.convert_to_wav(audio_data, mime_type or "audio/wav")
                        return final_audio, usage_stats
                    return audio_data, usage_stats
                
                if retry_on_empty:
                    raise EmptyResponseError("Received empty audio stream from API.")
                
                return None, usage_stats
                
            except Exception as e:
                # Immediate exit if cancelled
                if check_cancel and check_cancel():
                    return None, usage_stats

                error_msg = str(e).lower()
                
                if '429' in error_msg or 'resource_exhausted' in error_msg:
                    raise RateLimitError(str(e))
                
                is_retryable = (
                    '500' in error_msg or 
                    '503' in error_msg or 
                    'timeout' in error_msg or 
                    isinstance(e, EmptyResponseError)
                )

                if is_retryable:
                    if attempt < max_retries - 1:
                        # Interruptible sleep
                        wait_sec = retry_delay * (attempt + 1)
                        for _ in range(wait_sec * 10):
                            if check_cancel and check_cancel():
                                return None, usage_stats
                            time.sleep(0.1)
                        continue
                
                if isinstance(e, EmptyResponseError):
                    return None, usage_stats

                raise Exception(f"{e}")
                
        return None, usage_stats
        
    def convert_to_wav(self, audio_data: bytes, mime_type: str) -> bytes:
        """Convert raw audio data to WAV format"""
        parameters = self.parse_audio_mime_type(mime_type)
        bits_per_sample = parameters["bits_per_sample"]
        sample_rate = parameters["rate"]
        num_channels = 1
        data_size = len(audio_data)
        bytes_per_sample = bits_per_sample // 8
        block_align = num_channels * bytes_per_sample
        byte_rate = sample_rate * block_align
        chunk_size = 36 + data_size

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            chunk_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            num_channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size
        )
        return header + audio_data
        
    def parse_audio_mime_type(self, mime_type: str) -> dict:
        bits_per_sample = 16
        rate = 24000

        if not mime_type:
            return {"bits_per_sample": bits_per_sample, "rate": rate}

        parts = mime_type.split(";")
        for param in parts:
            param = param.strip()
            if param.lower().startswith("rate="):
                try:
                    rate_str = param.split("=", 1)[1]
                    rate = int(rate_str)
                except (ValueError, IndexError):
                    pass
            elif param.startswith("audio/L"):
                try:
                    bits_per_sample = int(param.split("L", 1)[1])
                except (ValueError, IndexError):
                    pass

        return {"bits_per_sample": bits_per_sample, "rate": rate}
        
    def generate_with_fallback(self, text: str, primary_model: str, 
                               fallback_model: str, enable_fallback: bool,
                               max_retries: int = 3, retry_delay: int = 2,
                               retry_on_empty: bool = False,
                               check_cancel: Callable[[], bool] = None) -> Tuple[Optional[bytes], str, Dict]:
        """
        Generate audio with automatic fallback. Returns (audio, model_name, usage_stats)
        """
        try:
            audio, stats = self.generate_audio(text, primary_model, max_retries, retry_delay, retry_on_empty, check_cancel)
            if audio:
                return audio, primary_model, stats
            return None, "No audio generated", stats
            
        except RateLimitError as e:
            if enable_fallback:
                try:
                    # Brief wait before fallback
                    if check_cancel and not check_cancel():
                        time.sleep(1)
                    
                    audio, stats = self.generate_audio(text, fallback_model, max_retries, retry_delay, retry_on_empty, check_cancel)
                    if audio:
                        return audio, fallback_model, stats
                    return None, "Fallback model: No audio generated", stats
                except Exception as fallback_error:
                    return None, str(fallback_error), {}
            else:
                return None, str(e), {}
                
        except Exception as e:
            return None, str(e), {}