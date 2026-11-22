"""Program icons: turn a picture into a square .ico inside the project (app_tree\\assets\\icons). Uses Qt's image classes only (no extra process,
no extra package). The saved file is hand-made data, never code."""
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter

from functional import core

BITMAP_SUFFIXES = ('.png', '.bmp', '.jpg', '.jpeg', '.gif', '.webp', '.tif', '.tiff')
ICON_SIDE = 256                                                 # the largest size an .ico file holds
MODES = ('pad', 'crop')


def is_bitmap(path):
    return Path(path).suffix.lower() in BITMAP_SUFFIXES


def load_picture(path):
    """A picture file as a QImage. Raises when Qt cannot read it."""
    image = QImage(str(path))
    if image.isNull():
        raise core.ZygoteError(f'{path} could not be read as a picture. Use a .ico, .png, .bmp, .jpg, .gif, .webp or .tif file.')
    return image


def square(image, mode):
    """The picture as a square: 'pad' puts it on a transparent square (nothing is lost), 'crop' cuts the centre square."""
    if mode not in MODES:
        raise core.ZygoteError(f'unknown icon mode: {mode} (use pad or crop)')
    width, height = image.width(), image.height()
    if width == height:
        return image.convertToFormat(QImage.Format_ARGB32)
    if mode == 'crop':
        side = min(width, height)
        return image.copy(QRect((width - side) // 2, (height - side) // 2, side, side)).convertToFormat(QImage.Format_ARGB32)
    side = max(width, height)
    canvas = QImage(side, side, QImage.Format_ARGB32)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage((side - width) // 2, (side - height) // 2, image)
    painter.end()
    return canvas


def icon_image(image, mode, side=ICON_SIDE):
    """The square picture scaled to `side` pixels: what is shown in the preview and what is written."""
    return square(image, mode).scaled(side, side, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def save_icon(project, image, mode, target):
    """Write the picture as a .ico at the target path in the project's icons folder (replacing a file there: the caller has asked first).
    Returns the path relative to the project."""
    target = core.clean_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not icon_image(image, mode).save(str(target), 'ICO'):
        raise core.ZygoteError(f'The icon could not be written: {target}')
    return target.relative_to(core.clean_path(project)).as_posix()
