import time
import torch
import whisper
import os

def benchmark():
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"Device: {torch.cuda.get_device_name(0)}")
    
    # 1. Measure Model Load Time
    start = time.time()
    print("Loading 'base' model...")
    model = whisper.load_model("base")
    # Force move to GPU to be sure
    model.to("cuda") 
    print(f"Model loaded in {time.time() - start:.2f}s")
    print(f"Model device: {model.device}")

    # 2. Measure Transcription Time (Real Audio)
    test_file = "/home/lucid/projects/yt-transcriber/channels/All-In_Podcast/mp3/Supercharging_a_New_FDA__Marty_Makary_on_Science__....mp3"
    
    if not os.path.exists(test_file):
        print(f"Error: Test file not found at {test_file}")
        return

    print(f"Transcribing {test_file}...")
    start = time.time()
    result = model.transcribe(test_file)
    duration = time.time() - start
    print(f"Transcription took {duration:.2f}s for the full file.")
    print(f"Text length: {len(result['text'])} chars")

if __name__ == "__main__":
    benchmark()
