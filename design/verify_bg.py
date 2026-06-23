import numpy as np
from PIL import Image, ImageDraw
from assetforge.core.background import detect_background, remove_background
from assetforge.core.config import BackgroundConfig
from assetforge.core.io_utils import load_rgba
from assetforge.core import detect


def det(img):
    return detect_background(np.asarray(img).astype(np.float32))[0]


# градиент -> не checker
grad = Image.new("RGBA", (200, 200)); gp = grad.load()
for y in range(200):
    c = int(230 - (y / 199) * 60)
    for x in range(200):
        gp[x, y] = (c, c, c, 255)
print("ГРАДИЕНТ:", det(grad), "(ждём none/white, НЕ checker)")

# настоящая шахматка 255/204 -> checker
W, H = 200, 160; chk = Image.new("RGBA", (W, H)); px = chk.load()
for y in range(H):
    for x in range(W):
        px[x, y] = (255, 255, 255, 255) if (x // 16 + y // 16) % 2 == 0 else (204, 204, 204, 255)
print("ШАХМАТКА 255/204:", det(chk), "(ждём checker)")

# баннеры
im = load_rgba(open("testkrivo.png", "rb").read())
print("БАННЕРЫ detect:", det(im))
fg = remove_background(im, BackgroundConfig(mode="auto")).image
print("БАННЕРЫ split:", len(detect.split_objects(fg, mode="auto")), "(ждём 3)")
