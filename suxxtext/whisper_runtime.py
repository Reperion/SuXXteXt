"""faster-whisper model loading and transcription."""

from __future__ import annotations

import contextlib
import queue
from typing import Any, Optional, Tuple, Union

from colorama import Fore, Style
from faster_whisper import WhisperModel


def get_whisper_runtime() -> Tuple[str, str]:
    """Prefer CUDA + float16; fall back to CPU int8."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def load_whisper_model(model_name: str, quiet: bool = False) -> WhisperModel:
    device, compute_type = get_whisper_runtime()
    if not quiet:
        print(
            f"{Fore.MAGENTA}Loading Whisper '{model_name}' on {device} ({compute_type})...{Style.RESET_ALL}"
        )
    return WhisperModel(model_name, device=device, compute_type=compute_type)


class ModelPool:
    def __init__(self, model_name: str, pool_size: int):
        self.pool: queue.Queue = queue.Queue()
        self.pool_size = pool_size
        self.device, self.compute_type = get_whisper_runtime()
        print(
            f"{Fore.MAGENTA}Initializing Model Pool: {pool_size} x '{model_name}' "
            f"on {self.device} ({self.compute_type})...{Style.RESET_ALL}"
        )
        for i in range(pool_size):
            try:
                model = WhisperModel(
                    model_name, device=self.device, compute_type=self.compute_type
                )
                self.pool.put(model)
                print(
                    f"{Fore.MAGENTA}  - Loaded model instance {i + 1}/{pool_size}{Style.RESET_ALL}"
                )
            except Exception as e:
                if self.device != "cpu":
                    print(
                        f"{Fore.YELLOW}GPU load failed ({e}); falling back to CPU int8 "
                        f"for remaining instances...{Style.RESET_ALL}"
                    )
                    self.device, self.compute_type = "cpu", "int8"
                    try:
                        model = WhisperModel(
                            model_name,
                            device=self.device,
                            compute_type=self.compute_type,
                        )
                        self.pool.put(model)
                        print(
                            f"{Fore.MAGENTA}  - Loaded model instance {i + 1}/{pool_size} on CPU{Style.RESET_ALL}"
                        )
                        continue
                    except Exception as e2:
                        print(
                            f"{Fore.RED}Error loading model instance {i + 1}: {e2}{Style.RESET_ALL}"
                        )
                        raise e2
                print(f"{Fore.RED}Error loading model instance {i + 1}: {e}{Style.RESET_ALL}")
                raise e

    @contextlib.contextmanager
    def get_model(self):
        model = self.pool.get()
        try:
            yield model
        finally:
            self.pool.put(model)


def transcribe_audio(
    audio_file: str,
    model_name_or_obj: Union[str, Any],
    output_file: str,
    lock=None,
) -> Tuple[bool, Optional[str]]:
    _ = lock
    try:
        if isinstance(model_name_or_obj, str):
            model = load_whisper_model(model_name_or_obj)
        else:
            model = model_name_or_obj
        segments, _ = model.transcribe(audio_file, beam_size=5)
        full_text = " ".join(segment.text for segment in segments)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(full_text)
        return True, None
    except Exception as e:
        return False, str(e)


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
