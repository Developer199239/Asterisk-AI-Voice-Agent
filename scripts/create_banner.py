#!/usr/bin/env python3
"""Create banner image with mascot behind title text."""

from PIL import Image, ImageDraw, ImageFont
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
mascot_path = os.path.join(project_root, "archived/AAVA-Mascots/aava.jpg")
output_path = os.path.join(project_root, "assets/banner.png")

# Banner dimensions (wide for README header)
BANNER_WIDTH = 800
BANNER_HEIGHT = 180

# Colors (GitHub dark theme)
BG_COLOR = (13, 17, 23)  # GitHub dark background
TEXT_COLOR = (255, 255, 255)  # White text

# Create banner
banner = Image.new('RGBA', (BANNER_WIDTH, BANNER_HEIGHT), BG_COLOR + (255,))

# Load and resize mascot
mascot = Image.open(mascot_path).convert('RGBA')
mascot_size = 140  # Size of mascot
mascot = mascot.resize((mascot_size, mascot_size), Image.Resampling.LANCZOS)

# Position mascot in center (will be behind text)
mascot_x = (BANNER_WIDTH - mascot_size) // 2
mascot_y = (BANNER_HEIGHT - mascot_size) // 2 - 10  # Slightly up

# Paste mascot with slight transparency for "behind" effect
mascot_with_alpha = mascot.copy()
# Make mascot semi-transparent so text appears "in front"
alpha = mascot_with_alpha.split()[3]
alpha = alpha.point(lambda p: int(p * 0.85))  # 85% opacity
mascot_with_alpha.putalpha(alpha)

banner.paste(mascot_with_alpha, (mascot_x, mascot_y), mascot_with_alpha)

# Add text on top
draw = ImageDraw.Draw(banner)

# Try to use a nice font, fall back to default
font_size = 48
try:
    # Try system fonts
    for font_name in ["/System/Library/Fonts/Helvetica.ttc", 
                      "/System/Library/Fonts/SFNSDisplay.ttf",
                      "/Library/Fonts/Arial.ttf"]:
        if os.path.exists(font_name):
            font = ImageFont.truetype(font_name, font_size)
            break
    else:
        font = ImageFont.load_default()
except:
    font = ImageFont.load_default()

text = "Asterisk AI Voice Agent"

# Get text bounding box for centering
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

text_x = (BANNER_WIDTH - text_width) // 2
text_y = (BANNER_HEIGHT - text_height) // 2

# Draw text with slight shadow for depth
shadow_offset = 2
draw.text((text_x + shadow_offset, text_y + shadow_offset), text, font=font, fill=(0, 0, 0, 128))
draw.text((text_x, text_y), text, font=font, fill=TEXT_COLOR)

# Save banner
banner.save(output_path, 'PNG')
print(f"Banner created: {output_path}")
