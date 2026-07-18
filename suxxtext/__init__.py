"""SuXXTeXt — YouTube archive + transcription toolkit."""

__version__ = "2.0.0"

from suxxtext.paths import (
    CHANNELS_ROOT,
    ensure_channel_dirs,
    resolve_channel_folder,
    sanitize_filename,
    transcript_exists_for_id,
)

__all__ = [
    "CHANNELS_ROOT",
    "ensure_channel_dirs",
    "resolve_channel_folder",
    "sanitize_filename",
    "transcript_exists_for_id",
    "__version__",
]
