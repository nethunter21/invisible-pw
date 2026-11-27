# PyInstaller spec — build with:  pyinstaller GeoLens.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = [("geolens/ui", "geolens/ui"), ("geolens/data", "geolens/data")]
datas += collect_data_files("rapidocr_onnxruntime")
datas += collect_data_files("webview")
for pkg in ("transformers", "tokenizers", "huggingface_hub", "safetensors", "tqdm", "regex", "requests",
            "packaging", "filelock", "numpy", "pyyaml", "torch"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

hidden = collect_submodules("transformers.models.clip") + collect_submodules("rapidocr_onnxruntime") + ["tzdata", "webview.platforms.edgechromium",
                                                            "webview.platforms.winforms"]

a = Analysis(["GeoLens.py"], pathex=["."], datas=datas, hiddenimports=hidden,
             excludes=["matplotlib", "tkinter", "IPython", "jupyter", "pytest", "tensorflow", "jax",
                       "torchvision", "torchaudio", "pandas", "scipy.spatial.cKDTree"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GeoLens", icon="assets/geolens.ico",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="GeoLens", upx=False)
