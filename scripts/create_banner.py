#!/usr/bin/env python3
"""Create banner image with mascot on left, title on right."""

from PIL import Image, ImageDraw, ImageFont
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
mascot_path = os.path.join(project_root, "archived/AAVA-Mascots/aava.jpg")
output_path = os.path.join(project_root, "assets/banner.png")

# Banner dimensions (wide for README header)
BANNER_WIDTH = 700
BANNER_HEIGHT = 140

# Colors (GitHub dark theme - exact match)
BG_COLOR = (13, 17, 23)  # #0d1117 GitHub dark background
TEXT_COLOR = (255, 255, 255)  # White text

# Create banner with GitHub dark background
banner = Image.new('RGBA', (BANNER_WIDTH, BANNER_HEIGHT), BG_COLOR + (255,))

# Load mascot
mascot = Image.open(mascot_path).convert('RGBA')

# Resize mascot to fit nicely on left
mascot_height = 130
aspect = mascot.width / mascot.height
mascot_width = int(mascot_height * aspect)
mascot = mascot.resize((mascot_width, mascot_height), Image.Resampling.LANCZOS)

# Position mascot on left side, vertically centered
mascot_x = 20
mascot_y = (BANNER_HEIGHT - mascot_height) // 2

# Paste mascot (full opacity)
banner.paste(mascot, (mascot_x, mascot_y), mascot)

# Add text on right side
draw = ImageDraw.Draw(banner)

# Try to use a bold font
font_size = 42
font = None
try:
    # Try system fonts - prefer bold
    for font_name in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                      "/System/Library/Fonts/Helvetica.ttc",
                      "/Library/Fonts/Arial.ttf"]:
        if os.path.exists(font_name):
            font = ImageFont.truetype(font_name, font_size)
            break
    if font is None:
        font = ImageFont.load_default()
except:
    font = ImageFont.load_default()

text = "Asterisk AI Voice Agent"

# Get text bounding box
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

# Position text to the right of mascot, vertically centered
text_x = mascot_x + mascot_width + 30
text_y = (BANNER_HEIGHT - text_height) // 2

# Draw text
draw.text((text_x, text_y), text, font=font, fill=TEXT_COLOR)

# Save banner
banner.save(output_path, 'PNG')
print(f"Banner created: {output_path}")
