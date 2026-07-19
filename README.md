# QR-Pro

QR-Pro is a Python tool that converts any file into a sequence of QR
codes stored in an MP4 video, then reconstructs the original file by
reading the video.

## Features

-   Encode any binary or text file into a QR video
-   Decode the video back into the original file
-   CRC32 validation for every frame
-   Preserves original filename
-   FFmpeg-based H.264 encoding
-   Progress reporting

## Requirements

-   Python 3.10+
-   FFmpeg in PATH

Install:

``` bash
pip install qrcode[pil] opencv-python-headless zxing-cpp numpy pillow
```

## Usage

``` bash
python qr.py
```

1.  Select a file.
2.  The program generates `qr_video.mp4`.
3.  The generated video is scanned automatically.
4.  The recovered file is saved as `qr_file.<ext>`.

## Configuration

``` python
FRAME_SIZE = 250
CHUNK_SIZE = 200
FPS = 24
CRF = 30
```

-   **FRAME_SIZE**: Resolution of each QR frame.
-   **CHUNK_SIZE**: Bytes stored per QR frame.
-   **FPS**: Video frame rate.
-   **CRF**: Compression level (higher = smaller file, lower quality).

## How it Works

1.  Package filename and file data.
2.  Split into packets.
3.  Add CRC32 and metadata.
4.  Encode packets as QR codes.
5.  Render QR frames into an MP4 using FFmpeg.
6.  Decode each QR frame.
7.  Verify CRC32.
8.  Rebuild the original file.

## Dependencies

-   qrcode
-   Pillow
-   NumPy
-   OpenCV
-   zxing-cpp
-   FFmpeg

## License

MIT
