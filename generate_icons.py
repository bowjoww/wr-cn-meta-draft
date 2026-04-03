"""
ScrimVault Icon Generator
Creates all required favicon/icon sizes with the approved visual direction:
- Vault door concept with sword/controller element
- Palette: #071823 bg + #22d3ee cyan accent
- Wordmark: "Scrim" normal + "VAULT" bold uppercase
"""

from PIL import Image, ImageDraw, ImageFont
import math
import struct
import os

BG = (7, 24, 35)         # #071823
CYAN = (34, 211, 238)    # #22d3ee
CYAN_DIM = (20, 130, 150)
WHITE = (255, 255, 255)
DARK_SURFACE = (12, 35, 50)
VAULT_RING = (40, 180, 210)

OUTPUT_DIR = "app/static/branding"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def draw_vault_icon(draw, size, cx, cy):
    """Draw a stylized vault door icon."""
    r = size * 0.42

    # Outer vault ring
    ring_w = max(2, int(size * 0.06))
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=CYAN, width=ring_w
    )

    # Inner vault door body
    inner_r = r * 0.72
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=DARK_SURFACE, outline=CYAN_DIM, width=max(1, ring_w // 2)
    )

    # Vault spokes (4 locking bolts around the ring)
    bolt_r = r * 0.88
    bolt_size = max(2, int(size * 0.05))
    for angle_deg in [0, 90, 180, 270]:
        angle = math.radians(angle_deg)
        bx = cx + bolt_r * math.cos(angle)
        by = cy + bolt_r * math.sin(angle)
        draw.ellipse(
            [bx - bolt_size, by - bolt_size, bx + bolt_size, by + bolt_size],
            fill=CYAN
        )

    # Center handle / lock symbol: a small circle + cross
    handle_r = inner_r * 0.28
    draw.ellipse(
        [cx - handle_r, cy - handle_r, cx + handle_r, cy + handle_r],
        outline=CYAN, width=max(1, int(size * 0.03))
    )

    # Cross inside handle
    line_w = max(1, int(size * 0.025))
    hl = handle_r * 0.55
    draw.line([cx - hl, cy, cx + hl, cy], fill=CYAN, width=line_w)
    draw.line([cx, cy - hl, cx, cy + hl], fill=CYAN, width=line_w)

    # Sword element: diagonal line from top-right through center
    sword_len = inner_r * 0.55
    sx1 = cx + sword_len * math.cos(math.radians(-45))
    sy1 = cy + sword_len * math.sin(math.radians(-45))
    sx2 = cx + sword_len * math.cos(math.radians(135))
    sy2 = cy + sword_len * math.sin(math.radians(135))
    sword_w = max(1, int(size * 0.025))
    draw.line([sx1, sy1, sx2, sy2], fill=CYAN, width=sword_w)

    # Sword guard (crossguard perpendicular at center)
    guard_len = handle_r * 0.85
    gx1 = cx + guard_len * math.cos(math.radians(45))
    gy1 = cy + guard_len * math.sin(math.radians(45))
    gx2 = cx + guard_len * math.cos(math.radians(225))
    gy2 = cy + guard_len * math.sin(math.radians(225))
    draw.line([gx1, gy1, gx2, gy2], fill=CYAN, width=sword_w + 1)


def make_icon(size):
    img = Image.new("RGBA", (size, size), BG + (255,))
    draw = ImageDraw.Draw(img)

    # Rounded rect background
    radius = size // 6
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG + (255,))

    # Draw vault icon centered
    cx, cy = size / 2, size / 2
    draw_vault_icon(draw, size, cx, cy)

    return img


def add_wordmark(img, size, text_scrim="Scrim", text_vault="VAULT"):
    """Add wordmark below vault for large sizes (512+)."""
    draw = ImageDraw.Draw(img)

    try:
        font_normal = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", max(10, size // 10))
        font_bold = ImageFont.truetype("C:/Windows/Fonts/ariblk.ttf", max(10, size // 10))
    except Exception:
        font_normal = ImageFont.load_default()
        font_bold = font_normal

    # Measure combined text width
    bbox_s = draw.textbbox((0, 0), text_scrim, font=font_normal)
    bbox_v = draw.textbbox((0, 0), text_vault, font=font_bold)
    total_w = (bbox_s[2] - bbox_s[0]) + (bbox_v[2] - bbox_v[0]) + size // 40
    start_x = (size - total_w) // 2
    text_y = int(size * 0.84)

    draw.text((start_x, text_y), text_scrim, font=font_normal, fill=WHITE)
    draw.text((start_x + (bbox_s[2] - bbox_s[0]) + size // 40, text_y), text_vault, font=font_bold, fill=CYAN)

    return img


# ── Generate each size ──────────────────────────────────────────────────────

sizes = {
    "icon-1024.png": 1024,
    "icon-512.png": 512,
    "icon-192.png": 192,
    "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
    "favicon-16.png": 16,
}

for filename, size in sizes.items():
    img = make_icon(size)
    if size >= 512:
        img = add_wordmark(img, size)
    out_path = os.path.join(OUTPUT_DIR, filename)
    img.save(out_path, "PNG")
    print(f"Created {out_path} ({size}x{size})")


# ── favicon.ico: multi-size ICO (16, 32, 48) ────────────────────────────────

ico_images = []
for s in [16, 32, 48]:
    ico_images.append(make_icon(s))

ico_path = os.path.join(OUTPUT_DIR, "favicon.ico")
ico_images[0].save(
    ico_path,
    format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48)],
    append_images=ico_images[1:],
)
print(f"Created {ico_path} (multi-size ICO: 16, 32, 48)")

print("\nAll ScrimVault branding assets generated successfully!")
