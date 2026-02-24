#!/usr/bin/env python3
"""Generate multiple banner samples for light and dark modes."""

from PIL import Image, ImageDraw, ImageFont
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
mascot_path = os.path.join(project_root, "archived/AAVA-Mascots/aava.jpg")
assets_dir = os.path.join(project_root, "assets")

def remove_white_bg(img):
    img = img.convert("RGBA")
    datas = img.getdata()
    new_data = []
    for item in datas:
        if item[0] > 240 and item[1] > 240 and item[2] > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
    img.putdata(new_data)
    return img

mascot = Image.open(mascot_path)
mascot = remove_white_bg(mascot)

mascot_height = 360
aspect = mascot.width / mascot.height
mascot_width = int(mascot_height * aspect)
mascot = mascot.resize((mascot_width, mascot_height), Image.Resampling.LANCZOS)

text = "Asterisk AI Voice Agent"
font_size = 140
font = None
font_paths = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf"
]
for font_name in font_paths:
    if os.path.exists(font_name):
        try:
            font = ImageFont.truetype(font_name, font_size, index=1 if "HelveticaNeue" in font_name else 0)
            break
        except: pass
if font is None: font = ImageFont.load_default()

temp_img = Image.new('RGBA', (1, 1))
temp_draw = ImageDraw.Draw(temp_img)
bbox = temp_draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]

padding_x = 40
padding_y = 40

def create_sample(name, bg_color, text_color, overlap):
    total_width = mascot_width + text_width - overlap + (padding_x * 2)
    total_height = max(mascot_height, text_height) + (padding_y * 2)
    
    # If transparent, bg_color is (0,0,0,0)
    banner = Image.new('RGBA', (total_width, total_height), bg_color)
    draw = ImageDraw.Draw(banner)
    
    mascot_x = padding_x
    mascot_y = (total_height - mascot_height) // 2
    
    text_x = mascot_x + mascot_width - overlap
    text_y = mascot_y + mascot_height - text_height - 60
    
    banner.paste(mascot, (mascot_x, mascot_y), mascot)
    draw.text((text_x, text_y), text, font=font, fill=text_color)
    
    out_path = os.path.join(assets_dir, name)
    banner.save(out_path, 'PNG')
    print(f"Created {name}")

# Transparent Backgrounds (Will automatically blend into GitHub's background)
create_sample("banner_dark_mode.png", (0, 0, 0, 0), (255, 255, 255, 255), overlap=70) # White text for dark mode
create_sample("banner_light_mode.png", (0, 0, 0, 0), (36, 41, 47, 255), overlap=70) # GitHub dark gray text for light mode

# Solid Backgrounds (Exactly matching GitHub's background colors to prevent any rendering quirks)
create_sample("banner_dark_solid.png", (13, 17, 23, 255), (255, 255, 255, 255), overlap=70) # GitHub Dark Background
create_sample("banner_light_solid.png", (255, 255, 255, 255), (36, 41, 47, 255), overlap=70) # GitHub Light Background

