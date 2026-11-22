"""The icon of a project's launcher: Zygote's double red and blue ring with an empty middle, and the project's own program icon, smaller, in the middle.
A project without its own icon shows Zygote's own icon in the rings (never an empty circle); Zygote itself shows its icon alone, without rings. The ring picture (app_tree\\assets\\icons\\project-rings.png) is data: Zygote's own icon with the
helix and the two dots blanked. The result is one .ico (.zygote\\user\\launcher.ico) that the launcher shortcut points at."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

SIZE = 256
MIDDLE = 150                                                   # the project icon's side inside the rings (their empty disc is about 206 wide)


def largest_image(path):
    """The biggest picture inside an icon or image file, or a null QImage."""
    reader = QImageReader(str(path))
    best = QImage()
    count = max(reader.imageCount(), 1)
    for number in range(count):
        reader = QImageReader(str(path))
        reader.jumpToImage(number)
        image = reader.read()
        if not image.isNull() and (best.isNull() or image.width() > best.width()):
            best = image
    return best


def compose(rings, project_icon):
    """The rings (a picture file) with the project's icon (a file, or None) scaled into the middle. A QImage, 256 x 256."""
    base = largest_image(rings)
    if base.isNull():
        raise ValueError(f'The ring picture {rings} could not be read.')
    result = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawImage(0, 0, base.scaled(SIZE, SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    if project_icon is not None:
        inner = largest_image(project_icon)
        if inner.isNull():
            painter.end()
            raise ValueError(f'The program icon {project_icon} could not be read.')
        inner = inner.scaled(MIDDLE, MIDDLE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage((SIZE - inner.width()) // 2, (SIZE - inner.height()) // 2, inner)
    painter.end()
    return result


def write_icon(rings, project_icon, out):
    """Compose and save as an .ico. Returns the path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not compose(rings, project_icon).save(str(out), 'ICO'):
        raise ValueError(f'The icon {out} could not be written.')
    return out


def write_plain(icon, out):
    """The Zygote program itself: its own icon alone, full size, no rings (the rings mean "a project of Zygote"). Returns the path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image = largest_image(icon)
    if image.isNull():
        raise ValueError(f'The icon {icon} could not be read.')
    result = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    scaled = image.scaled(SIZE, SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter.drawImage((SIZE - scaled.width()) // 2, (SIZE - scaled.height()) // 2, scaled)
    painter.end()
    if not result.save(str(out), 'ICO'):
        raise ValueError(f'The icon {out} could not be written.')
    return out
