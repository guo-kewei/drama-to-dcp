# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['yt_dlp', 'websockets', 'curl_cffi', 'mutagen', 'brotli', 'secretstorage', 'funasr', 'torch', 'torchaudio', 'torchvision', 'modelscope', 'matplotlib', 'librosa', 'scipy', 'av', 'faster_whisper', 'ctranslate2', 'onnxruntime', 'tokenizers', 'huggingface_hub'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='短剧转电影平台',
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
    icon=['app.ico'],
)
