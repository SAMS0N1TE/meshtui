# meshtui/ui_ptk/text_sanitize.py
import re

# Pre-compile the regex for efficiency
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
CONTROL_CHARS_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def sanitize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    # Remove ANSI escape sequences
    sanitized = ANSI_ESCAPE_PATTERN.sub('', text)
    # Remove other control characters
    sanitized = CONTROL_CHARS_PATTERN.sub('', sanitized)
    # Explicitly handle carriage returns by removing them
    sanitized = sanitized.replace('\r', '')
    return sanitized