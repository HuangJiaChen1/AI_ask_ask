import json
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont  # Import Pillow for image manipulation


# --- Data Models ---
class BoundingBox(BaseModel):
    label: str = Field(description="The name of the detected object")
    box_2d: list[int] = Field(description="Coordinates [ymin, xmin, ymax, xmax] normalized to 0-1000")


class DetectionResult(BaseModel):
    objects: List[BoundingBox]


# --- Main Logic ---
with open("config.json", "r") as f:
    config = json.load(f)

client = genai.Client(
    vertexai=True,
    project=config["project"],
    location=config["location"]
)

image_path = "1.jpg"  # Replace with your image

# Read bytes for Gemini
with open(image_path, "rb") as img_file:
    image_bytes = img_file.read()

# --- Generate Content ---
print("Analyzing image...")
response = client.models.generate_content(
    model=config["model_name"],
    contents=[
        types.Part.from_text(text="Give the segmentation masks for the objects. Output a JSON list of segmentation masks where each entry contains the 2D bounding box in the key 'box_2d', the segmentation mask in key 'mask', and the text label in the key 'label'. Use descriptive labels."),
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
    ],
    config=types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=DetectionResult
    )
)

# --- Visualization Logic ---
if response.parsed:
    # Open the original image using Pillow
    im = Image.open(image_path)
    width, height = im.size
    draw = ImageDraw.Draw(im)
    print(response)
    # Optional: Load a nice font (defaults to basic if not found)
    try:
        font = ImageFont.truetype("arial.ttf", size=int(height / 30))
    except IOError:
        font = ImageFont.load_default()

    print(f"Found {len(response.parsed.objects)} objects. Drawing boxes...")

    for obj in response.parsed.objects:
        # Gemini returns [ymin, xmin, ymax, xmax] in 0-1000 scale
        ymin_n, xmin_n, ymax_n, xmax_n = obj.box_2d

        # Convert to pixels
        ymin = int((ymin_n / 1000) * height)
        xmin = int((xmin_n / 1000) * width)
        ymax = int((ymax_n / 1000) * height)
        xmax = int((xmax_n / 1000) * width)

        # Draw the bounding box (Red, thickness 3)
        draw.rectangle([xmin, ymin, xmax, ymax], outline="red", width=3)

        # Draw the label with a background for readability
        text = obj.label

        # Calculate text size using font.getbbox (left, top, right, bottom)
        text_bbox = font.getbbox(text)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Draw red background for text
        draw.rectangle(
            [xmin, ymin - text_height - 4, xmin + text_width + 4, ymin],
            fill="red"
        )
        # Draw white text
        draw.text((xmin + 2, ymin - text_height - 4), text, fill="white", font=font)

    # Save and Show result
    output_filename = "annotated_output.jpg"
    im.save(output_filename)
    print(f"Saved annotated image to {output_filename}")
    im.show()  # Opens the image viewer
else:
    print("No objects found to draw.")