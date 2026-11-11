# Build using the isolated .venv-build interpreter.
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []
# The running server uses Deepgram for /audio and /voice.  Keep the portable
# GitHub build small enough to commit by excluding the unused local Whisper
# runtime (its model alone is about 1.5 GB).
for package in ("uvicorn", "websockets"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for package in ("openai", "tqdm"):
    datas += copy_metadata(package)

a = Analysis(["launcher.py"], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["torch", "torchvision", "tensorflow", "matplotlib", "pandas", "pytest",
                       "faster_whisper", "ctranslate2", "onnxruntime", "huggingface_hub", "tokenizers", "av"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NurseBackend",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True)
