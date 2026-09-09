from PIL import Image, ImageFilter, ImageEnhance
import os

# Two source renders, same composition, different Normal Map strength on the
# hex-grid material (see Icon_3D.blend, Hexagon.001 > Green.001):
#   - ORIGINAL (Strength 1.590): deep per-hex-cell bevel shading. Reads as
#     quality at large sizes, but that fine shading is exactly what turned to
#     mud/fringe once downsampled small.
#   - ALT (Strength 0.001): flat lighting, no chromatic-fringe artifact. Loses
#     the 3D depth look, but is much cleaner to downsample.
# Verified via direct crop diff: ORIGINAL grid patch averages ~61 brightness,
# ALT averages ~108, same patch -- confirms it's the per-cell bevel shading
# disappearing, not a global exposure change.
# Rather than pick one, each size pulls from whichever source suits it.
original_png = "Icon_2Kx2K_Source.png"
alt_png = "Icon_2Kx2KALT_Source.png"
output_ico = "AppIcon.ico"

# Sizes Windows expects for crisp icons, split by which source reads best.
LARGE_SIZES = [256, 128]   # from ORIGINAL, plain resize -- depth reads well here
SMALL_SIZES = [96, 64, 48, 40, 32, 24, 20, 16]         # from ALT, light sharpen -- flat base downsamples clean
OVERRIDE_32 = "icon-32.png"  # hand-pixeled crisp 32px - used directly if present

orig = Image.open(original_png).convert("RGBA")
alt = Image.open(alt_png).convert("RGBA")


def plain_resize(im, size):
    return im.resize((size, size), Image.Resampling.LANCZOS)


def light_sharpen_resize(im, size):
    """LANCZOS downsample, then a light contrast/sharpen touch-up. Alpha is
    preserved untouched -- only RGB gets contrast/sharpen treatment. Kept
    deliberately light: a heavier pass was needed on the old fringed render,
    but overshoots into ringing/moire on the flatter ALT source."""
    resized = im.resize((size, size), Image.Resampling.LANCZOS)
    rgb = resized.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.4)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=3))
    out = rgb.convert("RGBA")
    out.putalpha(resized.split()[3])
    return out


frames = [plain_resize(orig, s) for s in LARGE_SIZES]

def _small_frame(s):
    # per-size override: icon-16.png, icon-20.png etc. if present
    per_size = f"icon-{s}.png"
    if os.path.exists(per_size):
        im = Image.open(per_size).convert("RGBA")
        if im.size != (s, s):
            im = im.resize((s, s), Image.NEAREST)
        return im
    if s == 32 and os.path.exists(OVERRIDE_32):
        im = Image.open(OVERRIDE_32).convert("RGBA")
        if im.size != (32, 32):
            im = im.resize((32, 32), Image.NEAREST)
        return im
    # for sizes <32, derive crisp downscale from the hand-pixeled 32 if available
    if s < 32 and os.path.exists(OVERRIDE_32):
        base = Image.open(OVERRIDE_32).convert("RGBA")
        return base.resize((s, s), Image.NEAREST)
    return light_sharpen_resize(alt, s)

frames += [_small_frame(s) for s in SMALL_SIZES]
all_sizes = LARGE_SIZES + SMALL_SIZES

# Pillow's ICO writer: base image is frames[0] (256px), append_images supplies
# the rest as pre-rendered frames at their own native size -- it does NOT
# re-resize them, so our per-size, per-source processing above is preserved.
frames[0].save(
    output_ico,
    format="ICO",
    sizes=[(f.width, f.height) for f in frames],
    append_images=frames[1:],
)
# Nuitka's onefile splash-screen feature (see BuildEDFSE_Nuitka_OneFile.bat) reads its image
# straight out of this .ico's own base (256px, ORIGINAL-source) frame at build time - no separate
# splash asset to maintain here.

# annotate which sizes were overridden
overridden = [s for s in SMALL_SIZES if os.path.exists(f"icon-{s}.png") or (s <= 32 and os.path.exists(OVERRIDE_32))]
print(f"Icon saved with layers: {all_sizes} "
      f"(ORIGINAL for {LARGE_SIZES}, ALT+light sharpen for {SMALL_SIZES}"
      f"{', OVERRIDE for ' + str(overridden) + ' (NEAREST from icon-32.png)' if overridden else ''})")
