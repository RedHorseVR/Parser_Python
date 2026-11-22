"""The file model Zygote's two views share. It marks the folders that a build ZIP never overwrites (.git, user,
credentials, logs, env) with a blue folder and blue name, so "protected" looks the same in the tree, the icon view and the log.

Only the yellow of a folder icon is recolored; the status overlays that TortoiseGit puts on icons keep their own colors."""
from pathlib import Path

from PySide6.QtCore import QPointF, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QIconEngine, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRegion
from PySide6.QtWidgets import QFileSystemModel

from functional import core
from ui_ux.theme import Theme


class TintedEngine(QIconEngine):
    """An icon that turns its source icon blue when (and only when) a size is asked for: Windows draws a folder icon through shell calls on the
    window's own thread, so every size that is made without being shown is time the tree does not answer."""

    def __init__(self, source, hue=None):
        super().__init__()
        self.source = source
        self.hue = hue

    def pixmap(self, size, mode, state):
        return FolderTint.pixmap(self.source, size, mode, state, self.hue)

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))

    def clone(self):
        return TintedEngine(self.source, self.hue)


class PageIcon:
    """The picture of a file when Windows gives none: a white page with a folded corner. Drawn once, 256 px, no file."""
    cached = None

    @staticmethod
    def blank(icon):
        """True when the icon has no picture at all (null, or every pixel transparent)."""
        if not isinstance(icon, QIcon) or icon.isNull():
            return True
        image = icon.pixmap(32, 32).toImage()
        return image.isNull() or not any(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height()))

    @classmethod
    def icon(cls):
        if cls.cached is None:
            pixmap = QPixmap(256, 256)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor('#5a5a5a'), 10))
            painter.setBrush(QColor('#ffffff'))
            painter.drawPolygon(QPolygonF([QPointF(48, 12), QPointF(160, 12), QPointF(216, 68), QPointF(216, 244), QPointF(48, 244)]))
            painter.setBrush(QColor('#c8c8c8'))
            painter.drawPolygon(QPolygonF([QPointF(160, 12), QPointF(160, 68), QPointF(216, 68)]))
            painter.end()
            cls.cached = QIcon(pixmap)
        return cls.cached


class MarkedEngine(QIconEngine):
    """An icon with Zygote's own small status mark at its lower left: a dark green check (nothing changed since the last commit) or a red exclamation
    point (changed). Each has a white outline so it shows on the green folders too. Drawn for every size that is asked for; no file is written."""
    SHARE = 0.30                                               # the mark's side as a share of the icon's
    MINIMUM = 11

    def __init__(self, source, state):
        super().__init__()
        self.source = source
        self.state = state

    def pixmap(self, size, mode, state):
        """The picture is first put on a canvas of exactly the size asked for (whatever size the source answered), then the mark is drawn LAST, on top, inside the
        part of the canvas the picture really covers: at the lower left of that part, so it is never cut off by the edge of the canvas and never underneath."""
        side = max(1, size.width()), max(1, size.height())
        base = QPixmap(*side)
        base.fill(Qt.transparent)
        painter = QPainter(base)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        picture = self.trimmed(self.source.pixmap(size, mode, state))
        if not picture.isNull():
            scaled = picture if picture.size() == base.size() else picture.scaled(base.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap((base.width() - scaled.width()) // 2, (base.height() - scaled.height()) // 2, scaled)
        covered = self.covered(base)
        painter.setRenderHint(QPainter.Antialiasing)
        box = max(self.MINIMUM, int(min(covered.width(), covered.height()) * self.SHARE))
        painter.translate(covered.left() + 1, covered.bottom() - box)
        if self.state == 'bad':
            MarkDrawing.exclamation(painter, box)
        else:
            MarkDrawing.check(painter, box)
        painter.end()
        return base

    SMALL = 0.6                                                # a picture that covers less than this share of its pixmap (both ways) is a small picture on a big canvas

    @classmethod
    def trimmed(cls, picture):
        """Windows can answer a large size with a big transparent pixmap that holds only a small icon in a corner (the 32 px picture is not scaled up). Such a
        pixmap is cut down to the part that has a picture, so the icon fills the size asked for like every other. Any other pixmap is returned as it is."""
        if picture.isNull():
            return picture
        picture.setDevicePixelRatio(1.0)                       # sizes are in pixels here, whatever the screen's scale
        found = QRegion(picture.mask()).boundingRect()
        if found.isEmpty() or found.width() >= picture.width() * cls.SMALL or found.height() >= picture.height() * cls.SMALL:
            return picture
        return picture.copy(found)

    @staticmethod
    def covered(pixmap):
        """The rectangle of the pixmap that has any picture in it (not transparent); the whole pixmap when there is none."""
        rect = QRegion(pixmap.mask()).boundingRect()
        return rect if not rect.isEmpty() else pixmap.rect()

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))

    def clone(self):
        return MarkedEngine(self.source, self.state)


class MarkDrawing:
    GREEN = QColor('#0b7a2b')
    RED = QColor('#e0201b')
    OUTLINE = QColor('#ffffff')

    @classmethod
    def stroke(cls, painter, path, box, color):
        for pen_color, extra in ((cls.OUTLINE, 0.26), (color, 0.0)):
            pen = QPen(pen_color, box * (0.20 + extra))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

    @classmethod
    def check(cls, painter, box):
        path = QPainterPath()
        path.moveTo(box * 0.18, box * 0.55)
        path.lineTo(box * 0.42, box * 0.80)
        path.lineTo(box * 0.86, box * 0.22)
        cls.stroke(painter, path, box, cls.GREEN)

    @classmethod
    def exclamation(cls, painter, box):
        bar = QPainterPath()
        bar.moveTo(box * 0.38, box * 0.14)
        bar.lineTo(box * 0.38, box * 0.58)
        dot = QPainterPath()
        dot.moveTo(box * 0.38, box * 0.86)
        dot.lineTo(box * 0.38, box * 0.87)
        cls.stroke(painter, bar, box, cls.RED)
        cls.stroke(painter, dot, box, cls.RED)


class FolderTint:
    cache = {}

    @classmethod
    def recolor(cls, pixmap, hue=None):
        """A copy of the pixmap with its yellow pixels turned to the sacred blue (or to another hue: the green of working folders)."""
        hue = Theme.SACRED_HUE if hue is None else hue
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                old, saturation, value, alpha = color.getHsv()
                if alpha and 25 <= old <= 75 and saturation >= 60:
                    color.setHsv(hue, int(saturation * 0.7), min(255, value + 5), alpha)
                    image.setPixelColor(x, y, color)
        return QPixmap.fromImage(image)

    @classmethod
    def pixmap(cls, icon, size, mode, state, hue=None):
        """The tinted pixmap of one size, made once per icon, size and hue."""
        key = (icon.cacheKey(), size.width(), size.height(), mode.value, state.value, hue)
        if key not in cls.cache:
            cls.cache[key] = cls.recolor(icon.pixmap(size, mode, state), hue)
        return cls.cache[key]

    @classmethod
    def icon(cls, icon, hue=None):
        return QIcon(TintedEngine(icon, hue))


class Tint:
    """What the models share: the blue of the sacred folders and the green of the items the person works on (one code path)."""
    project_root = None

    def is_sacred_path(self, path, is_dir):
        if self.project_root is None or not is_dir:
            return False
        try:
            parts = Path(path).relative_to(self.project_root).parts
        except ValueError:
            return False
        return core.is_blue('/'.join(parts))

    def is_protected_file(self, path, is_dir):
        """START_HERE.md at the project's top: a file shown in blue like the blue folders."""
        return self.project_root is not None and not is_dir and core.is_protected_file(core.project_relative(self.project_root, path))

    def is_sacred_folder(self, index):
        return self.is_sacred_path(self.filePath(index), self.isDir(index))

    def is_working_path(self, path):
        """A file or folder the person works on (green): inside the project, not Zygote's own structure, not a sacred folder."""
        return self.project_root is not None and (core.can_trash(self.project_root, path)
                                                  or core.is_editable_system_file(core.project_relative(self.project_root, path)))

    def is_app_tree_path(self, path):
        return self.project_root is not None and core.is_app_tree(self.project_root, path)

    def has_picture(self, path):
        return self.project_root is not None and core.folder_picture(self.project_root, path) is not None

    def tinted(self, path, is_dir, role, value):
        if self.is_app_tree_path(path):
            if role == Qt.ForegroundRole:
                return QBrush(QColor(Theme.WORK_TEXT))
            return value                                      # its icon is the tree picture (app_tree.png), never recoloured
        if role == Qt.DecorationRole and isinstance(value, QIcon) and is_dir and not self.has_picture(path):
            if self.is_sacred_path(path, is_dir):
                return FolderTint.icon(value)
            if self.is_working_path(path):
                return FolderTint.icon(value, Theme.WORK_HUE)
        if role == Qt.ForegroundRole:
            if self.is_sacred_path(path, is_dir) or self.is_protected_file(path, is_dir):
                return QBrush(QColor(Theme.SACRED_TEXT))
            if self.is_working_path(path):
                return QBrush(QColor(Theme.WORK_TEXT))
        return value


class ProjectModel(Tint, QFileSystemModel):
    """The drives of the Computer tree (Qt's own model: it knows the drive names)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_root = None
        self.setResolveSymlinks(False)                        # a shortcut (.lnk) shows under its own name, not its target's (Windows)

    def data(self, index, role=Qt.DisplayRole):
        value = super().data(index, role)
        if role in (Qt.DecorationRole, Qt.ForegroundRole):
            return self.tinted(self.filePath(index), self.isDir(index), role, value)
        return value


class ProjectOnlyProxy(QSortFilterProxyModel):
    """The Project location tree: the project's working folder is its top item and nothing outside it shows (the folders above it are only
    the way down to it). Rows are accepted when their path is the project, inside it, or one of the folders above it."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.project = Path(project)
        self.inside = self.project.as_posix()                      # the model gives paths with / even on Windows
        self.above = {path.as_posix() for path in self.project.parents}
        self.setRecursiveFilteringEnabled(False)

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        path = model.filePath(model.index(row, 0, parent))
        return path == self.inside or path.startswith(self.inside + '/') or path in self.above
