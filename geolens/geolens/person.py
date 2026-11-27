"""Person / face detection and masking (OpenCV Haar cascades, offline).

Selfies are the worst case for geolocation: the face fills the frame, reverse image
search matches faces instead of places, and the vision model sees skin instead of
skyline. GeoLens finds faces, estimates the body region below them, and produces a
masked copy plus background-only crops that are used for every later technique.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

_cascades = None


def _load():
    global _cascades
    if _cascades is None:
        import cv2
        if not hasattr(cv2, "CascadeClassifier"):
            raise RuntimeError(f"OpenCV {cv2.__version__} has no Haar cascades — install opencv-python-headless<5")
        base = cv2.data.haarcascades
        _cascades = [cv2.CascadeClassifier(base + f) for f in
                     ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml")]
    return _cascades


def detect(img: Image.Image) -> dict:
    import cv2
    w, h = img.size
    scale = 900 / max(w, h) if max(w, h) > 900 else 1.0
    small = img.resize((int(w * scale), int(h * scale))) if scale != 1 else img
    g = cv2.equalizeHist(cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY))
    faces = []
    min_side = max(40, int(min(small.size) * 0.08))
    for i, c in enumerate(_load()):
        for (x, y, fw, fh) in c.detectMultiScale(g, 1.1, 6, minSize=(min_side, min_side)):
            faces.append([x / scale, y / scale, fw / scale, fh / scale])
        if faces:
            break
    # keep only large faces (selfie / portrait subject), drop tiny background faces
    faces = [f for f in faces if f[2] >= 0.08 * min(w, h)]
    persons = []  # each person = head box + torso box
    for (x, y, fw, fh) in faces:
        head = [max(0, x - 0.02 * fw), max(0, y - 0.42 * fh), min(w, x + 1.02 * fw), min(h, y + 1.2 * fh)]
        torso = [max(0, x - 1.1 * fw), head[3], min(w, x + 2.1 * fw), h]
        persons.append([int(v) for v in head])
        persons.append([int(v) for v in torso])
    area = 0.0
    if persons:
        m = np.zeros((h, w), bool)
        for x0, y0, x1, y1 in persons:
            m[y0:y1, x0:x1] = True
        area = float(m.mean())
    return {"faces": [[int(v) for v in f] for f in faces], "persons": persons, "area": round(area, 3)}


def masked(img: Image.Image, persons: list[list[int]]) -> Image.Image:
    """Replace people with a heavily blurred version of the scene (keeps colour/light context)."""
    if not persons:
        return img
    blur = img.filter(ImageFilter.GaussianBlur(max(img.size) / 25))
    mean = Image.new("RGB", img.size, tuple(int(v) for v in np.asarray(img).reshape(-1, 3).mean(0)))
    fill = Image.blend(blur, mean, 0.55)
    mask = Image.new("L", img.size, 0)
    from PIL import ImageDraw
    d = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in persons:
        d.rounded_rectangle([x0, y0, x1, y1], radius=int((x1 - x0) * 0.35), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(12))
    return Image.composite(fill, img, mask)


def background_boxes(size: tuple[int, int], persons: list[list[int]]) -> list[tuple[str, list[int]]]:
    """Scene crops around people. Taken from the *masked* image, so they may overlap the blurred person."""
    w, h = size
    if not persons:
        return []
    heads, torsos = persons[0::2], persons[1::2]
    hx0, hx1 = min(p[0] for p in heads), max(p[2] for p in heads)
    hy0, hy1 = min(p[1] for p in heads), max(p[3] for p in heads)
    ty0 = min(p[1] for p in torsos)
    band = max(hy0, int((hy0 + hy1) / 2))  # down to mid-head: rooftop signs often sit just behind the head
    out = [("Upper scene", [0, 0, w, band]),
           ("Upper-left scene", [0, 0, int(w * 0.6), band]),
           ("Upper-right scene", [int(w * 0.4), 0, w, band])]
    if hx0 >= w * 0.15:
        out.append(("Left of person", [0, 0, hx0 + int(0.15 * (hx1 - hx0)), ty0]))
    if w - hx1 >= w * 0.15:
        out.append(("Right of person", [hx1 - int(0.15 * (hx1 - hx0)), 0, w, ty0]))
    return [(n, b) for n, b in out if (b[2] - b[0]) >= 0.15 * w and (b[3] - b[1]) >= 0.1 * h]


TEACH = ("People are noise for geolocation. Faces dominate reverse image search (it returns look-alike "
         "selfies) and pull the vision model away from the scene. Analysts crop to the background — GeoLens "
         "does that automatically: faces are detected, the body region is estimated and blurred out, and "
         "background-only crops are searched separately.")
