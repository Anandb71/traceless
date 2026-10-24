"""Open-vocabulary clue classes for the dense CLIP detector.

Each class maps to a ClueType (or a non-clue role). Text embeddings for these
prompts are precomputed once by scripts/build_prompts.py (CLIP ViT-L/14 text
tower, streamed into RAM and discarded) into traceless/data/clip_prompts.npz.
Changing this list requires re-running that script.
"""

TEMPLATES = [
    "a photo of {}.",
    "a cropped photo of {}.",
    "a close-up photo of {}.",
    "a street-level photo of {}.",
]

# name -> (role, prompts). role is a ClueType, or "person" (protected),
# or "background" (never a clue).
CLASSES: dict[str, tuple[str, list[str]]] = {
    "sign": ("text", ["a street sign", "a shop sign with lettering", "a billboard", "a traffic sign", "a neon sign"]),
    "plate": ("plate", ["a car license plate"]),
    "landmark": ("landmark", ["a famous landmark", "a monument", "a tall tower", "a statue", "a bridge"]),
    "building": ("building", ["a building facade", "a house", "an apartment building", "a church", "a skyscraper", "a storefront"]),
    "palm": ("vegetation", ["a palm tree"]),
    "tree": ("vegetation", ["a tree", "bushes", "a hedge"]),
    "field": ("vegetation", ["a field of crops", "grass", "a lawn"]),
    "road_marking": ("road_marking", ["road markings", "a painted crosswalk", "a road with lane lines"]),
    "pole": ("other", ["a utility pole with power lines", "a street lamp", "a traffic light"]),
    "vehicle": ("vehicle", ["a car", "a bus", "a taxi", "a truck", "a tram"]),
    "flag": ("flag", ["a national flag"]),
    "window": ("reflection", ["a reflective glass window", "a shop window reflection", "a mirror"]),
    "sunglasses": ("reflection", ["sunglasses"]),
    "mountain": ("terrain", ["mountains", "a hill"]),
    "water": ("terrain", ["the sea", "a lake", "a river", "waves on a beach"]),
    "sand": ("terrain", ["a sandy beach", "rocks on the coast"]),
    "person": ("person", ["a person", "a face", "people walking"]),
    "sky": ("background", ["the sky", "clouds"]),
    "ground": ("background", ["pavement", "asphalt", "a sidewalk", "the ground"]),
    "wall": ("background", ["a plain wall", "a ceiling", "a floor"]),
    "indoor": ("background", ["furniture", "a room interior", "a sofa", "a table"]),
}

LABELS = {
    "sign": "Sign",
    "plate": "License plate",
    "landmark": "Landmark",
    "building": "Architecture",
    "palm": "Palm trees",
    "tree": "Trees",
    "field": "Vegetation",
    "road_marking": "Road markings",
    "pole": "Street furniture",
    "vehicle": "Vehicle",
    "flag": "Flag",
    "window": "Reflective glass",
    "sunglasses": "Sunglasses",
    "mountain": "Terrain",
    "water": "Water / coastline",
    "sand": "Coastline",
}

DESCRIPTIONS = {
    "text": "Readable text narrows language, country and often the exact business.",
    "phone": "Phone numbers carry country and area codes.",
    "plate": "Plate format and colours identify country or state.",
    "landmark": "A recognisable landmark can pin the exact spot.",
    "building": "Architectural style, materials and window shapes are regional.",
    "vegetation": "Plant species reveal climate zone and continent.",
    "road_marking": "Line colours and road design differ by country.",
    "vehicle": "Vehicle models, taxis and buses are regional.",
    "flag": "Flags name the country outright.",
    "reflection": "Reflections can show what is behind the camera.",
    "terrain": "Coastline and terrain shapes are matchable.",
    "other": "Street furniture (poles, lamps, signals) varies by country.",
}
