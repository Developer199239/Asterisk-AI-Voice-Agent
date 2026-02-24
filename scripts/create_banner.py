#!/usr/bin/env python3
"""Create banner image with transparent background, white text, and mascot overlap."""

from PIL import Image, ImageDraw, ImageFont
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
mascot_path = os.path.join(project_root, "archived/AAVA-Mascots/aava.jpg")
output_path = os.path.join(project_root, "assets/banner.png")

# Banner dimensions
BANNER_WIDTH = 800
BANNER_HEIGHT = 160

# Fully transparent background
banner = Image.new('RGBA', (BANNER_WIDTH, BANNER_HEIGHT), (0, 0, 0, 0))

def remove_white_bg(img):
    """Remove white background from image."""
    img = img.convert("RGBA")
    datas = img.getdata()
    new_data = []
    for item in datas:
        # If pixel is close to white, make it transparent
        if item[0] > 240 and item[1] > 240 and item[2] > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

# Load and process mascot
mascot = Image.open(mascot_path)
mascot = remove_white_bg(mascot)

# Resize mascot
mascot_height = 150
aspect = mascot.width / mascot.height
mascot_width = int(mascot_height * aspect)
mascot = mascot.resize((mascot_width, mascot_height), Image.Resampling.LANCZOS)

# Setup text
text = "Asterisk AI Voice Agent"
TEXT_COLOR = (255, 255, 255)  # White text for dark theme

# Use extra bold font if possible
font_size = 56
font = None
try:
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

draw = ImageDraw.Draw(banner)
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

# Overlap text over mascot
overlap = 25  # pixels
total_width = mascot_width + text_width - overlap

start_x = (BANNER_WIDTH - total_width) // 2

mascot_x = start_x
mascot_y = (BANNER_HEIGHT - mascot_height) // 2

text_x = mascot_x + mascot_width - overlap
text_y = mascot_y + (mascot_height - text_height) // 2 + 10  # aligned slightly lower like snapshot

# Draw mascot FIRST
banner.paste(mascot, (mascot_x, mascot_y), mascot)

# Draw text OVER the mascot
draw.text((text_x, text_y), text, font=font, fill=TEXT_COLOR)

# Save banner
banner.save(output_path, 'PNG')
print(f"Banner created: {output_path}")
