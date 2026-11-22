"""The model of the project tree and the folder view: it never reads a folder itself. A folder is asked from the folder scout (one background
thread) and shows a "loading…" row until the answer is in; a newer ask for a folder to show cancels the older ones. Nothing in here waits on the
disk, so a click, a drag, a selection or a scroll is never held up by a slow folder (a network drive, Zygote's own environment folder).

It stands in for QFileSystemModel: filePath, isDir, index(path), setRootPath, setFilter, sort, directoryLoaded. A folder is watched while it is
loaded (one QFileSystemWatcher): when it changes it is read again and its rows are brought up to date."""
import functools
import tempfile
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QDateTime, QDir, QFileInfo, QFileSystemWatcher, QMimeData, QModelIndex, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider

from functional import core
from ui_ux.models import MarkedEngine, PageIcon, Tint

PATHS_FORMAT = 'application/x-zygote-paths'                    # what a drag started in the folder view carries: only Zygote's own views make it
WATCH_LIMIT = 150


class Node:
    __slots__ = ('path', 'name', 'is_dir', 'size', 'modified', 'parent', 'children', 'child_map', 'loaded', 'requested', 'row', 'kind', 'icon', 'holder')

    def __init__(self, path, name, is_dir, parent, kind='item'):
        self.path, self.name, self.is_dir, self.parent, self.kind = path, name, is_dir, parent, kind
        self.size, self.modified = 0, 0.0
        self.children, self.child_map = [], {}
        self.loaded, self.requested = False, False
        self.row = 0
        self.icon = None
        self.holder = None                                    # the "loading…" row of a folder that was asked for


class LazyModel(Tint, QAbstractItemModel):
    directoryLoaded = Signal(str)
    binDropped = Signal(list)                                  # paths dropped on the recycle bin row
    moveDropped = Signal(list, str)                            # (paths, folder): green items dropped on a folder; the window moves them
    renameWanted = Signal(str, str)                            # (path, new name): the person typed a new name in the view; the window does the rename
    HEADERS = ('Name', 'Size', 'Type', 'Date Modified')

    def __init__(self, scout, parent=None):
        super().__init__(parent)
        self.scout = scout
        self.project_root = None
        self.system_first = False                           # True (the workbench): at the project's top the system block comes before everything the person works on
        self.dirs_only = False
        self.with_bin = False                                  # the folder view shows the recycle bin as its first item (inside a project)
        self.sort_column, self.sort_order = 0, Qt.AscendingOrder
        self.root = Node('', '', True, None, 'root')
        self.root.loaded = True
        self.by_path = {'': self.root}
        self.keep = []                                         # nodes taken out of the rows stay alive while an old index may still point at them
        self.provider = QFileIconProvider()
        self.type_icons = {}                                   # file type icons without Windows' own overlays, by suffix
        self.marks = None                                      # {relative path: 'ok' | 'bad'} from the Git index (functional.git_marks); None until read
        self.marked = {}                                       # the icons with a mark drawn, by (path, state)
        self.bin_icon = None                                   # the recycle bin picture now shown (empty or full: the window says which)
        self.bin_pictures = (None, None)                       # (empty, full)
        self.root_path = ''
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.changed_on_disk)
        scout.ready.connect(self.arrived)
        scout.dropped.connect(self.cancelled)
        self.fill_roots()

    # ---- the QFileSystemModel look-alike ----------------------------------------------------------------------
    def setFilter(self, flags):
        self.dirs_only = not bool(flags & QDir.Files)

    def setResolveSymlinks(self, value):
        pass

    def resolveSymlinks(self):
        return False                                          # a shortcut shows under its own name

    def rootPath(self):
        return self.root_path

    def setRootPath(self, path):
        """Name the folder the views show; it is asked for (shown at once as "loading…", filled when the scout answers). Returns its index."""
        self.root_path = str(path)
        index = self.index(self.root_path)
        node = self.node(index)
        if node is not self.root and node.is_dir and not node.loaded:
            self.request(node, 'view')
        return index

    def filePath(self, index):
        node = self.node(index)
        return node.parent.path if node.kind in ('loading', 'bin') and node.parent is not None else node.path

    def isDir(self, index):
        node = self.node(index)
        return node.is_dir and node.kind == 'item'

    def fileName(self, index):
        return self.node(index).name

    def fileInfo(self, index):
        return QFileInfo(self.filePath(index))

    def is_loaded(self, path):
        node = self.find(path)
        return node is not None and node.loaded

    def set_bin_full(self, full):
        """The bin row shows the full picture when the trash holds something, else the empty one."""
        self.bin_icon = self.bin_pictures[1 if full else 0]
        root = self.index(self.root_path) if self.root_path else QModelIndex()
        if root.isValid() and self.with_bin:
            row = self.index(0, 0, root)
            if self.is_bin(row):
                self.dataChanged.emit(row, row)

    def is_bin(self, index):
        return index.isValid() and self.node(index).kind == 'bin'

    def sort(self, column, order=Qt.AscendingOrder):
        self.sort_column, self.sort_order = column, order
        for node in [item for item in self.by_path.values() if item.loaded]:
            self.rebuild(node, [self.entry_of(child) for child in node.children if child.kind == 'item'], force=True)

    # ---- nodes --------------------------------------------------------------------------------------------------
    def node(self, index):
        return index.internalPointer() if index.isValid() else self.root

    def fill_roots(self):
        for drive in QDir.drives():
            path = drive.absoluteFilePath()
            node = Node(path, path.rstrip('/') or path, True, self.root)
            node.row = len(self.root.children)
            self.root.children.append(node)
            self.root.child_map[path] = node
            self.by_path[path] = node

    def parts_of(self, path):
        parts = Path(path).parts
        found, current = [], ''
        for part in parts:
            current = (Path(current) / part).as_posix() if current else Path(part).as_posix()
            found.append(current)
        return found

    def find(self, path):
        return self.by_path.get(Path(path).as_posix() if str(path) else '')

    def make_node(self, path):
        """The node of a path, made (as a stub, with the ones above it) when it is not there yet."""
        path = Path(path).as_posix() if str(path) else ''
        if path in self.by_path:
            return self.by_path[path]
        node = self.root
        for part in self.parts_of(path):
            child = self.by_path.get(part)
            if child is None:
                child = Node(part, Path(part).name or part, True, node)
                at = len(node.children)
                self.beginInsertRows(self.index_of(node), at, at)          # the views and the proxy must hear of every new row (a silent insert crashed Qt when app_tree\\assets was opened)
                child.row = at
                node.children.append(child)
                node.child_map[part] = child
                self.by_path[part] = child
                if node.holder is not None:
                    node.holder.row = at + 1                                 # the "loading…" row stays last
                self.endInsertRows()
            node = child
        node.is_dir = Path(path).is_dir() if not node.loaded else node.is_dir
        return node

    # ---- asking and arriving ----------------------------------------------------------------------------------
    def request(self, node, tag='tree'):
        if node.requested or node.kind != 'item':
            return
        node.requested = True
        warm = self.scout.entries(node.path)
        if warm is not None:
            QTimer.singleShot(0, self, functools.partial(self.arrived, node.path))      # NOT now: a view calls this from inside expand() / fetchMore(), and changing the rows there crashed Qt
            return
        self.show_holder(node)
        self.scout.want(node.path, tag)

    def show_holder(self, node):
        """The "loading…" row, placed after the rows the folder has."""
        if node.holder is None and node.loaded is False:
            node.holder = Node(node.path + '/…', 'loading…', False, node, 'loading')
            at = len(node.children)
            parent = self.index_of(node)
            self.beginInsertRows(parent, at, at)
            node.holder.row = at
            self.endInsertRows()

    def drop_holder(self, node):
        if node.holder is not None:
            at = len(node.children)
            holder, node.holder = node.holder, None
            self.beginRemoveRows(self.index_of(node), at, at)
            self.keep.append(holder)
            self.endRemoveRows()

    def arrived(self, path):
        node = self.find(path)
        if node is None or node.kind != 'item' or not node.requested:
            return
        entries = self.scout.cache.get(str(path))
        if entries is not None:
            self.rebuild(node, entries[1])

    def cancelled(self, path):
        """An older ask for a folder to show was cancelled by a newer one: it is "not asked" again (it asks again when it is shown)."""
        node = self.find(path)
        if node is not None and not node.loaded:
            node.requested = False
            self.drop_holder(node)

    def entry_of(self, node):
        return (node.name, node.is_dir, node.size, node.modified)

    def value_key(self, entry):
        name, is_dir, size, modified = entry
        return {0: name.casefold(), 1: size, 2: (Path(name).suffix.casefold(), name.casefold()), 3: modified}[self.sort_column]

    def ordered(self, entries, node=None):
        """The folders first, then the files, each by the sort column (the other way round when descending). With system_first, the project's top shows
        the system block before them, in a fixed order that the sort setting does not change: the launcher (Zygote's shortcut), the blue folders (.git, .zygote,
        zip), the other system files and the green dot folders. Everything else is the person's work and follows the sort setting."""
        wanted = [entry for entry in entries if entry[1] or not self.dirs_only]
        backwards = self.sort_order == Qt.DescendingOrder
        pinned = []
        if self.system_first and node is not None and self.project_root is not None and Path(node.path).as_posix() == Path(self.project_root).as_posix():
            for name in core.system_block(self.project_root):
                pinned += [entry for entry in wanted if entry[0].lower() == name.lower()]
            wanted = [entry for entry in wanted if entry not in pinned]
            dots = sorted((entry for entry in wanted if entry[1] and entry[0].startswith('.')), key=lambda entry: entry[0].casefold())
            pinned += dots                                           # then the green dot folders (.pytest_cache ...), by name
            wanted = [entry for entry in wanted if entry not in dots]
        blue = []
        if node is not None and self.inside_project(node.path):          # in every folder of the project the blue folders come first, whichever way it is sorted
            for entry in wanted:
                rel = core.project_relative(self.project_root, Path(node.path) / entry[0])
                if entry[1] and rel and core.is_blue(rel):
                    blue.append(entry)
            wanted = [entry for entry in wanted if entry not in blue]
        blue.sort(key=self.value_key, reverse=backwards)
        folders = sorted((entry for entry in wanted if entry[1]), key=self.value_key, reverse=backwards)
        files = sorted((entry for entry in wanted if not entry[1]), key=self.value_key, reverse=backwards)
        return pinned + blue + folders + files

    def rebuild(self, node, entries, force=False):
        """Bring the rows of a folder up to date with what was read. Nodes that stay keep their place (selection, expanded arrows)."""
        ordered = self.ordered(entries, node)
        if node.loaded and not force and [self.entry_of(child) for child in node.children if child.kind == 'item'] == ordered:
            self.drop_holder(node)
            return
        old_children = list(node.children)
        keep_stubs = {child.name: child for child in old_children if child.kind == 'item'}
        holder = node.holder
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()                   # AFTER the signal: the proxy and the views make their indexes while it is sent, and every one of them must be moved
        final = []
        if self.with_bin and self.inside_project(node.path):
            bin_node = next((child for child in old_children if child.kind == 'bin'), None) or Node(node.path + '/​bin', 'Recycle bin', False, node, 'bin')
            final.append(bin_node)
        for name, is_dir, size, modified in ordered:
            path = node.path.rstrip('/') + '/' + name
            child = keep_stubs.pop(name, None) or Node(path, name, is_dir, node)
            child.is_dir, child.size, child.modified = is_dir, size, modified
            if child.path not in self.by_path:
                self.by_path[child.path] = child
            node.child_map[name] = child
            final.append(child)
        for gone in keep_stubs.values():
            self.by_path.pop(gone.path, None)
            node.child_map.pop(gone.name, None)
            self.keep.append(gone)
        if holder is not None:
            self.keep.append(holder)
            node.holder = None
        for row, child in enumerate(final):
            child.row = row
        node.children = final
        node.loaded = True
        node.requested = True
        new = []
        for old in persistent:
            pointer = old.internalPointer()
            if pointer is not None and pointer.parent is node:
                new.append(self.createIndex(pointer.row, old.column(), pointer) if pointer in final else QModelIndex())
            else:
                new.append(old)
        self.changePersistentIndexList(persistent, new)
        self.layoutChanged.emit()
        self.watch(node.path)
        self.directoryLoaded.emit(node.path)

    def inside_project(self, path):
        return self.project_root is not None and Path(path).as_posix().startswith(Path(self.project_root).as_posix())

    # ---- changes on disk ------------------------------------------------------------------------------------------
    def watch(self, path):
        if path and path not in self.watcher.directories() and len(self.watcher.directories()) < WATCH_LIMIT:
            self.watcher.addPath(path)

    def changed_on_disk(self, path):
        node = self.find(path)
        if node is not None and node.loaded:
            self.scout.want(node.path, 'reload', fresh=True)

    def reload(self, path):
        """Read a folder again now (after the program itself changed it)."""
        node = self.find(path)
        if node is not None and node.loaded:
            self.scout.want(node.path, 'reload', fresh=True)

    # ---- QAbstractItemModel -------------------------------------------------------------------------------------
    def index_of(self, node):
        if node is self.root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    def index(self, row, column=0, parent=QModelIndex()):
        if isinstance(row, str):                               # index(path): the node is made when it is not there yet
            node = self.make_node(row) if row else self.root
            return self.index_of(node)
        owner = self.node(parent)
        rows = owner.children
        if row < 0 or column < 0 or column >= len(self.HEADERS):
            return QModelIndex()
        if row < len(rows):
            return self.createIndex(row, column, rows[row])
        if row == len(rows) and owner.holder is not None:
            return self.createIndex(row, column, owner.holder)
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        owner = self.node(index).parent
        return self.index_of(owner) if owner is not None else QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() > 0:
            return 0
        owner = self.node(parent)
        return len(owner.children) + (1 if owner.holder is not None else 0)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def hasChildren(self, parent=QModelIndex()):
        owner = self.node(parent)
        if owner.kind != 'item' and owner is not self.root:
            return False
        if not owner.is_dir:
            return False
        if owner.loaded:
            return any(child.kind == 'item' and (child.is_dir or not self.dirs_only) for child in owner.children)
        return True

    def canFetchMore(self, parent):
        owner = self.node(parent)
        return owner is not self.root and owner.kind == 'item' and owner.is_dir and not owner.loaded and not owner.requested

    def fetchMore(self, parent):
        self.request(self.node(parent))

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        kind = self.node(index).kind
        if kind == 'loading':
            return Qt.ItemIsEnabled
        if kind == 'bin':
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        node = self.node(index)
        if node.is_dir and self.project_root is not None and core.can_move_into(self.project_root, node.path):
            flags |= Qt.ItemIsDropEnabled                      # a folder that green items may be dropped on
        if index.column() == 0 and self.project_root is not None and core.can_copy(self.project_root, self.node(index).path):
            flags |= Qt.ItemIsEditable                         # only what the person works on can be renamed (F2 or Rename in the menu); never the blue and system items
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        """The editor of a name commits here. The model changes nothing itself: the window renames the file, and the folder is read again."""
        if role != Qt.EditRole or not index.isValid() or index.column() != 0 or self.node(index).kind != 'item':
            return False
        self.renameWanted.emit(self.node(index).path, str(value))
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node, column = self.node(index), index.column()
        if node.kind == 'loading':
            return 'loading…' if role == Qt.DisplayRole and column == 0 else None
        if node.kind == 'bin':
            if column != 0:
                return None
            if role == Qt.DisplayRole:
                return 'Recycle bin'
            if role == Qt.DecorationRole:
                return self.bin_icon
            if role == Qt.ToolTipRole:
                return 'Recycle bin: drop the items you work on here to throw them away. Double-click to open it.'
            return None
        if column == 0:
            if role in (Qt.DisplayRole, Qt.EditRole):
                return node.name
            if role == Qt.ToolTipRole:
                return node.path
            if role == Qt.DecorationRole:
                if node.icon is None:
                    node.icon = self.file_icon(node.path)
                return self.with_mark(node.path, self.tinted(node.path, node.is_dir, role, node.icon))
            if role == Qt.ForegroundRole:
                return self.tinted(node.path, node.is_dir, role, None)
            return None
        if role == Qt.DisplayRole:
            if column == 1:
                return '' if node.is_dir else self.size_text(node.size)
            if column == 2:
                return 'File folder' if node.is_dir else (f'{Path(node.name).suffix[1:].upper()} File' if Path(node.name).suffix else 'File')
            if column == 3:
                return QDateTime.fromSecsSinceEpoch(int(node.modified)).toString('yyyy-MM-dd HH:mm') if node.modified else ''
        if role == Qt.TextAlignmentRole and column == 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def file_icon(self, path):
        """The icon of a file or folder WITHOUT any overlay of Windows (the marks are Zygote's own, see with_mark). A project's launcher shortcut is drawn from
        the project's own launcher.ico (read from the file each time the views are rebuilt), because Windows keeps the icon it first showed for a shortcut
        until the program is started again. The app_tree folder is the tree picture."""
        path = Path(path)
        root = getattr(self, 'project_root', None)
        picture = None if root is None else core.folder_picture(root, path)
        if picture is not None and picture.is_file():
            return QIcon(str(picture))
        if path.suffix.lower() == '.lnk' and core.is_live_launcher_name(path.name):
            made = path.parent / core.DOT / 'user' / 'launcher.ico'
            if made.is_file():
                return QIcon(str(made))
        if path.is_dir():
            return self.provider.icon(QFileIconProvider.Folder)
        suffix = path.suffix.lower()
        if suffix == '.ico':
            return QIcon(str(path))
        if suffix in ('.exe', '.lnk', '.scr'):                 # these carry a picture of their own: only the real file knows it
            return self.provider.icon(QFileInfo(str(path)))
        if suffix not in self.type_icons:                      # a file that does not exist is asked for by its type alone: no overlay
            nowhere = Path(tempfile.gettempdir()) / 'zygote-no-such-folder' / ('x' + suffix)
            found = self.provider.icon(QFileInfo(str(nowhere)))
            if PageIcon.blank(found):                           # Windows gave no picture for this type: the plain file picture, then Zygote's own page
                found = self.provider.icon(QFileIconProvider.File)
            self.type_icons[suffix] = PageIcon.icon() if PageIcon.blank(found) else found
        return self.type_icons[suffix]

    def set_marks(self, marks):
        """The Git state of the files, as read by the marks scout: the icons are drawn again with their marks."""
        self.layoutAboutToBeChanged.emit()
        self.marks = marks
        self.marked = {}
        self.layoutChanged.emit()

    def with_mark(self, path, icon):
        """The icon with Zygote's check or exclamation point on it, when the Git state of the path is known."""
        if not self.marks or not isinstance(icon, QIcon) or self.project_root is None:
            return icon
        rel = core.project_relative(self.project_root, path)
        state = None if rel is None else self.marks.get(rel)
        if state is None:
            return icon
        key = (path, state)
        if key not in self.marked:
            self.marked[key] = QIcon(MarkedEngine(icon, state))
        return self.marked[key]

    @staticmethod
    def size_text(size):
        for unit in ('bytes', 'KB', 'MB', 'GB'):
            if size < 1024 or unit == 'GB':
                return f'{size:.0f} {unit}' if unit == 'bytes' else f'{size:.1f} {unit}'
            size /= 1024
        return ''

    # ---- dragging out and the recycle bin row -------------------------------------------------------------------
    def mimeTypes(self):
        return ['text/uri-list', PATHS_FORMAT]

    def mimeData(self, indexes):
        data = QMimeData()
        paths = sorted({self.filePath(index) for index in indexes if index.isValid() and self.node(index).kind == 'item'})
        data.setUrls([QUrl.fromLocalFile(path) for path in paths])
        data.setData(PATHS_FORMAT, '\n'.join(paths).encode('utf-8'))
        return data

    def supportedDragActions(self):
        """A drag OUT of the workbench (to the desktop, Explorer, a folder) is a copy and nothing else: Explorer cannot turn it into a move, so the original never leaves the project."""
        return Qt.CopyAction

    def supportedDropActions(self):
        return Qt.MoveAction

    def dragged_paths(self, data):
        """The paths of a drag that Zygote's own folder view made; [] for anything else (the desktop, Explorer)."""
        if not data.hasFormat(PATHS_FORMAT):
            return []
        return bytes(data.data(PATHS_FORMAT)).decode('utf-8').split('\n')

    def is_folder_target(self, index):
        return index.isValid() and self.node(index).kind == 'item' and self.node(index).is_dir

    def canDropMimeData(self, data, action, row, column, parent):
        paths = self.dragged_paths(data)
        if not paths or not parent.isValid() or self.project_root is None:
            return False
        if self.node(parent).kind == 'bin':
            return all(core.can_trash(self.project_root, path) for path in paths)
        if not self.is_folder_target(parent):
            return False
        folder = Path(self.node(parent).path)
        return core.can_move_into(self.project_root, folder) and all(
            core.can_move(self.project_root, path) and Path(path) != folder and Path(path) not in folder.parents for path in paths)

    def dropMimeData(self, data, action, row, column, parent):
        if not self.canDropMimeData(data, action, row, column, parent):
            return False
        if self.node(parent).kind == 'bin':
            self.binDropped.emit(self.dragged_paths(data))
        else:
            self.moveDropped.emit(self.dragged_paths(data), self.node(parent).path)
        return True
