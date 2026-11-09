"""Finds ffmpeg: system one if installed, otherwise the one bundled by imageio-ffmpeg
(installed automatically with pip, so nothing to set up on Windows/Mac)."""
import shutil


def _find() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit("Nu găsesc ffmpeg. Rulează: pip install imageio-ffmpeg")


FFMPEG = _find()
