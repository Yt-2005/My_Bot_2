"""
ai/image_gen.py — AI Image Generation via Pollinations.ai
Free, no API key required. Supports multiple art styles.
"""

import logging
import asyncio
import aiohttp
import urllib.parse
from config import IMAGE_STYLES

logger = logging.getLogger(__name__)

# Pollinations base URL
BASE_URL = "https://image.pollinations.ai/prompt/{prompt}?width=1024&height=1024&nologo=true&enhance=true"


async def generate_image(prompt: str, style_key: str = None) -> tuple[bytes | None, str | None]:
    if style_key and style_key in IMAGE_STYLES:
        style_suffix = IMAGE_STYLES[style_key]
        full_prompt = f"{prompt}, {style_suffix}"
    else:
        full_prompt = prompt

    encoded = urllib.parse.quote(full_prompt)
    url = BASE_URL.format(prompt=encoded)

    logger.info(f"🎨 Generating image: {full_prompt[:80]}...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read()
                    logger.info(f"✅ Image generated ({len(image_bytes) // 1024} KB)")
                    return image_bytes, None
                else:
                    return None, f"❌ Image generation failed (HTTP {resp.status})"

    except asyncio.TimeoutError:
        return None, "⏱️ Image generation timed out. Please try again."
    except Exception as e:
        logger.error(f"Image gen error: {e}")
        return None, f"❌ Failed to generate image: {str(e)[:100]}"


async def upscale_image(image_bytes: bytes) -> tuple[bytes | None, str | None]:
    """
    Upscale using Real-ESRGAN via Replicate (free) or Upscayl API.
    Falls back to enhanced Pillow processing.
    """
    # ── Try Real-ESRGAN via free API first ──
    result = await _upscale_realesrgan(image_bytes)
    if result[0]:
        return result

    # ── Fallback: Enhanced Pillow ──
    logger.info("⚠️ API unavailable, using enhanced Pillow fallback")
    return await _upscale_pillow(image_bytes)


async def _upscale_realesrgan(image_bytes: bytes) -> tuple[bytes | None, str | None]:
    """Use Picwish free API for AI upscaling."""
    try:
        import base64
        b64 = base64.b64encode(image_bytes).decode()

        # Picwish free tier — no API key needed
        url = "https://picwish.com/api/upload"
        payload = {
            "image_base64": b64,
            "scale": 2,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.deepai.org/api/torch-srgan",
                data={"image": image_bytes},
                headers={"api-key": "quickstart-QUdJIGlzIGF3ZXNvbWU"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    output_url = data.get("output_url")
                    if output_url:
                        async with session.get(output_url) as img_resp:
                            if img_resp.status == 200:
                                result = await img_resp.read()
                                logger.info(f"✅ Real-ESRGAN upscale done ({len(result) // 1024} KB)")
                                return result, None
    except Exception as e:
        logger.warning(f"Real-ESRGAN API failed: {e}")

    return None, None


async def _upscale_pillow(image_bytes: bytes) -> tuple[bytes | None, str | None]:
    """Enhanced Pillow upscaling with better sharpening."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        import io

        img = Image.open(io.BytesIO(image_bytes))
        original_size = img.size
        logger.info(f"📸 Enhancing image {original_size}")

        if img.mode != "RGB":
            img = img.convert("RGB")

        # ── Step 1: Upscale 2x LANCZOS
        new_w = min(img.width * 2, 4096)
        new_h = min(img.height * 2, 4096)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # ── Step 2: Strong unsharp mask for crispness
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=1))

        # ── Step 3: Brightness (slight lift)
        brightness = ImageEnhance.Brightness(img)
        img = brightness.enhance(1.05)

        # ── Step 4: Contrast boost
        contrast = ImageEnhance.Contrast(img)
        img = contrast.enhance(1.2)

        # ── Step 5: Vibrant colors
        color = ImageEnhance.Color(img)
        img = color.enhance(1.15)

        # ── Step 6: Sharpness
        sharpness = ImageEnhance.Sharpness(img)
        img = sharpness.enhance(1.5)

        # ── Step 7: Edge enhance
        img = img.filter(ImageFilter.EDGE_ENHANCE)

        # ── Step 8: Final soft denoise
        img = img.filter(ImageFilter.SMOOTH)
        img = img.filter(ImageFilter.UnsharpMask(radius=0.5, percent=60, threshold=1))

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=97, optimize=True)
        result = output.getvalue()

        logger.info(f"✅ Enhanced: {original_size} → {img.size} ({len(result) // 1024} KB)")
        return result, None

    except ImportError:
        return None, "❌ Pillow not installed."
    except Exception as e:
        logger.error(f"Upscale error: {e}")
        return None, f"❌ Enhancement failed: {str(e)[:100]}"