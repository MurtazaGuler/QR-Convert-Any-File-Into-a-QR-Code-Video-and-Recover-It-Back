"""
QR-Pro: Bi-directional File to Video Converter via QR Code Sequences
===================================================================
Author: GitHub Contributor
Description: This script packs any binary/text file into a sequence of high-density 
QR code frames, compiles them into an MP4 video using FFmpeg, and decodes the 
resulting video back to restore the original file with absolute data integrity.

Requirements:
    pip install qrcode[pil] opencv-python-headless zxing-cpp
"""

import os
import sys
import struct
import zlib
import base64
import time
import subprocess

import qrcode
import numpy as np
import cv2
from PIL import Image

# --------------------------------------------------------------------------
# GLOBAL CONFIGURATION & OPTIMIZATION SETTINGS
# --------------------------------------------------------------------------
MAGIC = b"QRP1"
FRAME_SIZE = 250        # Output resolution size (Square: FRAME_SIZE x FRAME_SIZE)
CHUNK_SIZE = 200        # Data payload byte size per QR frame
FPS = 24                # Framerate for the encoded video stream
CRF = 30                # H.264 Constant Rate Factor (Compression trade-off)


# --------------------------------------------------------------------------
# CORE CORE UTILITY FUNCTIONS
# --------------------------------------------------------------------------

def build_container(file_path: str) -> bytes:
    """Serializes the file name and raw binary payload into a unified byte stream."""
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        data = f.read()
    name_bytes = filename.encode("utf-8")
    if len(name_bytes) > 65535:
        raise ValueError("Filename exceeds max length limits (65KB).")
    blob = struct.pack(">H", len(name_bytes)) + name_bytes + data
    return blob


def build_packets(blob: bytes, chunk_size: int):
    """Chunks the byte stream into structured network packets protected by CRC32."""
    total = max(1, (len(blob) + chunk_size - 1) // chunk_size)
    packets = []
    for i in range(total):
        chunk = blob[i * chunk_size:(i + 1) * chunk_size]
        crc = zlib.crc32(chunk) & 0xFFFFFFFF
        header = MAGIC + struct.pack(">III", total, i, crc)
        packets.append(header + chunk)
    return packets


def make_qr_frame(packet: bytes, frame_size: int) -> np.ndarray:
    """Generates a highly resilient QR frame using Base64 encoding to prevent encoding distortion."""
    b64_text = base64.b64encode(packet).decode("ascii")
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # Max 30% error correction rate
        box_size=10,
        border=4,
    )
    qr.add_data(b64_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((frame_size, frame_size), Image.NEAREST)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# --------------------------------------------------------------------------
# ENCODER MODULE: FILE -> VIDEO
# --------------------------------------------------------------------------

def encode_file_to_video(file_path: str, output_path: str,
                          fps: int = FPS, chunk_size: int = CHUNK_SIZE,
                          crf: int = CRF, progress_cb=None) -> str:
    """Processes raw data chunks into structured QR sequences and pipes them to FFmpeg."""
    blob = build_container(file_path)
    packets = build_packets(blob, chunk_size)
    total = len(packets)

    # Launching synchronized FFmpeg pipeline with optimal parameters for cellular structures
    proc = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{FRAME_SIZE}x{FRAME_SIZE}",
            "-framerate", str(fps),
            "-i", "-",
            "-an",  # Strip audio track
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    for i, packet in enumerate(packets):
        frame = make_qr_frame(packet, FRAME_SIZE)
        proc.stdin.write(frame.tobytes())
        if progress_cb:
            progress_cb(i + 1, total)

    proc.stdin.close()
    stderr = proc.stderr.read()
    proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg pipeline failure:\n{stderr.decode('utf-8', errors='ignore')}"
        )

    return output_path


# --------------------------------------------------------------------------
# DECODER MODULE: VIDEO -> FILE
# --------------------------------------------------------------------------

def decode_video_to_file(video_path: str, output_dir: str, progress_cb=None):
    """Decodes video frame-by-frame using zxingcpp and validates CRC32 integrity to reconstruct files."""
    import zxingcpp

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video source target: {video_path}")

    chunks = {}
    total_expected = None
    frame_no = 0
    total_frames_hint = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_no += 1

        results = zxingcpp.read_barcodes(frame)
        if not results:
            if progress_cb:
                progress_cb(frame_no, total_frames_hint)
            continue

        try:
            packet = base64.b64decode(results[0].text)
        except Exception:
            if progress_cb:
                progress_cb(frame_no, total_frames_hint)
            continue

        if packet[:4] != MAGIC:
            if progress_cb:
                progress_cb(frame_no, total_frames_hint)
            continue

        total, idx, crc = struct.unpack(">III", packet[4:16])
        payload = packet[16:]

        if zlib.crc32(payload) & 0xFFFFFFFF == crc:
            total_expected = total
            chunks[idx] = payload

        if progress_cb:
            progress_cb(frame_no, total_frames_hint)

    cap.release()

    if total_expected is None:
        raise RuntimeError("No valid QR-Pro data frames detected in the video stream.")

    missing = [i for i in range(total_expected) if i not in chunks]
    if missing:
        raise RuntimeError(f"Data stream corrupted. Missing or unreadable frames: {missing}")

    blob = b"".join(chunks[i] for i in range(total_expected))
    name_len = struct.unpack(">H", blob[:2])[0]
    orig_filename = blob[2:2 + name_len].decode("utf-8")
    data = blob[2 + name_len:]

    ext = os.path.splitext(orig_filename)[1]
    output_path = os.path.join(output_dir, f"qr_file{ext}")
    with open(output_path, "wb") as f:
        f.write(data)

    return output_path, orig_filename


# --------------------------------------------------------------------------
# MAIN EXECUTION ENTRYPOINT
# --------------------------------------------------------------------------

def main():
    import shutil
    import tkinter as tk
    from tkinter import filedialog, messagebox

    if shutil.which("ffmpeg") is None:
        print("ERROR: FFmpeg binary not found in system PATH. Please install FFmpeg.")
        return

    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="QR Pro - Select File to Encode into Video"
    )
    if not file_path:
        print("No input file selected. Exiting pipeline.")
        return

    workdir = os.getcwd()
    video_path = os.path.join(workdir, "qr_video.mp4")

    # ---- PHASE 1: File Encoding ----
    print(f"[1/2] Encoding '{os.path.basename(file_path)}' into synchronized video...")
    t0 = time.time()

    def prog1(i, total):
        print(f"\r  Writing frame matrix: {i}/{total}", end="", flush=True)

    try:
        encode_file_to_video(file_path, video_path, progress_cb=prog1)
    except Exception as e:
        print(f"\nCRITICAL ENCODE ERROR: {e}")
        messagebox.showerror("QR Pro - Error", f"Encoding pipeline broke:\n{e}")
        return

    print(f"\n[1/2] Success ({time.time() - t0:.1f}s). Exported Video: {video_path}")

    # ---- PHASE 2: Video Decoding ----
    print(f"[2/2] Re-decoding '{os.path.basename(video_path)}' back into physical asset...")
    t1 = time.time()

    def prog2(i, total):
        print(f"\r  Scanning frame matrix: {i}/{total}", end="", flush=True)

    try:
        out_path, orig_name = decode_video_to_file(video_path, workdir, progress_cb=prog2)
    except Exception as e:
        print(f"\nCRITICAL DECODE ERROR: {e}")
        messagebox.showerror("QR Pro - Error", f"Decoding pipeline broke:\n{e}")
        return

    print(f"\n[2/2] Success ({time.time() - t1:.1f}s). Recovered File: {out_path} (Original: {orig_name})")

    messagebox.showinfo(
        "QR Pro Status",
        f"Pipeline Completed Successfully!\n\n"
        f"Encoded Video Path: {video_path}\n"
        f"Recovered Output Path: {out_path}\n"
        f"Original Filename Reference: {orig_name}"
    )


if __name__ == "__main__":
    main()