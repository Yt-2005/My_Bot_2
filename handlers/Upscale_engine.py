"""
upscale_engine.py — Best-quality AI upscaling pipeline
Stack:  Real-ESRGAN x4+  →  GFPGAN (face fix)  →  OpenCV sharpening  →  PNG output

Install requirements:
    pip install realesrgan gfpgan opencv-python-headless basicsr facexlib

GPU recommended but CPU works (slower).
"""

import io
import logging
import os
import tempfile
from typing import Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Weight paths (auto-downloaded on first run) ──────────────────────────────
_REALESRGAN_MODEL = "RealESRGAN_x4plus"   # general photos
_REALESRGAN_ANIME = "RealESRGAN_x4plus_anime_6B"  # anime/illustration

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def upscale_image(
    image_bytes: bytes,
    scale: int = 4,
    face_enhance: bool = True,
    sharpen: bool = True,
    mode: str = "photo",          # "photo" | "anime"
) -> Tuple[bytes, str | None]:
    """
    Upscale an image with the best available method.

    Returns (png_bytes, error_message_or_None).
    Falls back gracefully if heavy libraries are unavailable.
    """
    try:
        return await _realesrgan_pipeline(image_bytes, scale, face_enhance, sharpen, mode)
    except ImportError:
        logger.warning("Real-ESRGAN not available — falling back to Pillow Lanczos+sharpen")
        return _pillow_fallback(image_bytes, scale, sharpen)
    except Exception as e:
        logger.error(f"Upscale error: {e}")
        return b"", str(e)


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — Real-ESRGAN + GFPGAN
# ══════════════════════════════════════════════════════════════════════════════

async def _realesrgan_pipeline(
    image_bytes: bytes,
    scale: int,
    face_enhance: bool,
    sharpen: bool,
    mode: str,
) -> Tuple[bytes, None]:
    import torch
    from realesrgan import RealESRGANer
    from basicsr.archs.rrdbnet_arch import RRDBNet

    # ── Load model ────────────────────────────────────────────────────────────
    if mode == "anime":
        from realesrgan.archs.srvgg_arch import SRVGGNetCompact
        model = SRVGGNetCompact(
            num_in_ch=3, num_out_ch=3, num_feat=64,
            num_conv=16, upscale=4, act_type="prelu"
        )
        model_name = _REALESRGAN_ANIME
        netscale = 4
    else:
        model = RRDBNet(
            num_in_ch=3, num_out_ch=3, num_feat=64,
            num_block=23, num_grow_ch=32, scale=4
        )
        model_name = _REALESRGAN_MODEL
        netscale = 4

    # Weight file — BasicSR downloads automatically on first run
    model_path = _get_model_path(model_name)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    upsampler = RealESRGANer(
        scale=netscale,
        model_path=model_path,
        model=model,
        tile=512,          # tile size to avoid OOM on large images
        tile_pad=10,
        pre_pad=0,
        half=device.type == "cuda",  # fp16 on GPU only
        device=device,
    )

    # ── Decode image ──────────────────────────────────────────────────────────
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError("Could not decode image")

    # ── Face enhancement (GFPGAN) ─────────────────────────────────────────────
    if face_enhance:
        try:
            from gfpgan import GFPGANer
            gfpgan_path = _get_gfpgan_path()
            face_enhancer = GFPGANer(
                model_path=gfpgan_path,
                upscale=scale,
                arch="clean",
                channel_multiplier=2,
                bg_upsampler=upsampler,
            )
            _, _, output_bgr = face_enhancer.enhance(
                img_bgr,
                has_aligned=False,
                only_center_face=False,
                paste_back=True,
            )
        except Exception as fe:
            logger.warning(f"GFPGAN face enhance failed ({fe}), using Real-ESRGAN only")
            output_bgr, _ = upsampler.enhance(img_bgr, outscale=scale)
    else:
        output_bgr, _ = upsampler.enhance(img_bgr, outscale=scale)

    # ── Sharpening ────────────────────────────────────────────────────────────
    if sharpen:
        output_bgr = _adaptive_sharpen(output_bgr)

    # ── Encode as PNG ─────────────────────────────────────────────────────────
    success, png_buf = cv2.imencode(".png", output_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not success:
        raise ValueError("PNG encode failed")

    return png_buf.tobytes(), None


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — Pillow Lanczos + unsharp mask (no GPU deps)
# ══════════════════════════════════════════════════════════════════════════════

def _pillow_fallback(image_bytes: bytes, scale: int, sharpen: bool) -> Tuple[bytes, None]:
    from PIL import Image, ImageFilter, ImageEnhance

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    new_size = (img.width * scale, img.height * scale)
    upscaled = img.resize(new_size, Image.LANCZOS)

    if sharpen:
        # Unsharp mask — radius=2, percent=150, threshold=3
        upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        # Mild color boost
        upscaled = ImageEnhance.Color(upscaled).enhance(1.15)
        upscaled = ImageEnhance.Contrast(upscaled).enhance(1.05)

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG", optimize=False)
    return buf.getvalue(), None


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _adaptive_sharpen(img_bgr: np.ndarray) -> np.ndarray:
    """
    Adaptive unsharp mask: sharpens detail areas, leaves smooth areas alone.
    """
    img_float = img_bgr.astype(np.float32)

    # Gaussian blur for the mask
    blurred = cv2.GaussianBlur(img_float, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(img_float, 1.5, blurred, -0.5, 0)

    # Detect edges (where to apply sharpening)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edge_mask = cv2.Canny(gray, 30, 100).astype(np.float32) / 255.0
    edge_mask = cv2.GaussianBlur(edge_mask, (5, 5), 0)
    edge_mask = np.stack([edge_mask] * 3, axis=-1)

    # Blend: sharp where edges exist, original elsewhere
    result = sharpened * edge_mask + img_float * (1.0 - edge_mask)
    return np.clip(result, 0, 255).astype(np.uint8)


def _get_model_path(model_name: str) -> str:
    """Return local weight path, downloading from GitHub if missing."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "realesrgan")
    os.makedirs(cache_dir, exist_ok=True)
    weight_file = os.path.join(cache_dir, f"{model_name}.pth")

    if not os.path.exists(weight_file):
        import urllib.request
        urls = {
            "RealESRGAN_x4plus":
                "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
            "RealESRGAN_x4plus_anime_6B":
                "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        }
        url = urls.get(model_name)
        if url:
            logger.info(f"Downloading {model_name} weights...")
            urllib.request.urlretrieve(url, weight_file)

    return weight_file


def _get_gfpgan_path() -> str:
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "gfpgan")
    os.makedirs(cache_dir, exist_ok=True)
    weight_file = os.path.join(cache_dir, "GFPGANv1.4.pth")

    if not os.path.exists(weight_file):
        import urllib.request
        url = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth"
        logger.info("Downloading GFPGAN weights...")
        urllib.request.urlretrieve(url, weight_file)

    return weight_file


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE INFO HELPER
# ══════════════════════════════════════════════════════════════════════════════

def get_image_info(image_bytes: bytes) -> dict:
    """Return width, height, and size of raw image."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return {}
    h, w = img.shape[:2]
    return {"width": w, "height": h, "megapixels": round(w * h / 1_000_000, 2)}