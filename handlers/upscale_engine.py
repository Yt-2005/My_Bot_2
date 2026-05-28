"""
upscale_engine.py — Image upscaling via Real-ESRGAN + GFPGAN
Falls back gracefully if models aren't loaded yet.
"""

import os
import logging
import tempfile
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

# ── Lazy-load heavy models only when first needed ──────────────────────────
_realesrgan_model = None
_gfpgan_model = None


def _load_realesrgan():
    global _realesrgan_model
    if _realesrgan_model is not None:
        return _realesrgan_model
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet

        model = RRDBNet(
            num_in_ch=3, num_out_ch=3,
            num_feat=64, num_block=23, num_grow_ch=32, scale=4
        )
        model_path = _ensure_model(
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            "RealESRGAN_x4plus.pth"
        )
        _realesrgan_model = RealESRGANer(
            scale=4,
            model_path=model_path,
            model=model,
            tile=256,          # tile to avoid OOM on free tier
            tile_pad=10,
            pre_pad=0,
            half=False,        # CPU — no fp16
        )
        logger.info("✅ Real-ESRGAN model loaded")
    except Exception as e:
        logger.error(f"Failed to load Real-ESRGAN: {e}")
        _realesrgan_model = None
    return _realesrgan_model


def _load_gfpgan():
    global _gfpgan_model
    if _gfpgan_model is not None:
        return _gfpgan_model
    try:
        from gfpgan import GFPGANer

        model_path = _ensure_model(
            "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth",
            "GFPGANv1.3.pth"
        )
        _gfpgan_model = GFPGANer(
            model_path=model_path,
            upscale=2,
            arch="clean",
            channel_multiplier=2,
        )
        logger.info("✅ GFPGAN model loaded")
    except Exception as e:
        logger.error(f"Failed to load GFPGAN: {e}")
        _gfpgan_model = None
    return _gfpgan_model


def _ensure_model(url: str, filename: str) -> str:
    """Download model weights if not cached."""
    cache_dir = Path(os.getenv("MODEL_CACHE_DIR", "/tmp/upscale_models"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / filename
    if not dest.exists():
        logger.info(f"Downloading {filename}...")
        import urllib.request
        urllib.request.urlretrieve(url, dest)
        logger.info(f"Downloaded {filename}")
    return str(dest)


# ── Public API ──────────────────────────────────────────────────────────────

def get_image_info(image_bytes: bytes) -> dict:
    """Return basic info about an image (size, mode, format)."""
    import io
    try:
        img = Image.open(io.BytesIO(image_bytes))
        return {
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format or "unknown",
        }
    except Exception as e:
        logger.error(f"get_image_info error: {e}")
        return {"width": 0, "height": 0, "mode": "unknown", "format": "unknown"}


def upscale_image(
    image_bytes: bytes,
    scale: int = 4,
    enhance_face: bool = False,
) -> bytes:
    """
    Upscale image bytes and return upscaled image bytes (JPEG).

    Args:
        image_bytes:  Raw bytes of the input image.
        scale:        Upscale factor (2 or 4). Default 4.
        enhance_face: Also run GFPGAN face enhancement. Default False.

    Returns:
        JPEG bytes of the upscaled image.

    Raises:
        RuntimeError if upscaling fails.
    """
    import io
    import cv2
    import numpy as np

    # Decode input
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise RuntimeError("Could not decode image. Make sure it's a valid JPEG/PNG.")

    # ── Real-ESRGAN upscale ────────────────────────────────────────────────
    upscaler = _load_realesrgan()
    if upscaler is None:
        # Fallback: simple Lanczos resize if model unavailable
        logger.warning("Real-ESRGAN unavailable, using Lanczos fallback")
        h, w = img_bgr.shape[:2]
        img_bgr = cv2.resize(img_bgr, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
    else:
        try:
            img_bgr, _ = upscaler.enhance(img_bgr, outscale=scale)
        except Exception as e:
            raise RuntimeError(f"Upscaling failed: {e}") from e

    # ── Optional GFPGAN face enhancement ──────────────────────────────────
    if enhance_face:
        gfpganer = _load_gfpgan()
        if gfpganer is not None:
            try:
                _, _, img_bgr = gfpganer.enhance(
                    img_bgr,
                    has_aligned=False,
                    only_center_face=False,
                    paste_back=True,
                )
            except Exception as e:
                logger.warning(f"GFPGAN face enhancement failed (skipping): {e}")

    # Encode output as JPEG
    success, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not success:
        raise RuntimeError("Failed to encode upscaled image as JPEG")

    return buf.tobytes()