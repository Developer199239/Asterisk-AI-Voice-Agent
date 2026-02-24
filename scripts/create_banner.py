#!/usr/bin/env python3
"""Create high-resolution banner image with mascot overlap."""

from PIL import Image, ImageDraw, ImageFont
import os

# Paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
mascot_path = os.path.join(project_root, "archived/AAVA-Mascots/aava.jpg")
output_path = os.path.join(project_root, "assets/banner.png")

# Retina dimensions (2x)
BANNER_WIDTH = 1600
BANNER_HEIGHT = 360

# Fully transparent background
banner = Image.new('RGBA', (BANNER_WIDTH, BANNER_HEIGHT), (0, 0, 0, 0))

def remove_white_bg(img):
    """Remove white background from image smoothly."""
    img = img.convert("RGBA")
    datas = img.getdata()
    new_data = []
    for item in datas:
        # If pixel is close to white, make it transparent
        # Use a slightly stricter threshold to avoid white halos
        if item[0] > 245 and item[1] > 245 and item[2] > 245:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

# Load and process mascot
mascot = Image.open(mascot_path)
mascot = remove_white_bg(mascot)

# Resize mascot (make it larger and crisp)
mascot_height = 320
aspect = mascot.width / mascot.height
mascot_width = int(mascot_height * aspect)
mascot = mascot.resize((mascot_width, mascot_height), Image.Resampling.LANCZOS)

# Setup text
text = "Asterisk AI Voice Agent"
TEXT_COLOR = (255, 255, 255)  # White text

# Use the best available bold font for Mac
font_size = 110
font = None
font_paths = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf"
]

for font_name in font_paths:
    if os.path.exists(font_name):
        try:
            # Try to grab the Bold variant if it's a TTC
            font = ImageFont.truetype(font_name, font_size, index=1 if "HelveticaNeue" in font_name else 0)
            break
        except:
            pass

if font is None:
    font = ImageFont.load_default()

draw = ImageDraw.Draw(banner)
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

# Position text and mascot to overlap exactly like Snapshot 1
# Mascot is on the left, text overlaps the bottom right of the mascot circle
overlap = 60  # Pixels of overlap
total_width = mascot_width + text_width - overlap

start_x = (BANNER_WIDTH - total_width) // 2

mascot_x = start_x
mascot_y = (BANNER_HEIGHT - mascot_height) // 2

text_x = mascot_x + mascot_width - overlap
# Align text lower, overlapping the hand/circle area
text_y = mascot_y + mascot_height - text_height - 60

# Draw mascot FIRST
banner.paste(mascot, (mascot_x, mascot_y), mascot)

# Draw text OVER the mascot
draw.text((text_x, text_y), text, font=font, fill=TEXT_COLOR)

# Save banner
banner.save(output_path, 'PNG')
print(f"Banner created: {output_path}")
