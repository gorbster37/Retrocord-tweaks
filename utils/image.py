from io import BytesIO
import json
import os

import numpy as np
from PIL import Image
import requests
from sklearn.cluster import KMeans

from utils.custom_logger import logger

try:
    from config.config import EMBED_IMAGE_TIMEOUT_SECONDS
except ImportError:
    EMBED_IMAGE_TIMEOUT_SECONDS = 5


DEFAULT_DISCORD_COLOR = 0x5865F2


def cache_color(image_url, cache_file="image_cache.json", num_clusters=3):
    """Return a cached image color, or a safe default when an image cannot load."""
    cached_data = _load_cache(cache_file)
    if image_url in cached_data:
        return cached_data[image_url]

    try:
        response = requests.get(image_url, timeout=EMBED_IMAGE_TIMEOUT_SECONDS)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGB")
        img = img.resize((max(1, img.width // 2), max(1, img.height // 2)))
        pixels = np.array(img).reshape((-1, 3))
        filtered_pixels = pixels[np.linalg.norm(pixels, axis=1) > 50]
        if len(filtered_pixels) < num_clusters:
            raise ValueError("Image does not contain enough distinct pixels")

        kmeans = KMeans(n_clusters=num_clusters, random_state=0)
        kmeans.fit(filtered_pixels)
        cluster_centers = kmeans.cluster_centers_
        vibrant_color = cluster_centers[
            np.argmax(np.linalg.norm(cluster_centers, axis=1))
        ]
        color = int("0x{:02x}{:02x}{:02x}".format(*vibrant_color.astype(int)), 16)
    except (OSError, ValueError, requests.RequestException) as error:
        logger.warning("Could not determine Discord color for image: %s", error)
        return DEFAULT_DISCORD_COLOR

    cached_data[image_url] = color
    try:
        with open(cache_file, "w", encoding="utf-8") as cache_handle:
            json.dump(cached_data, cache_handle)
    except OSError as error:
        logger.warning("Could not save image color cache: %s", error)
    return color


def get_discord_color(image_url, cache_file="image_cache.json", num_clusters=3):
    return cache_color(image_url, cache_file, num_clusters)


def _load_cache(cache_file):
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as cache_handle:
            data = json.load(cache_handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Could not read image color cache: %s", error)
        return {}
