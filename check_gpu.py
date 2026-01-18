import torch
import whisper

print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA device count: {torch.cuda.device_count()}")
    print(f"Current device: {torch.cuda.current_device()}")
    print(f"Device name: {torch.cuda.get_device_name(0)}")
else:
    print("CUDA is NOT available. Whisper will run on CPU.")

try:
    model = whisper.load_model("tiny")
    print(f"Whisper device: {model.device}")
except Exception as e:
    print(f"Error loading whisper model: {e}")
