# Build using the isolated .venv-build interpreter.
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "opencc", "uvicorn", "websockets"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for package in ("openai", "faster-whisper", "huggingface-hub", "tqdm"):
    datas += copy_metadata(package)

a = Analysis(["launcher.py"], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["torch", "torchvision", "tensorflow", "matplotlib", "pandas", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NurseBackend",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NurseBackend")
