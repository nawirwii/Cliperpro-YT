# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

block_cipher = None

# Force import MediaPipe Tasks API modules BEFORE collecting submodules
# This ensures PyInstaller discovers the explicit imports used by portrait.py
try:
    import mediapipe
    import mediapipe.tasks
    import mediapipe.tasks.python
    import mediapipe.tasks.python.vision
    import mediapipe.tasks.python.vision.face_landmarker
    print(f"[sidecar.spec] MediaPipe Tasks API pre-imported successfully")
except ImportError as e:
    print(f"[sidecar.spec] WARNING: Could not pre-import mediapipe: {e}")

# Collect ALL mediapipe and cv2 data and submodules
mediapipe_data = collect_data_files('mediapipe', include_py_files=False)
mediapipe_submodules = collect_submodules('mediapipe')

opencv_data = collect_data_files('cv2')
opencv_submodules = collect_submodules('cv2')

numpy_submodules = collect_submodules('numpy')
ytdlp_submodules = collect_submodules('yt_dlp')

# curl_cffi (required by yt-dlp >=2026 for YouTube impersonation).
# Its native libcurl must be bundled as a binary, not just imported.
curl_cffi_binaries = collect_dynamic_libs('curl_cffi')
curl_cffi_submodules = collect_submodules('curl_cffi')

# Pillow
pillow_data = collect_data_files('PIL', include_py_files=False)
pillow_submodules = collect_submodules('PIL')

# v2.0.88: faster-whisper (optional local transcription engine).
# Its native libraries MUST be collected as binaries or the frozen sidecar
# raises "DLL load failed" on first use. Measured on-disk cost:
#   ctranslate2 60 MB, av 32 MB, tokenizers 12 MB, huggingface_hub 8 MB.
# onnxruntime (67 MB) is deliberately NOT collected — faster-whisper imports
# it lazily inside vad.py and we always run with vad_filter=False.
fw_imported = True
try:
    import faster_whisper  # noqa: F401
    print("[sidecar.spec] faster-whisper pre-imported successfully")
except ImportError as e:
    fw_imported = False
    print(f"[sidecar.spec] WARNING: faster-whisper not installed: {e}")

fw_binaries = []
fw_data = []
fw_submodules = []
if fw_imported:
    for pkg in ('ctranslate2', 'tokenizers', 'av', 'huggingface_hub'):
        try:
            fw_binaries += collect_dynamic_libs(pkg)
            fw_data += collect_data_files(pkg, include_py_files=False)
            fw_submodules += collect_submodules(pkg)
        except Exception as e:
            print(f"[sidecar.spec] WARNING: could not collect {pkg}: {e}")

a = Analysis(
    ['../../scripts/sidecar_entry.py'],
    pathex=['../..'],
    binaries=[
        *curl_cffi_binaries,
        *fw_binaries,
    ],
    datas=[
        *mediapipe_data,
        *opencv_data,
        *pillow_data,
        *fw_data,
    ],
    hiddenimports=[
        'openai',
        'certifi',
        'urllib3',
        'requests',
        'charset_normalizer',
        'idna',
        # curl_cffi for yt-dlp YouTube impersonation (TLS fingerprint)
        'curl_cffi',
        'curl_cffi.requests',
        'curl_cffi.impersonate',
        *curl_cffi_submodules,
        # PIL/Pillow for hook text overlay
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        # Force MediaPipe Tasks API imports
        'mediapipe.tasks',
        'mediapipe.tasks.python',
        'mediapipe.tasks.python.vision',
        'mediapipe.tasks.python.vision.face_landmarker',
        'mediapipe.tasks.python.vision.face_detector',
        'mediapipe.tasks.python.vision.image_classifier',
        'mediapipe.tasks.python.vision.object_detector',
        'mediapipe.python',
        *mediapipe_submodules,
        *opencv_submodules,
        *numpy_submodules,
        *ytdlp_submodules,
        *pillow_submodules,
        # faster-whisper local transcription (v2.0.88)
        'faster_whisper',
        'faster_whisper.audio',
        'faster_whisper.feature_extractor',
        'faster_whisper.tokenizer',
        'faster_whisper.transcribe',
        'faster_whisper.utils',
        'faster_whisper.vad',
        'ctranslate2',
        'tokenizers',
        'huggingface_hub',
        *fw_submodules,
    ],
    hookspath=['../../build/spec'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'tensorflow',
        'transformers',
        'datasets',
        'pandas',
        'scipy',
        'sklearn',
        'numba',
        'llvmlite',
        'onnxruntime',
        'pyarrow',
        'sounddevice',
        'sentry_sdk',
        'boto3',
        'botocore',
        'uvicorn',
        'tkinter',
        'IPython',
        'notebook',
        'jedi',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ytclip-sidecar-x86_64-pc-windows-msvc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
