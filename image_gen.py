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
    """
    Generate an image from a text prompt.

    Args:
        prompt:    The image description from the user
        style_key: Optional style name from IMAGE_STYLES (e.g. "🎌 Anime")

    Returns:
        (image_bytes, error_message)
    """
    # Append style modifiers to prompt
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
    Upscale/enhance an image using Picwish API (free tier).
    Falls back to a sharpening filter if API unavailable.

    Returns:
        (enhanced_image_bytes, error_message)
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        import io

        # Load the image
        img = Image.open(io.BytesIO(image_bytes))
        original_size = img.size
        logger.info(f"📸 Enhancing image {original_size}")

        # Convert to RGB if needed
        if img.mode != "RGB":
            img = img.convert("RGB")

        # ── Step 1: Upscale 2x using LANCZOS (high quality)
        new_w = min(img.width * 2, 4096)
        new_h = min(img.height * 2, 4096)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # ── Step 2: Sharpen
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=2))

        # ── Step 3: Enhance contrast
        contrast = ImageEnhance.Contrast(img)
        img = contrast.enhance(1.15)

        # ── Step 4: Enhance color saturation
        color = ImageEnhance.Color(img)
        img = color.enhance(1.1)

        # ── Step 5: Enhance sharpness
        sharpness = ImageEnhance.Sharpness(img)
        img = sharpness.enhance(1.3)

        # ── Step 6: Reduce noise with slight smooth pass
        img = img.filter(ImageFilter.SMOOTH_MORE)
        # Re-sharpen slightly after smoothing
        img = img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=80, threshold=1))

        # Save to bytes
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=95, optimize=True)
        result = output.getvalue()

        logger.info(f"✅ Enhanced: {original_size} → {img.size} ({len(result) // 1024} KB)")
        return result, None

    except ImportError:
        return None, "❌ Pillow library not installed. Run: pip install Pillow"
    except Exception as e:
        logger.error(f"Upscale error: {e}")
        return None, f"❌ Enhancement failed: {str(e)[:100]}"
