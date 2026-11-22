"""Zygote window: a focused toolbar (Run, Run tests, Commit) with the version stack on the right, a File menu for the rest,
folder tree left and icon view right (both zoomable on their own), and a log below, all separated by splitters.

Look rules (DOCTRINE): only things that can be pressed look like buttons; information is plain text; active text, if it
ever exists, is colored and underlined like a link. The look itself lives in theme.py.

The whole window takes drops: a build ZIP is unpacked over the project, a folder becomes the project (after a
confirmation). Nothing here watches files: the labels and views are read again when the window is shown, when it
becomes the active window and after each action.
"""
import datetime
import functools
import html
import re
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QDir, QEvent, QModelIndex, QPoint, QPointF, QRect, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QPixmapCache, QPolygonF, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QLabel, QListView, QMainWindow, QMenu,
                               QHBoxLayout, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabBar, QToolBar,
                               QTreeView, QVBoxLayout, QWidget)

import crashlog
from functional import core
from functional import cleanup, restructure
from functional.rebuild import Rebuild
import terminal
from ui_ux.commit_runner import CommitRunner
from ui_ux.agents_window import AgentsWindow
from ui_ux.ai_window import AIWindow
from ui_ux.panel_renderer import PanelWindow
from ui_ux.cli import CliButton, FolderButton
from ui_ux.help_window import HelpWindow
from ui_ux.folder_scout import FolderScout
from ui_ux.marks_scout import MarksScout
from ui_ux.debug_control import DebugControl
from ui_ux.code_window import DropToCode
from ui_ux.instance import InstanceGuard, bring_to_front, flash
from ui_ux.dialogs import AboutDialog, ConfirmProjectDialog, DeployDialog, MakeZipDialog, OpenProjectDialog, PreferencesDialog, ProjectSettingsDialog, RebuildDialog, RevertDialog, TestsDialog, ToolsDialog, CleanupDialog
from ui_ux.lazy_model import LazyModel
from ui_ux.models import FolderTint, ProjectModel, ProjectOnlyProxy
from ui_ux.toast import Toast
from ui_ux.panels import PictureButton, TitledPanel
from ui_ux.shell_tabs import BottomTabs, ShellPage, ShellWindow, TabGhost, close_button
from ui_ux.theme import Theme
from ui_ux.folder_views import FolderDetails, FolderIcons, PathBar, UpButton
from ui_ux.recycle import TrashWindow, bin_icon
from ui_ux.zoom import IconZoomFilter, TreeZoomFilter

ICON_FILE = core.ICON_FILE


def green_triangle():
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor('#2e9e44'))
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(QPolygonF([QPointF(7, 3), QPointF(7, 29), QPointF(28, 16)]))
    painter.end()
    return QIcon(pixmap)


def label(point_size, bold=False, dim=False, bright=False):
    text = QLabel('')
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(bold)
    text.setFont(font)
    text.setAlignment(Qt.AlignRight)
    if dim:
        text.setObjectName('dim')                                  # the theme gives it the quieter color
    if bright:
        text.setObjectName('bright')                               # and this one the bright color
    return text


class MainWindow(QMainWindow):
    HEADER_ICON = 64                                              # the program icon at the right of the header, in pixels

    working_space_ready = Signal()                                 # the project's folder is in the folder view and in the tree

    def __init__(self, launch_folder=None):
        super().__init__()
        self.project = None
        self.instance = None                                      # the InstanceGuard of this window (one window per project)
        self.ready_sent = False
        self.launch_folder = Path(launch_folder) if launch_folder else Path.cwd()   # where Zygote was started from
        self.setWindowTitle('Zygote')
        if ICON_FILE.is_file():
            self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.setAcceptDrops(True)
        self.resize(1000, 660)

        self.path_label = QLabel('')
        self.path_label.setTextFormat(Qt.RichText)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.computer_tree = self.make_tree()
        self.computer_tree.clicked.connect(self.show_computer_folder)
        self.tree = self.make_tree()                              # the project's own tree
        self.tree.clicked.connect(self.show_folder)
        self.icons = FolderIcons()
        self.icons.setViewMode(QListView.IconMode)
        self.icons.setResizeMode(QListView.Adjust)
        self.icons.setUniformItemSizes(True)
        self.icons.setStyleSheet('QListView { padding-top: 10px; }')   # the first row (the recycle bin) does not touch the title bar
        self.details = FolderDetails()                            # the same folder as a list with columns (View: Details)
        self.details.setRootIsDecorated(False)
        self.details.setUniformRowHeights(True)
        self.details.setSortingEnabled(True)
        for view in (self.icons, self.details):
            view.setDefaultDropAction(Qt.CopyAction)              # dragging out only copies (the model says so too): the original stays in the project
            view.setDragDropMode(QAbstractItemView.DragDrop)      # a file can be dragged OUT (Project settings drop box, the recycle bin); only Zygote's own drags come IN
            view.setSelectionMode(QAbstractItemView.ExtendedSelection)      # Shift = a range, Ctrl = add or remove, a box dragged from empty space
            view.setAcceptDrops(True)
            view.viewport().setAcceptDrops(True)
            view.refused.connect(self.say)
            view.restoreDropped.connect(lambda slots: self.guarded(functools.partial(self.restore_dropped, slots)))
            view.doubleClicked.connect(self.open_item)
            view.setEditTriggers(QAbstractItemView.SelectedClicked)     # the way of Windows: a second click on a selected item's name edits it; a double-click opens, and Qt cancels the edit for it
            QShortcut(QKeySequence('F2'), view, functools.partial(self.guarded, self.rename_current), context=Qt.WidgetShortcut)      # F2 = Rename in the menu: one path (begin_rename)
            view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.icons.customContextMenuRequested.connect(self.show_icons_menu)
        self.details.customContextMenuRequested.connect(self.show_details_menu)
        self.computer_zoom = TreeZoomFilter(self.computer_tree)  # Ctrl + wheel, each panel on its own
        self.tree_zoom = TreeZoomFilter(self.tree)
        self.icons_zoom = IconZoomFilter(self.icons)
        self.details_zoom = TreeZoomFilter(self.details)
        self.zoom_filters = {'computer': self.computer_zoom, 'tree': self.tree_zoom, 'icons': self.icons_zoom, 'details': self.details_zoom}

        self.computer_panel = TitledPanel('Computer', self.computer_tree)
        self.project_panel = TitledPanel('Project workspace', self.tree)
        self.root_button = QPushButton('Root')                    # jumps to the project's working folder from anywhere inside it
        self.root_button.setToolTip('Show the project\'s root folder')
        self.root_button.setObjectName('toolbutton')              # the same look as Stop and Clear
        self.root_button.setFixedHeight(22)                       # fits the bar: the panel title bars keep their height
        self.root_button.clicked.connect(lambda: self.guarded(self.go_root))
        self.project_panel.add_right_widget(self.root_button)
        self.project_panel.row.setAlignment(self.root_button, Qt.AlignVCenter)       # the colour of the bar all around it
        self.tree_proxy = None
        self.icon_stack = QStackedWidget()
        self.icon_stack.addWidget(self.icons)
        self.icon_stack.addWidget(self.details)
        self.icon_panel = TitledPanel('', self.icon_stack)       # its title names the folder shown
        self.folder_title = PathBar()                             # the clickable path; the folder in view is plain text
        self.folder_title.chosen.connect(lambda path: self.guarded(functools.partial(self.open_inside, path)))
        self.icon_panel.set_title_widget(self.folder_title)
        self.up_button = UpButton()                            # one level up (the picture app_tree\\assets\\ui\\up_folder.png); grey at the project's root
        up_picture = QIcon(str(core.ui_picture('up_folder.png')))                  # at the project's root (button off): a blank grey folder
        up_picture.addPixmap(QPixmap(str(core.ui_picture('up_folder_root.png'))), QIcon.Disabled)
        self.up_button.setIcon(up_picture)
        self.up_button.setObjectName('picturebutton')             # no button face: the folder sits on the grey of the bar
        self.up_button.setIconSize(QSize(24, 22))
        self.up_button.setToolTip('Up one folder')
        self.up_button.setFixedSize(28, 24)
        self.up_button.clicked.connect(lambda: self.guarded(self.go_up))
        self.up_button.setToolTip('Up one folder (drop green items here to move them up)')
        self.up_button.movedOut.connect(lambda paths: self.guarded(functools.partial(self.move_up, paths)))
        self.icon_panel.add_left_widget(self.up_button)
        self.before_zip = None                                    # the sort and view to go back to after the zip folder
        self.sort_box = QComboBox()
        self.sort_box.setToolTip('Sort the items of this folder')
        for text, column, descending in (('Sort: Name (A to Z)', 0, False), ('Sort: Name (Z to A)', 0, True),
                                         ('Sort: Date modified (oldest first)', 3, False), ('Sort: Date modified (newest first)', 3, True),
                                         ('Sort: Type (A to Z)', 2, False), ('Sort: Type (Z to A)', 2, True),
                                         ('Sort: Size (smallest first)', 1, False), ('Sort: Size (largest first)', 1, True)):
            self.sort_box.addItem(text, (column, descending))
        self.sort_box.currentIndexChanged.connect(self.sort_changed)
        self.view_box = QComboBox()
        self.view_box.setToolTip('Show the items as icons or as a list with details')
        self.view_box.addItem('View: Icons')
        self.view_box.addItem('View: Details')
        self.view_box.currentIndexChanged.connect(self.view_changed)
        self.icon_panel.add_right_widget(self.sort_box)           # Sort and View sit at the right end, beside the cmd, PowerShell and folder buttons
        self.icon_panel.add_right_widget(self.view_box)
        self.folder_button = FolderButton('Show the folder in view in the file manager')
        self.folder_button.clicked.connect(lambda: self.guarded(self.open_folder))
        self.icon_panel.add_right_widget(self.folder_button)
        self.cmd_button = CliButton('cmd', 'Open CLI here (Command Prompt). Right-click: as administrator.')
        self.powershell_button = CliButton('powershell', 'Open CLI here (PowerShell). Right-click: as administrator.')
        for button in (self.cmd_button, self.powershell_button):
            button.clicked.connect(functools.partial(self.press_cli, button.kind, False))
            button.admin_requested.connect(functools.partial(self.press_cli, button.kind, True))
            self.icon_panel.add_right_widget(button)
        self.left = QSplitter(Qt.Vertical)                       # drag the bar between the two trees
        self.left.addWidget(self.computer_panel)
        self.left.addWidget(self.project_panel)
        self.left.setSizes([220, 300])
        self.panes = QSplitter(Qt.Horizontal)
        self.panes.addWidget(self.left)
        self.panes.addWidget(self.icon_panel)
        self.panes.setSizes([300, 700])
        self.marks_scout = MarksScout(self)                      # the Git state of the files (the marks on the icons), read on one background thread
        self.marks_scout.ready.connect(self.marks_ready)
        self.marks_scout.failed.connect(self.say)
        self.scout = FolderScout()                               # the one background reader of folder lists (starts when the first folder is opened)
        self.waiting = set()                                     # what the start-up still waits for: the splash stays until it is empty
        self.trash_window = None                                 # the recycle bin window (made when first opened, non-modal)
        self.build_models()                                      # after the panels exist: they show the folder names

        self.log = QPlainTextEdit()                              # its own Ctrl + wheel zoom comes with Qt
        self.log.setReadOnly(True)

        self.terminal_factory = terminal.make_terminal            # tests replace this; the terminal itself is made when the first program runs
        self.ai_window = None                                     # the AI panel, made when first asked for
        self.layout_ai_window = None                              # the AI panel described as data (data/ai_panel.json), made when first asked for
        self.agents_window = None                                 # the AI agents panel, made when first asked for
        self.place_restored = False                               # the window goes back to its saved place once per run
        self.console = None                                       # the terminal view, made on the first run (nothing starts by itself)
        self.committer = None                                     # the CommitRunner, made on the first Commit
        self.console_page = QWidget()
        self.console_layout = QVBoxLayout(self.console_page)
        self.console_layout.setContentsMargins(0, 0, 0, 0)
        self.console_split = QSplitter(Qt.Horizontal)             # the Console on the left; the code window on the right while debugging (drag the bar)
        self.console_split.setChildrenCollapsible(False)
        self.console_layout.addWidget(self.console_split)
        self.debugger = DebugControl(self)
        self.console_page.setObjectName('consolepage')            # black from the start, like the terminal that fills it
        self.console_page.setAttribute(Qt.WA_StyledBackground, True)
        self.bottom_tabs = BottomTabs()                           # the log, the console, one tab per shell, and a "+" that makes the next shell
        self.bottom_tabs.tab_bar.setSelectionBehaviorOnRemove(QTabBar.SelectLeftTab)      # closing a shell never lands on the "+" tab
        self.bottom_tabs.addTab(self.log, 'Log')
        self.bottom_tabs.addTab(self.console_page, 'Console')
        self.bottom_tabs.setTabToolTip(1, 'With "Show console output" ticked (Settings > Project settings…), Run and Commit show the program here.')
        self.bottom_tabs.add_plus()
        self.bottom_tabs.setCurrentWidget(self.console_page)      # opens on the Console (debug or regular), not the Log
        self.log_clear_button = self.tool_button('console_clear.png', 'Clear (trash can): empty the log (nothing saved is touched); asks first')
        self.log_clear_button.clicked.connect(self.clear_log)
        self.stop_button = self.tool_button('console_stop.png', 'Stop (red stop sign): end the program that runs in the Console (press again to force it)')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(lambda: self.guarded(self.stop_console))
        self.console_clear_button = self.tool_button('console_clear.png', 'Clear (trash can): empty the Console (the next run starts on a clean screen); asks first')
        self.console_clear_button.clicked.connect(self.clear_console)
        self.code_button = QPushButton('Code')                    # shows or hides the code window (any project, debug mode or not)
        self.code_button.setToolTip('Show or hide the code window (it opens the debug entry point)')
        self.code_button.clicked.connect(lambda: self.guarded(self.debugger.toggle_window))
        self.shell_stop_button = self.tool_button('console_stop.png', 'Stop (red stop sign): end the shell of this tab')   # the two buttons of a shell tab act on the shell tab that is shown
        self.shell_stop_button.setEnabled(False)
        self.shell_stop_button.clicked.connect(lambda: self.guarded(self.stop_shell))
        self.shell_clear_button = self.tool_button('console_clear.png', 'Clear (trash can): empty this shell tab; asks first')
        self.shell_clear_button.clicked.connect(self.clear_shell)
        self.log_copy_button = QPushButton('Copy')                # Copy: everything in the tab (all the lines, also those scrolled out of sight) goes to the clipboard as text
        self.log_copy_button.setToolTip('Copy all the text of the Log to the clipboard')
        self.log_copy_button.clicked.connect(self.copy_log)
        self.console_copy_button = QPushButton('Copy')
        self.console_copy_button.setToolTip('Copy all the text of the Console (its whole scroll-back) to the clipboard')
        self.console_copy_button.clicked.connect(self.copy_console)
        self.shell_copy_button = QPushButton('Copy')
        self.shell_copy_button.setToolTip('Copy all the text of this shell tab (its whole scroll-back) to the clipboard')
        self.shell_copy_button.clicked.connect(self.copy_shell)
        self.tab_tools = QStackedWidget()                         # page 0 = Log's tools, page 1 = Console's tools (Code, a gap, Stop, Clear), page 2 = a shell tab's tools
        for buttons in ((self.log_copy_button, self.log_clear_button), (self.code_button, None, self.console_copy_button, self.stop_button, self.console_clear_button), (self.shell_copy_button, self.shell_stop_button, self.shell_clear_button)):
            tools = QWidget()
            tools_row = QHBoxLayout(tools)
            tools_row.setContentsMargins(0, 3, 6, 3)               # real buttons: the colour of the bar all around them
            for button in buttons:
                if button is None:
                    tools_row.addSpacing(16)                       # the gap between Code and Stop / Clear
                    continue
                button.setObjectName('toolbutton')
                button.setFixedHeight(22)
                tools_row.addWidget(button)
            self.tab_tools.addWidget(tools)
        self.last_tab = self.bottom_tabs.currentIndex()           # the tab shown before the "+" was pressed
        self.tab_tools.setCurrentIndex(min(self.last_tab, 1))     # the buttons of the tab it opens on (the Console)
        self.bottom_tabs.currentChanged.connect(self.bottom_tab_changed)
        self.bottom_tabs.tab_bar.rename_wanted.connect(self.bottom_tabs.rename_in_place)
        self.bottom_tabs.tab_bar.menu_wanted.connect(self.shell_menu)
        self.bottom_tabs.tab_bar.tear_wanted.connect(self.begin_tear)
        self.bottom_tabs.tab_bar.tear_moved.connect(self.move_tear)
        self.bottom_tabs.tab_bar.tear_dropped.connect(self.end_tear)
        self.tear_hold = None                                          # (page, name, colour, ghost) while a tab is carried
        self.torn = []                                                 # ShellWindow: shells dragged off the tabs
        self.bottom_tabs.setCornerWidget(self.tab_tools, Qt.TopRightCorner)
        self.rows = QSplitter(Qt.Vertical)                       # drag the bar to give the bottom panel more or less room
        self.rows.addWidget(self.panes)
        self.rows.addWidget(self.bottom_tabs)
        self.rows.setStretchFactor(0, 1)
        self.rows.setSizes([480, 110])

        self.today_label = label(10)                              # the date and the last change sit on the project-location line, at its right
        self.since_label = label(10, dim=True)                   # (the last change: under the version in the bar, see build_toolbar)
        self.since_label.setAlignment(Qt.AlignCenter)
        location = QHBoxLayout()
        location.addWidget(self.path_label, 1)
        location.addWidget(self.today_label)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(location)
        layout.addWidget(self.rows, 1)
        self.setCentralWidget(central)

        self.build_menu()
        self.build_toolbar()
        self.refresh()
        self.say('Drop a project folder to open it, or a build ZIP to unpack it over the open project.')

    # ---- building the window ---------------------------------------------------------------------------------
    def make_tree(self):
        tree = QTreeView()
        tree.setHeaderHidden(True)
        tree.setDragEnabled(False)                              # dragging out of a tree would open a project by accident
        tree.setDragDropMode(QAbstractItemView.NoDragDrop)
        return tree

    def build_models(self):
        """Fresh file models. Called at start and when the project's folder must be let go (renaming it)."""
        self.computer_model = ProjectModel(self)                 # folders only: the drives
        self.computer_model.setFilter(QDir.AllDirs | QDir.Hidden | QDir.NoDotAndDotDot)
        self.tree_model = LazyModel(self.scout, self)            # folders only: the project (read by the scout, never on this thread)
        self.tree_model.setFilter(QDir.AllDirs | QDir.Hidden | QDir.NoDotAndDotDot)       # hidden too: .git must show
        self.icon_model = LazyModel(self.scout, self)            # folders and files
        self.icon_model.system_first = True                      # the workbench: the system block (blue folders, launcher, .zygote) comes first at the top
        self.icon_model.setFilter(QDir.AllEntries | QDir.Hidden | QDir.NoDotAndDotDot)
        for model in (self.tree_model, self.icon_model):
            model.directoryLoaded.connect(self.folder_loaded)
        self.icon_model.moveDropped.connect(lambda paths, folder: self.guarded(functools.partial(self.move_paths, paths, folder)))     # green items dropped on a folder
        self.icon_model.binDropped.connect(lambda paths: self.guarded(functools.partial(self.trash_paths, paths)))     # a green item dropped on the bin row
        self.icon_model.renameWanted.connect(lambda path, name: self.guarded(functools.partial(self.rename_item, path, name)))      # a name typed in the view
        self.icon_model.directoryLoaded.connect(self.start_pending_rename)
        self.clipboard_paths = []                                                       # Copy: what Paste will copy (memory only, nothing is written anywhere)
        self.pending_rename = None                                                      # a new item waits here until its folder has been read; then its name opens for editing
        self.computer_tree.setModel(self.computer_model)
        for column in (1, 2, 3):
            self.computer_tree.hideColumn(column)
        self.icons.setModel(self.icon_model)
        self.details.setModel(self.icon_model)
        self.details.setColumnWidth(0, 260)
        self.sort_changed()
        self.show_computer()

    def show_computer(self):
        """No project: the top tree browses the drives, the project tree is empty and the icon view shows the drives."""
        self.computer_model.project_root = self.tree_model.project_root = self.icon_model.project_root = None
        self.computer_model.setRootPath('')
        self.computer_tree.setRootIndex(QModelIndex())
        self.tree.setModel(None)
        self.tree_proxy = None
        self.icon_model.setRootPath('')
        self.show_in_views(QModelIndex())
        self.icon_model.with_bin = False
        self.show_title(None)
        self.up_button.setEnabled(False)

    def release_folder(self):
        """Let go of the project's folder so Windows can rename it (Qt's file models hold folders open)."""
        old = (self.computer_model, self.tree_model, self.icon_model)
        self.computer_tree.setModel(None)
        self.tree.setModel(None)
        self.tree_proxy = None
        self.icons.setModel(None)
        self.details.setModel(None)
        for model in old:
            model.setParent(None)
            model.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def add_action(self, menu, text, action, shortcut=None, checkable=False):
        entry = QAction(text, menu)
        entry.setCheckable(checkable)
        if shortcut:
            entry.setShortcut(shortcut)
        if action is not None:
            entry.triggered.connect(lambda: self.guarded(action))
        menu.addAction(entry)
        return entry

    def build_menu(self):
        menu = self.menuBar().addMenu('&File')
        self.save_action = self.add_action(menu, '&Save layout', self.save_clicked, QKeySequence.Save)
        self.reload_action = self.add_action(menu, '&Reload', self.reload_menu, QKeySequence('F5'))
        self.restart_action = self.add_action(menu, 'Rest&art Zygote…', self.restart_menu)
        menu.addSeparator()
        quit_action = QAction('E&xit', self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        project = self.menuBar().addMenu('&Project')
        self.open_action = self.add_action(project, '&Open project…', self.choose_project, QKeySequence.Open)
        self.undo_action = self.add_action(project, '&Revert project…', self.revert_project, QKeySequence.Undo)
        for unused in (self.open_action, self.undo_action):      # no longer in the menu (Luis, Z 2.15.1): dropping a folder opens a project; Revert was dangerous and unused.
            project.removeAction(unused)                          # The actions and their code stay; with no menu they have no shortcut either.
        self.tests_action = self.add_action(project, 'Run &test suite…', self.show_tests)
        project.addSeparator()
        self.update_core_action = self.add_action(project, "&Update project's core", self.update_core)       # in its own group: it acts on the open project
        self.rebuild_action = self.add_action(project, 'Re&make launchers…', self.rebuild_project)         # part of the update group, for now
        project.addSeparator()
        self.history_action = self.add_action(project, 'Project h&istory', self.show_history)
        self.debug_menu = self.menuBar().addMenu('&Debug')           # always there (grayed out when it does not apply); "Debug mode" below is the one switch
        control = self.debugger
        self.debug_mode_action = self.add_action(self.debug_menu, 'Debug &mode', self.choose_debug_mode, checkable=True)    # the same state as Project settings > Run uses
        self.debug_menu.addSeparator()
        self.debug_actions = [                                       # only while Debug mode is on
            self.add_action(self.debug_menu, 'Step &over', lambda: control.press('step_over'), QKeySequence('F10')),
            self.add_action(self.debug_menu, 'Step &into', lambda: control.press('step_into'), QKeySequence('F11')),
            self.add_action(self.debug_menu, '&Continue', lambda: control.press('continue'), QKeySequence('F5')),
            self.add_action(self.debug_menu, '&Stop debug', control.stop, QKeySequence('Shift+F5')),
            self.add_action(self.debug_menu, 'Clear &breakpoints', control.clear_all),
            self.add_action(self.debug_menu, 'Breakpoints &list', control.list_breakpoints)]
        self.debug_menu.addSeparator()
        self.always_actions = [                                      # with any project, debug mode or not
            self.add_action(self.debug_menu, 'Show &code window', control.show_code),
            self.add_action(self.debug_menu, '&Language bundle…', control.language_bundle)]
        settings = self.menuBar().addMenu('&Settings')
        self.settings_action = self.add_action(settings, 'Project &settings…', self.project_settings)
        self.preferences_action = self.add_action(settings, 'Project &preferences…', self.preferences)
        self.tools_action = self.add_action(settings, '&Tools…', self.tools_settings)
        ai_menu = self.menuBar().addMenu('&AI')                       # between Settings and Help
        self.ai_action = self.add_action(ai_menu, 'AI &settings…', self.show_ai)          # global settings: everything below uses them
        ai_menu.addSeparator()
        self.layout_ai_action = self.add_action(ai_menu, 'AI panel (&layout)…', self.show_layout_ai)
        self.agents_action = self.add_action(ai_menu, 'AI &agents…', self.show_agents)
        self.zygote_menu = self.menuBar().addMenu('&Zygote')          # only while Zygote itself is open (see show_zygote_menu)
        self.allow_adding_action = self.add_action(self.zygote_menu, 'Allow &adding files to Zygote', self.toggle_allow_adding)
        self.allow_adding_action.setCheckable(True)
        self.allow_adding_action.setToolTip('Off: a folder dropped on Zygote opens (or starts) its own project window and nothing is copied into Zygote')
        self.zygote_menu.menuAction().setVisible(False)
        help_menu = self.menuBar().addMenu('&Help')
        self.zygote_help_action = self.add_action(help_menu, 'Zygote &help', self.show_zygote_help)
        self.project_help_action = self.add_action(help_menu, '&Project help', self.show_project_help)
        help_menu.addSeparator()
        self.about_action = self.add_action(help_menu, '&About Zygote…', self.show_about)

    def apply_look(self, light, outer):
        """Show the theme and the outer colour now (the live preview of Preferences, and the final choice)."""
        Theme.outer = Theme.check_outer(outer) if outer else None
        Theme.apply(QApplication.instance(), 'light' if light else 'dark')

    def ask_preferences(self):
        """Show Preferences (one panel, changes shown live). Returns (light, outer colour or None) when OK, None when cancelled (the look is
        put back). Tests replace this."""
        dialog = PreferencesDialog(Theme.mode == 'light', Theme.outer, Theme.colors()['window'], self, self.apply_look)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def preferences(self):
        """Settings > Project preferences…: theme and outer colour of THIS project; saved in the project, applied whenever it is opened."""
        project = self.need_project()
        answer = self.ask_preferences()
        if answer is None:
            self.apply_project_look()                            # cancelled: the saved look comes back
            return
        light, outer = answer
        self.apply_look(light, outer)
        core.save_look(project, light, Theme.outer)
        self.say(f'Project preferences: {Theme.mode} theme; outer colour {Theme.outer or "of the theme"} (saved in this project)')

    def apply_project_look(self):
        """Show the look saved in the open project (dark and the theme's own colour when it has none)."""
        light, outer = core.look(self.project)
        try:
            self.apply_look(light, outer)
        except ValueError as error:
            self.apply_look(light, None)
            raise core.ZygoteError(f'The outer colour saved in this project is wrong ({error}). Open Settings > Project preferences… and choose it again.') from error

    def reload_views(self):
        """File > Reload: read the folders, the icons and the version again (something outside Zygote may have changed them)."""
        shown = self.shown_folder()
        QPixmapCache.clear()                                     # Qt keeps drawn icons (with their TortoiseGit marks) between reloads
        FolderTint.cache.clear()
        self.release_folder()
        self.build_models()
        if self.project is not None:
            self.attach(self.project)
            if shown and Path(shown).is_dir():
                self.browse(shown)
        if self.project is not None:
            core.notify_shell(self.project)                      # Windows asks the icon overlays again
        self.refresh()
        self.say('Reloaded: the views read the disk again')

    def reload_menu(self):
        """File > Reload (F5): the views read the disk again. When Zygote's own files on disk are another version than the program running, say so and offer Restart."""
        self.reload_views()
        if core.restart_pending():
            self.offer_restart(f'The disk has {core.tool_version()}, this window runs {core.RUNNING_VERSION}')

    def ask_restart_now(self):
        """File > Restart Zygote: True when the person confirms. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Restart Zygote', 'Close Zygote and start it again on this project?\n\nThe whole program is loaded again from the files on disk.',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def restart_menu(self):
        self.need_project()                                      # the new Zygote opens the same project
        if self.ask_restart_now():
            self.restart()

    def show_about(self):
        AboutDialog(self).exec()

    def add_button(self, bar, text, tip, action, icon=None, box=None):
        """A real button on the toolbar whose press runs `action` through guarded(); an optional check box sits under it."""
        widget = QPushButton(text)
        if icon:
            widget.setIcon(icon)
        widget.setToolTip(tip)
        widget.clicked.connect(lambda: self.guarded(action))
        cell = QWidget()
        column = QVBoxLayout(cell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(widget)
        if box is not None:
            column.addWidget(box)
        column.addStretch(1)
        self.toolbar_cells[widget] = bar.addWidget(cell)
        return widget

    def tool_button(self, picture, tip):
        """A small picture button of the bottom panel's bar (the stop sign, the clear can). It has its own picture for the off state
        (<name>_off.png): Qt would otherwise grey the picture itself, mixing in the project's window colour, and the buttons would change
        colour from project to project. They belong to Zygote, so both states are Zygote's own files."""
        icon = QIcon(str(core.ui_picture(picture)))
        icon.addPixmap(QPixmap(str(core.ui_picture(picture.replace('.png', '_off.png')))), QIcon.Disabled)
        button = QPushButton()
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
        button.setFixedWidth(30)
        button.setToolTip(tip)
        return button

    def debugger_buttons(self):
        """(key, picture file, tooltip, action) of the debug toolbar buttons, in order: icons only, the tooltip says what each does and its key."""
        control = self.debugger
        return [('over', 'debug_step_over.png', 'Step over: run the next line, not going into calls (F10). Lit only while the debugger is stopped.', lambda: control.press('step_over')),
                ('into', 'debug_step_into.png', 'Step into: run the next line, going into calls (F11). Lit only while the debugger is stopped.', lambda: control.press('step_into')),
                ('restart', 'debug_restart.png', 'Restart the debugger from the top: asks first, ends the run that goes and starts the debug run again, stopped at its first line. Lit while a debug run exists.', control.restart),
                ('stop', 'debug_stop.png', 'Stop debugging: end the program that runs in the Console, like the Stop button there (Shift+F5). Lit only while something runs.', control.stop),
                ('clear', 'debug_clear.png', 'Clear all breakpoints of the project (the red X). Lit only when there is at least one.', control.clear_all)]

    def set_debug_states(self, running, stopped, breakpoints):
        """The debug buttons are lit only when they can do something: Run (green) when nothing runs or the debugger is stopped (then it is Continue), the
        steps only while stopped, Restart while a debug run exists, Stop while something runs, the red X when a breakpoint exists."""
        debug = core.current_mode(self.project) == 'debug' if self.project is not None else False
        self.run_button.setEnabled(not debug or not running or stopped)
        self.debug_buttons['over'].setEnabled(stopped)
        self.debug_buttons['into'].setEnabled(stopped)
        self.debug_buttons['restart'].setEnabled(running or stopped)
        self.debug_buttons['stop'].setEnabled(running)
        self.debug_buttons['clear'].setEnabled(breakpoints > 0)

    def show_debug_tools(self, debug):
        """Debug mode (one saved state, per project) decides what is active. The toolbar's debug buttons exist only in debug mode. The Debug menu is always
        there: its stepping entries are grayed out outside debug mode; Show code window, the Code button and Language bundle work whenever a project is open.
        F5 is Continue in debug mode, so File > Reload gives it up then."""
        for widget in self.debug_buttons.values():
            self.toolbar_cells[widget].setVisible(debug)
        has_project = self.project is not None
        self.debug_mode_action.setEnabled(has_project)
        self.debug_mode_action.blockSignals(True)
        self.debug_mode_action.setChecked(debug)
        self.debug_mode_action.blockSignals(False)
        for entry in self.debug_actions:
            entry.setEnabled(debug)
        for entry in self.always_actions:
            entry.setEnabled(has_project)
        self.code_button.setEnabled(has_project)
        self.bottom_tabs.setTabText(self.bottom_tabs.indexOf(self.console_page), 'Debug console' if debug else 'Console')
        self.reload_action.setShortcut(QKeySequence() if debug else QKeySequence('F5'))
        self.debugger.sync()

    def choose_debug_mode(self):
        """The Debug > Debug mode check box: the same saved state as the Debug / Runtime buttons of Project settings."""
        self.set_debug_mode(self.debug_mode_action.isChecked())

    def set_debug_mode(self, debug):
        project = self.need_project()
        core.set_run_mode(project, 'debug' if debug else 'runtime')
        if getattr(self, 'settings_dialog', None) is not None:
            self.settings_dialog.follow_mode('debug' if debug else 'runtime')
        self.refresh()
        self.say(f'Debug mode is {"ON" if debug else "off"}.')

    def build_toolbar(self):
        bar = QToolBar('Main')
        bar.setMovable(False)
        self.addToolBar(bar)
        self.toolbar_cells = {}                                  # button -> the toolbar entry that holds it (to show or hide it)
        self.run_button = self.add_button(bar, 'Run', 'Run it in the console: everything the program prints appears in the Console tab (Debug mode: the debugger runs to the next breakpoint)', self.run_project, green_triangle())
        self.debug_buttons = {}                                  # to the right of Run: only while the project is in debug mode
        for key, picture, tip, action in self.debugger_buttons():
            button = self.add_button(bar, '', tip, action, QIcon(str(core.ui_picture(picture))))
            button.setIconSize(QSize(22, 22))
            button.setFixedWidth(38)
            self.debug_buttons[key] = button
        self.debug_gap = QLabel('»')                              # a gap and a mark between the debug buttons and Commit / Make ZIP (debug mode only)
        gap_font = self.debug_gap.font()
        gap_font.setPointSize(16)
        gap_font.setBold(True)
        self.debug_gap.setFont(gap_font)
        self.debug_gap.setAlignment(Qt.AlignCenter)
        self.debug_gap.setFixedHeight(self.run_button.sizeHint().height())          # level with the buttons, not with the check box row under them
        self.debug_gap.setContentsMargins(14, 0, 14, 0)
        self.debug_gap.setToolTip('Left of this: the debug buttons. Right of it: Commit and Make ZIP.')
        gap_cell = QWidget()
        gap_column = QVBoxLayout(gap_cell)
        gap_column.setContentsMargins(0, 0, 0, 0)
        gap_column.addWidget(self.debug_gap)
        gap_column.addStretch(1)
        self.toolbar_cells[self.debug_gap] = bar.addWidget(gap_cell)
        self.commit_button = self.add_button(bar, 'Commit', 'Open TortoiseGit\'s commit window for the open project (app_tree\\bat\\COMMIT.bat)', self.commit)
        self.zip_button = self.add_button(bar, 'Make ZIP', 'Make a ZIP of the open project in its zip folder (asks what to include)', self.make_zip)
        self.deploy_button = self.add_button(bar, 'Deploy', 'Make one program (an exe) of the open project that runs on another computer: unpacks a <project>_home folder and starts it', self.deploy)
        self.name_label = label(22, bold=True, bright=True)      # the project name: bigger, in the middle of the bar
        self.name_label.setAlignment(Qt.AlignCenter)
        self.version_label = label(20, bold=True)                # the version: twice the old size (easy to read on a large screen), centered under the name
        self.version_label.setAlignment(Qt.AlignCenter)
        title = QWidget()                                        # the name over the version, in the middle of the bar
        column = QVBoxLayout(title)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.name_label)
        column.addWidget(self.version_label)
        column.addWidget(self.since_label)                       # the last change, centered under the version, readable on any bar colour
        self.icon_label = PictureButton()                       # the program icon, large, at the far right of the bar: pressing it is Run
        self.icon_label.clicked.connect(lambda: self.guarded(self.run_as_product))      # (a press: the saved arguments)
        self.icon_label.setFixedSize(self.HEADER_ICON + 12, self.HEADER_ICON)
        self.icon_label.setContentsMargins(0, 0, 12, 0)         # (not touching the window edge)
        self.icon_label.setAlignment(Qt.AlignCenter)            # the picture in the middle of the dotted drop target
        self.icon_label.accept_files(12)                        # files dropped on it run the program as product with them as the arguments (dotted line round the picture)
        self.icon_label.filesDropped.connect(lambda paths: self.guarded(functools.partial(self.run_as_product_with, paths)))
        for widget in (None, title, None, self.icon_label):
            if widget is None:
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                bar.addWidget(spacer)
            else:
                bar.addWidget(widget)

    # ---- state -----------------------------------------------------------------------------------------------
    ERROR_WORDS = re.compile(r'\b(error|errors|failed|failure|could not|cannot|can not|refused|not found)\b', re.IGNORECASE)

    def say(self, text):
        """One line in the Log. A line that tells of an error is red (the one colour for it in the theme), the rest keeps the ordinary text colour."""
        line = f'{datetime.datetime.now():%H:%M:%S}  {text}'
        if self.ERROR_WORDS.search(text):
            self.log.appendHtml(f'<span style="color:{Theme.colors()["error"]};">{html.escape(line)}</span>')
        else:
            self.log.appendPlainText(line)

    def say_protected(self, text, names):
        """A log line whose list of protected folders is drawn in the same blue as those folders in the views."""
        self.log.appendHtml(f'{datetime.datetime.now():%H:%M:%S}  {html.escape(text)} '
                            f'<span style="color:{Theme.SACRED_TEXT};">{html.escape(", ".join(names))}</span>')

    def say_rebuild(self, text):
        """A log line of the Rebuild output: teal, so it stands apart from the other messages in the Log tab."""
        self.log.appendHtml(f'<span style="color:{Theme.colors()["rebuild"]};">{datetime.datetime.now():%H:%M:%S}  {html.escape(text)}</span>')

    def show_error(self, text):
        QMessageBox.critical(self, crashlog.error_title(), text)

    def guarded(self, action):
        """Run a button's action; any failure is shown in full and logged, never swallowed."""
        try:
            action()
        except Exception as error:                                  # the message is the whole point
            self.say(f'ERROR: {error}')
            self.show_error(str(error))

    def show_program_icon(self):
        """The project's program icon (Zygote's own when it has none) in the title bar, the taskbar and, large, at the right of the header.
        When the saved icon file is gone, Zygote's own icon is shown and the error is raised (shown, never replaced silently)."""
        zygote = QIcon(str(ICON_FILE))
        self.icon_label.setToolTip('Run as product, or drop files on it')
        if self.project is None:
            self.icon_label.clear()
            self.setWindowIcon(zygote)
            return
        try:
            icon = QIcon(str(core.program_icon_file(self.project)))
        except core.ZygoteError:
            self.icon_label.setPixmap(zygote.pixmap(self.HEADER_ICON, self.HEADER_ICON))
            self.setWindowIcon(zygote)
            raise
        self.icon_label.setPixmap(icon.pixmap(self.HEADER_ICON, self.HEADER_ICON))
        self.setWindowIcon(icon)

    def need_project(self):
        if self.project is None:
            raise core.ZygoteError('No project is open. Drop a project folder on this window, or use Project > Open project….')
        return self.project

    def refresh(self):
        today = core.now()
        self.today_label.setText(f'{today:%a %Y-%m-%d}')
        if self.project is None:
            self.name_label.setText('')
            self.version_label.setText('VERSION: no project')
            self.since_label.setText('')
            self.path_label.setText('<b>PROJECT LOCATION:</b> none open')
            self.setWindowTitle(core.running_title())
            self.run_button.setText('Run')
            self.show_debug_tools(False)
            return
        version, since = core.track_version(self.project)
        name = core.project_name(self.project)
        self.name_label.setText(name)
        self.version_label.setText(f'VERSION: {version or "?"}')
        self.since_label.setText(f'last change {datetime.datetime.fromisoformat(since):%Y-%m-%d %H:%M}' if since else 'last change ?')
        self.path_label.setText(f'<b>PROJECT LOCATION:</b> {html.escape(str(self.project))}')
        debug = core.run_mode(self.project) == 'debug'
        self.run_button.setText('Run debug' if debug else 'Run')       # the Debug / Runtime buttons of Project settings
        self.show_debug_tools(debug)
        self.setWindowTitle(f'{name}, version {version or "?"} — {core.running_title()}')       # the project, then the tool that is RUNNING (not the one on disk)

    # ---- opening a project -----------------------------------------------------------------------------------
    def attach(self, folder):
        """Point the views at the project (the tree is now centered on it)."""
        folder = core.clean_path(folder)
        if not folder.is_dir():
            raise core.ZygoteError(f'Not a folder: {folder}. If the project was moved, a shortcut made before still points at the old place: '
                                   'open the project from where it is now and press OK in Settings > Project settings… to make its shortcut again.')
        self.leave_shells()                                      # shells of the project being left end (after asking), their tabs go
        self.save_all()                                          # the project being left keeps its bars, window place, colours and shell tabs
        self.clear_shell_pages()
        self.project = folder
        self.waiting = {'folder view', 'project tree'}           # the splash waits for these two and for nothing else
        self.ready_sent = False
        self.say('Loading the working space…')
        self.computer_model.project_root = self.tree_model.project_root = self.icon_model.project_root = folder
        self.icon_model.bin_pictures = (bin_icon(False), bin_icon(True))
        self.refresh_bin()
        self.icon_model.with_bin = True                          # the recycle bin is the first item of every folder of the project
        self.show_project_tree(folder)
        self.icon_model.setRootPath(str(folder))
        self.show_in_views(self.icon_model.index(str(folder)))
        self.show_title(folder)
        self.apply_project_look()                                 # the look belongs to the project
        self.apply_zoom()                                         # so does the size of the text and icons in each panel
        self.show_zygote_menu()
        self.show_program_icon()                                  # so does the program icon
        if self.ai_window is not None:
            self.ai_window.use_project(self.project)              # the open AI panel follows the project
        if self.layout_ai_window is not None:
            self.layout_ai_window.use_project(self.project)
        self.restore_window()                                     # and where its window was left (once per run: later projects stay where the window is)
        self.restore_layout()                                     # and the place of the drag bars
        self.restore_shells()                                     # and its shell tabs (not running: each has a Start button)
        self.refresh()
        self.marks_scout.ask(folder)                              # the check and exclamation marks: read again with every opening, Refresh and the end of a commit

    def marks_ready(self, answer):
        """The Git state of the project has been read: both views draw their marks (an answer for a project that is not open any more is dropped)."""
        project, marks = answer
        if self.project is None or str(self.project) != project or marks is None:
            return
        self.tree_model.set_marks(marks)
        self.icon_model.set_marks(marks)

    def window_place(self):
        """Where the window is now: position and size when it is not maximized (the window's normal place), and whether it is maximized."""
        place = self.normalGeometry() if self.isMaximized() else self.geometry()
        return {'x': place.x(), 'y': place.y(), 'w': place.width(), 'h': place.height(), 'maximized': self.isMaximized()}

    @staticmethod
    def on_a_screen(place):
        """True when the saved place still lands on a screen that is connected now (its title bar is inside a screen's usable area)."""
        title_bar = QRect(place['x'], place['y'], min(place['w'], 200), 40)
        return any(screen.availableGeometry().contains(title_bar) for screen in QGuiApplication.screens())

    def center_on_main_screen(self):
        area = QGuiApplication.primaryScreen().availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

    def restore_window(self):
        """First project of this run: put the window where this project left it. A saved place that is not on any screen now (another
        monitor, another PC) is not used: the window goes to the middle of the main screen. Never saved: it stays where it opened."""
        if self.place_restored:
            return
        self.place_restored = True
        place = core.window_place(self.project)
        if place is None:
            return
        if not self.on_a_screen(place):
            self.say('This project was last on a screen that is not here now: the window is in the middle of the main screen.')
            self.center_on_main_screen()
            return
        self.setGeometry(place['x'], place['y'], place['w'], place['h'])
        if place['maximized']:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)      # no show() here: at start-up the window is shown once it is ready

    def save_all(self):
        """Keep how this project's window looks: its place and size, the drag bars and the colours. Nothing to keep without a project."""
        if self.project is not None:
            core.set_window_place(self.project, self.window_place())
            self.save_layout()
            core.set_shell_tabs(self.project, self.shell_records())
            core.save_look(self.project, Theme.mode == 'light', Theme.outer)
            core.set_zoom_levels(self.project, {name: round(one.current_size(), 1) for name, one in self.zoom_filters.items()})

    def apply_zoom(self):
        """Put each panel at the text size this project left it at (a panel with nothing kept stays as it is)."""
        for name, size in core.zoom_levels(self.project).items():
            self.zoom_filters[name].set_size(size)

    def save_clicked(self):
        """File > Save: keep the layout now (the same keeping also happens by itself when the window closes)."""
        self.need_project()
        self.save_all()
        self.say('Saved: window place and size, drag bars and colours of this project.')

    def drag_bars(self):
        """The three drag bars by the names the project's record uses."""
        return {'left': self.left, 'panes': self.panes, 'rows': self.rows}

    def save_layout(self):
        """Keep where the drag bars are, in the open project (sticky: the next run of Zygote shows them the same). No project: nothing to keep."""
        if self.project is not None:
            core.set_window_layout(self.project, {name: bar.sizes() for name, bar in self.drag_bars().items()})

    def restore_layout(self):
        """Put the drag bars where this project had them (a project with none saved keeps the standard places)."""
        for name, sizes in core.window_layout(self.project).items():
            bar = self.drag_bars()[name]
            if len(sizes) != bar.count():
                raise core.ZygoteError(f'The saved position of the {name} bar has {len(sizes)} parts but the window has {bar.count()}.')
            bar.setSizes(sizes)

    def show_project_tree(self, folder):
        """The Project location tree: the working folder is its top item (nothing outside it shows). A drive root has nothing above it, so
        its folders are the top items."""
        old = self.tree_proxy
        self.tree_proxy = None
        if old is not None:
            old.deleteLater()
        if folder.parent == folder:
            self.tree.setModel(self.tree_model)
            self.tree_model.setRootPath(str(folder))
            self.tree.setRootIndex(self.tree_model.index(str(folder)))
        else:
            self.tree_proxy = ProjectOnlyProxy(folder, self)
            self.tree_proxy.setSourceModel(self.tree_model)
            self.tree.setModel(self.tree_proxy)
            self.tree_model.setRootPath(str(folder.parent))
            self.tree.setRootIndex(self.tree_proxy.mapFromSource(self.tree_model.index(str(folder.parent))))
            self.tree.expand(self.tree_proxy.mapFromSource(self.tree_model.index(str(folder))))
        for column in (1, 2, 3):
            self.tree.hideColumn(column)

    def go_root(self):
        """The Root button: show the project's working folder in the icon view and select it in the tree."""
        project = self.need_project()
        self.browse(project)
        if self.tree_proxy is not None:
            index = self.tree_proxy.mapFromSource(self.tree_model.index(str(project)))
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

    def project_runs_elsewhere(self, folder):
        """True (said in the Log) when another window already holds this project: that window was told to come forward and nothing is opened here."""
        if self.instance is not None and self.instance.key == core.clean_path(folder):
            return False
        if InstanceGuard.ask_running(core.clean_path(folder)):
            self.say(f'{core.clean_path(folder).name} is already open in another window: it was brought to the front.')
            return True
        return False

    def hold_instance(self, key):
        """This window is the one for this project (or the bare Zygote): listen for a second start. The earlier name is let go."""
        if self.instance is not None and self.instance.key == key:
            return
        guard = InstanceGuard(key, self)
        if not guard.claim():
            self.say('This window could not take its single-instance name: a second window for the same project may open.')
            guard.deleteLater()
            return
        guard.raised.connect(self.come_forward)
        guard.ai_requested.connect(self.ai_requested)
        if self.instance is not None:
            self.instance.release()
            self.instance.deleteLater()
        self.instance = guard

    def come_forward(self):
        """A second start found this window: it comes to the front and flashes once, so it is clear that something happened."""
        bring_to_front(self)
        flash(self)

    def open_project(self, folder, before_questions=None):
        """Open a folder that was already confirmed once (the --project flag of a shortcut). before_questions: called once the project is
        attached and the window is in its place, before anything is asked (start-up shows the window there)."""
        if self.project_runs_elsewhere(folder):
            if before_questions is not None:
                before_questions()
            return
        self.attach(folder)
        self.hold_instance(core.clean_path(folder))
        self.say(f'Opened {self.project}')
        if before_questions is not None:
            before_questions()
        self.note_open()
        if core.LAUNCHER_IS_SHORTCUT:
            self.stamp_shortcut()                                 # the launcher and the shortcut are made again each time (quick): nothing to remember to do
        else:
            self.hint_shortcut()
        self.offer_adoption()

    def hint_shortcut(self):
        """Information only (nothing is made): where the way to start Zygote on this project comes from."""
        if not core.find_launchers(self.project):
            self.say(f'There is no "{core.launcher_name(self.project)}" here. Project > Remake launchers… makes it (a project does not need one).')

    def ask_update_core(self, project, old, new):
        """One short question. True for yes. Tests replace this. `new` is the Zygote on the disk; a Yes that brings in another version than the
        one running also restarts Zygote on this project (said in the second line)."""
        text = f'Update {project.name} from {old or "no copy"} to {new}?'
        if new != core.RUNNING_VERSION:
            text += '\nZygote restarts to run it.'
        return QMessageBox.question(self, "Zygote \u2014 update the project's core", text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def update_core(self):
        """Project > Update project's core: when the project's copy, the disk and the running Zygote are all the same version a toast says so and nothing
        is asked. Otherwise one question; Yes copies into .zygote\\core and, when the disk has another version than the one running, starts the new Zygote
        with --updated (it says "Update complete")."""
        self.need_project()
        old, new = core.core_version(self.project), core.installed_version()
        if self.project == core.ZYGOTE_ROOT:                      # the core itself: nothing to copy, but the launcher and the tidying are still its update
            self.say('This is the installed Zygote itself: nothing is copied. Its launcher is made again and what an earlier Zygote left is tidied.')
            self.refresh_structure()
            self.refresh()
            self.show_toast('Update complete')
            return True
        if core.core_is_current(self.project):
            self.show_toast('Already updated')
            return False
        if not self.ask_update_core(self.project, old, new):
            self.say('Cancelled: the project\'s Zygote was not changed')
            return False
        external = core.external_console(self.project)
        count = core.update_core(self.project)
        after = core.external_console(self.project)
        self.say(f'Console setting "Show external console output": {"on" if external else "off"} before the update, {"on" if after else "off"} after.')
        self.say(f'{self.project.name}: Zygote {new} copied into .zygote\\core ({count} files; it was {old or "not there"}).')
        renamed = core.rename_launcher(self.project)             # the launcher carries the project's name (VFlow_Zide.lnk); only a rename
        if renamed:
            self.say(renamed)
        self.refresh_structure()
        self.refresh()
        if core.restart_pending():                                 # the Yes also covered this (the question said so): one restart
            self.say(f'Restarting Zygote to run {new} ({"in a visible console that stays open" if after else "minimized, closing itself"}).')
            self.restart(updated=True)
        else:
            self.show_toast('Update complete')
        return True

    def ask_cleanup(self, items):
        """The files an earlier Zygote left (ticked). Returns the ones to throw away; [] for Cancel. Tests replace this."""
        dialog = CleanupDialog(items, self)
        return dialog.chosen() if dialog.exec() == QDialog.Accepted else []

    def ask_restructure(self, moves):
        """The older layout: one question that names the folders that move into the app tree. True for yes. Tests replace this."""
        names = ', '.join(Path(source).name for source, target in moves)
        text = (f'Z 2.15 keeps {names} in the app tree (app_tree), next to app, and leaves .zygote to the machine.\n\nMove them now? Nothing is deleted or replaced. '
                'Git will show the moves as renames: commit them afterwards.')
        return QMessageBox.question(self, 'Zygote \u2014 the app tree', text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def restructure(self):
        """The one-time move of an older project into the app tree (see functional/restructure.py), after one question. The views let go of the folders first
        (Windows cannot rename a folder that is being watched) and read the project again afterwards."""
        moves = restructure.plan(self.project)
        if not moves:
            return
        if not self.ask_restructure(moves):
            self.say('The folders stay where they are: this project keeps the older layout until it is updated (Commit, Help and Tests look in the app tree).')
            return
        self.release_folder()
        try:
            lines = restructure.run(self.project)
        finally:
            self.build_models()
            self.attach(self.project)
        for line in lines:
            self.say(line)

    def refresh_structure(self):
        """The rest of an update of the core, with no menu to pick from: the older layout moves into the app tree (asked once), the launcher and the shortcut
        are made again (the project's icon in the rings), what an earlier Zygote left is tidied (the system's own silently; anything the person could use is
        asked about once, all ticked)."""
        self.restructure()
        if core.LAUNCHER_IS_SHORTCUT:
            self.stamp_shortcut()
        found = cleanup.find(self.project)
        for line in cleanup.remove_system([one for one in found if one.owner == 'system']):
            self.say(line)
        for line in cleanup.skipped(self.project):
            self.say(line)
        mine = [one for one in found if one.owner == 'user']
        if mine:
            for line in cleanup.remove_user(self.project, self.ask_cleanup(mine)):
                self.say(line)

    def drop_project(self, path):
        """A folder dropped on Zygote: it is opened as before, and when its own copy of Zygote is not this version the update is offered."""
        self.begin_project(path)
        folder = core.clean_path(path)
        if self.project == folder and folder != core.ZYGOTE_ROOT and core.core_version(folder) != core.installed_version():
            self.update_core()

    def ask_adopt(self, project, missing):
        """Offer to add the .zygote tree to a folder. True for yes. Tests replace this."""
        text = (f'{project.name} has no complete .zygote folder yet.\n\nAdd it? {len(missing)} files will be added '
                f'(READMEs, placeholder launchers, a starting version). Nothing that is already in the folder is changed or replaced.')
        return QMessageBox.question(self, 'Zygote \u2014 add the Zygote folder', text) == QMessageBox.Yes

    def offer_adoption(self):
        """Once per folder: offer to add the baseline. Yes adds only what is missing; No is remembered on this computer."""
        project = self.project
        if not core.should_offer_adoption(project):
            return
        if not self.ask_adopt(project, core.missing_baseline(project)):
            core.decline_adoption(project)
            self.say('The .zygote folder was not added (Zygote will not ask again for this folder).')
            return
        report = core.adopt_project(project, core.project_name(project))
        self.note(f'Added the .zygote folder ({len(report["added"])} files); version {report["version"]}')
        if report['outer']:
            self.apply_project_look()                            # the new project's own colour
            self.say(f'{project.name} got its own colour {report["outer"]} (Settings > Project preferences… changes it).')
        self.refresh()
        self.say(f'Added {len(report["added"])} files to {project.name}\\.zygote; version {report["version"]}'
                 + ('' if report['version_written'] else ' (kept)') + f'; START_HERE.md {report["start_here"]}')

    def choose_project(self):
        dialog = OpenProjectDialog(self, self.launch_folder)
        if dialog.exec() == QDialog.Accepted:
            self.begin_project(dialog.folder)

    def start_here(self):
        """At startup without --project: a folder Zygote already knows opens by itself; any other asks once."""
        if core.is_known_project(self.launch_folder):
            self.open_project(self.launch_folder)
        else:
            self.choose_project()

    def ask_project(self, folder, name, title):
        """Show the confirmation. Returns (name, rename_folder) or None. Tests replace this."""
        dialog = ConfirmProjectDialog(folder, name, self, title)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def begin_project(self, folder):
        """Confirm a chosen folder as the project (git note, name, optional folder rename), then open it."""
        folder = core.clean_path(folder)
        if not folder.is_dir():
            raise core.ZygoteError(f'Not a folder: {folder}')
        if core.is_known_project(folder):                       # Zygote recorded its confirmed name here before: nothing to ask
            self.open_project(folder)
            return
        if self.project_runs_elsewhere(folder):
            return
        answer = self.ask_project(folder, folder.name, 'Zygote — confirm the project folder')
        if answer is None:
            self.say('Cancelled: no project opened')
            return
        name, rename = answer
        if rename and name != folder.name:
            folder = core.rename_folder(folder, name)            # nothing holds the folder yet: the views point elsewhere
            self.say(f'Renamed the folder to {folder}')
        self.attach(folder)
        self.hold_instance(core.clean_path(folder))
        core.set_project_name(folder, name)
        self.refresh()
        self.say(f'Project "{name}" opened: {folder}' + ('' if core.has_git(folder) else '  (no .git here)'))
        self.stamp_shortcut()
        self.note_open()
        self.offer_adoption()

    def project_settings(self):
        """Settings > Project settings…: opens the panel. It is not modal (a file can be dragged into it from the icon view).
        An older panel is closed and dropped first: a panel is never reused after it closed (a reused closed panel was the 'already deleted' error)."""
        project = self.need_project()
        old = getattr(self, 'settings_dialog', None)
        self.settings_dialog = None
        if old is not None:
            old.close()
            old.deleteLater()
        panel = ProjectSettingsDialog(project, core.project_name(project), core.run_all(project), core.external_console(project), core.run_mode(project), self,
                                       icon=core.load_state(project).get('icon', ''))
        panel.mode_changed.connect(lambda mode: self.guarded(functools.partial(self.set_debug_mode, mode == 'debug')))
        panel.saved.connect(lambda: self.guarded(self.settings_saved))
        panel.accepted.connect(lambda: self.guarded(self.settings_accepted))
        self.settings_dialog = panel
        panel.show()

    def settings_values(self):
        dialog = self.settings_dialog
        if core.clean_path(dialog.folder) != self.project:
            raise core.ZygoteError('The project changed while the settings panel was open. Open Settings > Project settings… again.')
        return dialog.settings()

    def settings_saved(self):
        """Save button: write the values now; the panel stays open."""
        self.apply_settings(self.settings_values())
        self.settings_dialog.say_saved('Saved.')

    def settings_accepted(self):
        """OK: write the values; the panel closes."""
        self.apply_settings(self.settings_values())

    def apply_settings(self, answer):
        """Change the open project's name (and optionally its folder name), its debug box and the runner, entry point and arguments of both modes."""
        project = self.need_project()
        name = answer['name']
        if answer['rename'] and name != project.name:
            self.release_folder()
            try:
                new = core.rename_folder(project, name)
            finally:
                self.build_models()
            self.say(f'Renamed the folder to {new}')
            project = new
            self.attach(project)
            self.hold_instance(core.clean_path(project))          # the folder has a new name: so does the single-instance name
            if getattr(self, 'settings_dialog', None) is not None:
                self.settings_dialog.folder = project
        core.set_project_name(project, name)
        for mode in core.RUN_MODES:
            run = answer['runs'][mode]
            core.set_run_settings(project, mode, run['runner'], run['entry'], run['args'])
        core.set_program_icon(project, answer['icon'])
        QPixmapCache.clear()                                      # a replaced icon file must be read again
        self.show_program_icon()
        core.set_external_console(project, answer['external'])
        core.set_run_mode(project, answer['mode'])
        self.refresh()
        shown = '; '.join(f'{mode}: {core.command_text(**core.run_settings(project, mode))}' for mode in core.RUN_MODES)
        self.say(f'Project name is now "{name}"; Run uses the {answer["mode"]} settings; external console {"ON" if answer["external"] else "off"}; {shown}')
        self.stamp_shortcut()

    def run_project(self, normal=False):
        """Run: the entry point, else a real RUN.bat. With nothing to run yet the same Project settings panel opens.
        Every run goes through the Console tab inside Zygote (Zygote is the harness), unless "Show external console output" is ticked in
        Project settings: then it opens a console window that stays open after the program ends. normal=True (the header icon): always the
        Runtime settings, always in the Console tab."""
        project = self.need_project()
        mode = 'runtime' if normal else core.current_mode(project)
        external = False                                                                    # Run is always the Console tab, whatever "Show external console output" says
        kind, what = core.run_choice(project, mode)
        if kind == 'panel':
            self.say(f'Nothing to run yet: {what}. Set the entry point in this panel, then press Run again.')
            self.project_settings()
            return
        if kind == 'entry' and mode == 'debug' and not normal and not external and self.debugger.can_debug():
            self.guarded(functools.partial(self.debugger.press, 'continue'))                  # Run debug and Continue are ONE path: the debugger of the language bundle
            return
        if kind == 'entry':
            saved = core.run_settings(project, mode)
            if saved['runner']:
                command = core.entry_command(project, mode)
                self.start_program(command, f'{mode}: {" ".join(command)}', external)
                return
            if saved['args']:
                self.say(f'Started ({mode}): {core.run_entry_command(project, mode)}')   # no runner, but arguments: Windows opens the file with them
                return
        self.launch(what, external)                                                       # a .bat in the Console tab; any other file goes to Windows

    def run_as_product_with(self, paths):
        """Files dropped on the icon: the same run, with these files as the arguments instead of the saved ones (this run only; nothing is saved)."""
        project = self.need_project()
        kind, what = core.run_choice(project, 'runtime')
        if kind != 'entry':
            raise core.ZygoteError('Dropping files on the icon needs an entry point: set it in Settings > Project settings…')
        self.run_as_product(core.arguments_for(project, paths))

    def run_as_product(self, args=None):
        """The icon at the right of the bar: run the project the way its finished program would run, outside Zygote's Console, with the Runtime settings'
        runner (a command line window opens only when that runner is one). "Show external console output" ticked: the console that stays open.
        One process per press, started by this button. args: arguments for this run only, instead of the saved ones (files dropped on the icon)."""
        project = self.need_project()
        kind, what = core.run_choice(project, 'runtime')
        if kind == 'panel':
            self.say(f'Nothing to run yet: {what}. Set the entry point in this panel, then press Run again.')
            self.project_settings()
            return
        command = core.entry_command(project, 'runtime', args) if kind == 'entry' else None
        if core.external_console(project):
            words = command or [str(project / (core.run_settings(project, 'runtime')['entry'] if kind == 'entry' else what).replace('\\', '/'))] + (core.split_words(args) if args else [])
            if core.open_external_console(words, project) is None:
                self.say('External console: this system has no terminal Zygote knows (x-terminal-emulator, gnome-terminal, konsole, xterm); nothing was started.')
                return
            self.say(f'Started as a product, in an external console that stays open ({" ".join(words)})')
        elif kind == 'entry':
            self.say(f'Started as a product ({core.run_entry_command(project, "runtime", args)})' + (' with the dropped files' if args is not None else ''))
        else:
            core.launch(project, what.replace('/', '\\'), debug=False)
            self.say(f'Started as a product: {what}')
    def start_program(self, command, label, external):
        """One program: in a kept-open external console when asked and one exists, else in the Console tab."""
        if external:
            shown = core.open_external_console(command, self.need_project())
            if shown is not None:
                self.say(f'Started in an external console ({label})')
                return
            self.say('External console: this system has no terminal Zygote knows (x-terminal-emulator, gnome-terminal, konsole, xterm); running in the Console tab instead.')
        if Path(command[0]).stem.lower().startswith('pythonw'):
            self.say('Console: this runner (pythonw) has no output, so there is nothing to capture.')
        self.run_in_console(command, label)

    def note(self, what):
        """One line in the project's history (app_tree\\notes). A problem is shown and logged; the work goes on."""
        try:
            core.record_event(self.project, what)
        except core.ZygoteError as error:
            self.say(f'History not written: {error}')
            self.show_error(f'History not written:\n{error}')

    def note_open(self):
        try:
            line = core.note_tool_version(self.project)
        except core.ZygoteError as error:
            self.say(f'History not written: {error}')
            self.show_error(f'History not written:\n{error}')
            return
        if line:
            self.say(f'History: {line}')

    def show_history(self):
        project = self.need_project()
        self.help_window = HelpWindow.text_page(f'{core.project_name(project)} — project history', core.history_text(project), self)
        self.help_window.show()

    def show_tests(self):
        project = self.need_project()
        self.tests_dialog = TestsDialog(project, self)
        self.tests_dialog.show()


    def notice(self, text):
        """A short message with an OK. Tests replace this."""
        QMessageBox.information(self, 'Zygote', text)

    def ask_rebuild(self, items):
        """The Rebuild panel. Returns the ticked keys, or None when it was cancelled. Tests replace this."""
        dialog = RebuildDialog(items, self)
        return dialog.keys() if dialog.exec() == QDialog.Accepted else None

    def rebuild_project(self):
        """Project > Remake launchers…: the health check first (nothing is changed), then exactly what the person ticked. A compile can take minutes the first time."""
        project = self.need_project()
        rebuild = Rebuild(project)
        keys = self.ask_rebuild(rebuild.health())
        if keys is None:
            self.say('Remake cancelled.')
            return
        self.say('Remaking: ' + (', '.join(keys) if keys else 'nothing ticked') + '…')
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            lines = rebuild.run(keys)
        finally:
            QApplication.restoreOverrideCursor()
        for line in lines:
            self.say_rebuild(line)
        self.reload_views()                                       # the Workbench draws the new launcher icon at once

    def stamp_shortcut(self):
        """Put this project's launcher at its root (<project>_Zide.lnk) and its Zygote shortcut in .zygote\\user. A failure is shown; the project stays open."""
        try:
            self.say(f'Launcher ready: {core.make_launcher(self.project)}')
            for link in core.create_shortcut(self.project, core.project_name(self.project)):
                self.say(f'Shortcut stamped: {link}')
        except core.ZygoteError as error:
            self.say(f'Launcher or shortcut not made: {error}')
            self.show_error(f'The project is open, but the launcher or shortcut was not made:\n{error}')

    # ---- actions ---------------------------------------------------------------------------------------------
    def browse(self, path):
        """Show a folder in the icon view and name it in the title bar above it. A folder not read yet shows the busy cursor until it is in;
        the scout reads the person's own folders ahead (never .zygote unless the person is already inside it)."""
        self.read_ahead(path)
        self.show_in_views(self.icon_model.setRootPath(str(path)))
        self.show_title(path)
        self.zip_view_settings(path)

    def zip_view_settings(self, path):
        """The zip folder (snapshots, undo files, ZIPs) opens as a list with the newest first, so the old ones sit at the bottom and can be selected and thrown away
        together. Leaving it puts the sort and the view back the way they were."""
        in_zip = self.project is not None and core.clean_path(path) == core.clean_path(self.project) / 'zip'
        if in_zip and self.before_zip is None:
            self.before_zip = (self.sort_box.currentIndex(), self.view_box.currentIndex())
        if in_zip:
            self.sort_box.setCurrentIndex(self.sort_box.findText('Sort: Date modified (newest first)'))
            self.view_box.setCurrentIndex(1)
        elif self.before_zip is not None:
            self.sort_box.setCurrentIndex(self.before_zip[0])
            self.view_box.setCurrentIndex(self.before_zip[1])
            self.before_zip = None

    def show_folder(self, index):
        if self.tree_proxy is not None and index.model() is self.tree_proxy:
            index = self.tree_proxy.mapToSource(index)
        self.browse(self.tree_model.filePath(index))

    def show_computer_folder(self, index):
        self.browse(self.computer_model.filePath(index))

    def shown_folder(self):
        """The folder the folder view shows now ('' when it shows the drives)."""
        return self.icon_model.filePath(self.icons.rootIndex()) if self.icons.rootIndex().isValid() else ''

    def open_folder(self):
        folder = self.shown_folder()
        core.open_folder(folder)
        self.say(f'Showed {folder} in the file manager')

    def press_cli(self, kind, admin):
        self.guarded(functools.partial(self.open_cli, kind, admin))

    def open_cli(self, kind, admin):
        folder = self.shown_folder()
        if not core.open_cli(kind, folder, admin):             # the person pressed No in the Windows permission window: silent, unless the external console box is ticked
            if core.external_console(self.project):
                self.say('External console is on: the administrator permission window was cancelled; nothing was started')
            return
        self.say(f'Opened {"PowerShell" if kind == "powershell" else "Command Prompt"}{" as administrator" if admin else ""} in {folder}')

    def show_zygote_help(self):
        self.help_window = HelpWindow.html_page('Zygote help', core.read_help(core.zygote_help_path()), self)
        self.help_window.show()

    def show_project_help(self):
        if self.project is None:
            raise core.ZygoteError('No project is open. Open a project first (Project > Open project…).')
        name = core.project_name(self.project)
        path = core.project_help_path(self.project)
        self.help_window = HelpWindow.markdown_page(f'{name} — project help', core.read_help(path), self, editable=(self.project, path))
        self.help_window.show()

    def show_in_views(self, index):
        self.icons.setRootIndex(index)
        self.details.setRootIndex(index)

    def sort_changed(self):
        column, descending = self.sort_box.currentData()
        order = Qt.DescendingOrder if descending else Qt.AscendingOrder
        self.icon_model.sort(column, order)
        self.details.header().setSortIndicator(column, order)

    def view_changed(self):
        self.icon_stack.setCurrentWidget(self.details if self.view_box.currentIndex() == 1 else self.icons)

    def open_item(self, index):
        if self.icon_model.is_bin(index):
            self.guarded(self.show_trash)
            return
        path = self.icon_model.filePath(index)
        self.guarded(lambda: self.open_inside(path) if Path(path).is_dir() else core.open_file(path))      # a folder opens inside Zygote

    def open_inside(self, path):
        """A folder opens inside Zygote: the folder view shows it and, when it is in the project, the tree selects it."""
        self.browse(path)
        if self.project is not None and self.tree_proxy is not None and core.project_relative(self.project, path) is not None:
            self.select_in_tree(path)

    def tree_index(self, path):
        """The tree's (proxy) index of a path, made fresh every time: an index kept across a folder being read goes stale and crashed Qt."""
        return self.tree_proxy.mapFromSource(self.tree_model.index(str(path)))

    def select_in_tree(self, path):
        """Select a folder in the project tree. Every folder above it is opened FIRST, one at a time, each index taken fresh: opening a folder
        can read it and change the rows at once, and selecting with an index taken before that crashed Qt (opening app_tree\\assets)."""
        path = Path(path)
        for folder in reversed([parent for parent in path.parents if core.project_relative(self.project, parent) is not None]):
            above = self.tree_index(folder)
            if above.isValid():
                self.tree.expand(above)
        index = self.tree_index(path)
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

    def read_ahead(self, path):
        """The folder is about to be shown: the scout reads the person's own folders ahead (never .zygote unless the person is already in it)."""
        if self.project is not None and core.project_relative(self.project, path) is not None:
            self.scout.plan(core.read_ahead_plan(self.project, path))

    def folder_loaded(self, path):
        """A folder of the tree or the folder view was read. The start-up is done when the working space (the project's folder, in the folder
        view and in the tree) is in."""
        if self.project is None or Path(path) != Path(self.project):
            return
        for name, model in (('folder view', self.icon_model), ('project tree', self.tree_model)):
            if name in self.waiting and model.is_loaded(path):
                self.waiting.discard(name)
                self.say(f'Loaded: {name}.')
        if not self.waiting and not self.ready_sent:
            self.ready_sent = True
            self.working_space_ready.emit()

    def still_loading(self):
        """What the start-up still waits for (the Log says it when the splash is dismissed or gives up)."""
        return sorted(self.waiting)

    def trash_paths(self, paths):
        """Throw items away (to .zygote\\user\\trash). The ones that may not be thrown away are named and left where they are."""
        project = self.need_project()
        moved = 0
        for path in paths:
            if core.can_trash(project, path):
                core.trash_path(project, path)
                moved += 1
            else:
                self.say(f'Not thrown away: {Path(path).name} (the project, .zygote, .git, zip and the launcher stay).')
        if moved:
            self.say(f'{moved} item(s) are in the trash. Open the recycle bin (first item of the folder view) to put them back.')
        for name in self.debugger.close_files([path for path in paths if not Path(path).exists()]):
            self.say(f'Closed the tab of {Path(name).name}: the file was thrown away.')
        self.keep_view(paths)
        self.bin_changed()
        return moved

    def keep_view(self, thrown):
        """The folder in view was thrown away (or one above it): show the nearest folder that is still there, inside the project."""
        if not self.icons.rootIndex().isValid() or self.project is None:
            return
        target = core.fallback_folder(self.icon_model.filePath(self.icons.rootIndex()), [p for p in thrown if core.can_trash(self.project, p)])
        if target is not None:
            self.say(f'The folder in view was thrown away: showing {target.name} instead.')
            self.open_inside(target)

    def bin_changed(self):
        """The trash changed (thrown away, put back, emptied): the views, the bin picture and the open bin window follow at once."""
        if self.trash_window is not None:
            self.trash_window.reload()
        self.refresh_bin()
        self.refresh()

    def refresh_bin(self):
        """The bin row shows paper when the trash holds something, else it looks empty."""
        if self.project is not None:
            self.icon_model.set_bin_full(bool(core.trash_items(self.project)))

    def show_title(self, path):
        """The path above the folder view: the project's name, then each level down to the folder in view; the up arrow follows."""
        if path is None or self.project is None:
            self.folder_title.show_path([('Computer', '')] if path is None else [(Path(path).name or str(path), str(path))])
            self.up_button.setEnabled(path is not None and Path(path).parent != Path(path))
            return
        path = Path(path)
        relative = core.project_relative(self.project, path)
        if relative is None:
            self.folder_title.show_path([(path.name or str(path), str(path))])
            self.up_button.setEnabled(path.parent != path)
            return
        segments = [(self.project.name + ' workbench', str(self.project))]           # the folder you work in is the project's workbench
        for part in Path(relative).parts if str(relative) not in ('', '.') else ():
            segments.append((part, str(Path(segments[-1][1]) / part)))
        self.folder_title.show_path(segments)
        self.up_button.setEnabled(len(segments) > 1)

    def go_up(self):
        current = Path(self.icon_model.filePath(self.icons.rootIndex())) if self.icons.rootIndex().isValid() else None
        if current is not None and current.parent != current:
            self.open_inside(current.parent)

    def show_trash(self):
        """The recycle bin window: not modal, above the main window, one at a time. The folder view's bin row opens it."""
        project = self.need_project()
        if self.trash_window is None or self.trash_window.project != project:
            self.trash_window = TrashWindow(project, self)
            self.trash_window.refused.connect(self.say)
            self.trash_window.changed.connect(self.bin_changed)
            self.trash_window.thrown.connect(lambda paths: self.guarded(functools.partial(self.trash_paths, paths)))
        else:
            self.trash_window.reload()
        self.trash_window.show()
        self.trash_window.raise_()

    def restore_dropped(self, slots):
        """Items dragged out of the bin onto the folder view: they go into the folder in view."""
        project = self.need_project()
        folder = Path(self.icon_model.filePath(self.icons.rootIndex())) if self.icons.rootIndex().isValid() else project
        for slot in slots:
            try:
                self.say(f'Put back in {folder.name}: {core.restore_item(project, slot, folder).name}')
            except core.ZygoteError as error:
                self.say(str(error))
        self.bin_changed()

    def file_menu(self, path):
        """The right-click menu of one item of the folder view: a small operating system. What does not apply is not there (a blue folder has no Copy,
        Rename or Delete; a program has Open and nothing to open it with)."""
        menu = QMenu(self)
        if Path(path).is_dir():
            self.add_action(menu, 'Open', functools.partial(self.open_inside, path))
            self.add_action(menu, core.file_manager_label(), functools.partial(core.open_path, path))
            self.paste_action(menu, path)
            self.edit_actions(menu, path)
            self.trash_action(menu, path)
            return menu
        self.add_action(menu, 'Open', functools.partial(core.open_file, path))
        if core.file_extension(path) == '.exe':
            self.trash_action(menu, path)                       # a program is opened, nothing else (no View, no Open with)
            return menu
        if core.is_text_file(path):
            self.add_action(menu, 'View contents', functools.partial(self.view_contents, path))
        self.edit_actions(menu, path)
        self.trash_action(menu, path)
        return menu

    def edit_actions(self, menu, path):
        """Copy and Rename: only for what the person works on."""
        if self.project is not None and core.can_copy(self.project, path):
            menu.addSeparator()
            self.add_action(menu, 'Copy', functools.partial(self.copy_paths, [path]))
            self.add_action(menu, 'Rename', functools.partial(self.begin_rename, path))

    def paste_action(self, menu, folder):
        """Paste into a folder: there only when something was copied and the folder is one the person may make things in."""
        if self.clipboard_paths and self.project is not None and core.can_create_in(self.project, folder):
            menu.addSeparator()
            self.add_action(menu, 'Paste', functools.partial(self.paste_into, folder))

    def folder_menu(self, folder):
        """The right-click menu of empty space in the folder view: New folder, New text document, New bitmap image, Paste (grey where the folder is Zygote's own)."""
        menu = QMenu(self)
        allowed = self.project is not None and core.can_create_in(self.project, folder)
        for kind, label in (('folder', 'New folder'), ('text', 'New text document'), ('bitmap', 'New bitmap image')):
            self.add_action(menu, label, functools.partial(self.new_item, folder, kind)).setEnabled(allowed)
        menu.addSeparator()
        self.add_action(menu, 'Paste', functools.partial(self.paste_into, folder)).setEnabled(allowed and bool(self.clipboard_paths))
        menu.addSeparator()
        self.add_action(menu, 'Refresh', self.reload_views)       # the same as File > Reload: folders, icons and marks are read again
        return menu

    def view_contents(self, path):
        """View contents: the file opens as a tab in the code window beside the Console (the same path as dragging it onto the Console)."""
        self.debugger.open_dropped([path])

    # ---- the workbench as a small operating system: new, copy, paste, rename -------------------------------------
    def new_item(self, folder, kind):
        path = core.new_item(self.need_project(), folder, kind)
        self.say(f'Made {path.name} in {Path(folder).name}. Type its name and press Enter.')
        self.begin_rename(path)

    def copy_paths(self, paths):
        copyable = [str(path) for path in paths if self.project is not None and core.can_copy(self.project, path)]
        self.clipboard_paths = copyable
        self.say(f'Copied {len(copyable)} item(s): ' + ', '.join(Path(path).name for path in copyable) + '. Right-click a folder or empty space > Paste.' if copyable
                 else 'Nothing copied: only the files and folders you work on can be copied.')

    def paste_into(self, folder):
        made = core.copy_into(self.need_project(), self.clipboard_paths, folder)
        self.say(f'Pasted {len(made)} item(s) into {Path(folder).name}: ' + ', '.join(path.name for path in made))
        self.icon_model.reload(str(folder))

    def begin_rename(self, path):
        """Put the name of an item in an editor in the folder view. The item may not be in the rows yet (just made): it waits for its folder to be read."""
        node = self.icon_model.find(path)
        if node is not None and node.kind == 'item' and node.parent is not None and node.parent.loaded:
            QTimer.singleShot(0, self, functools.partial(self.edit_name, str(path)))        # the item is in the rows already (the menu, F2): no reading to wait for
            return
        self.pending_rename = str(path)
        self.icon_model.reload(str(Path(path).parent))

    def rename_current(self):
        """F2: rename the one item that is selected in the folder view (the same path as Rename in the menu). Nothing selected, or several: nothing happens."""
        view = self.details if self.view_box.currentIndex() == 1 else self.icons
        rows = {index.row() for index in view.selectionModel().selectedIndexes()}
        indexes = [index for index in view.selectionModel().selectedIndexes() if index.column() == 0]
        if len(rows) == 1 and indexes and self.project is not None and core.can_copy(self.project, self.icon_model.filePath(indexes[0])):
            self.begin_rename(self.icon_model.filePath(indexes[0]))

    def start_pending_rename(self, folder):
        """The folder was read: when it holds the item that waits for its name, select it and open the editor on it."""
        wanted = self.pending_rename
        if wanted is None or Path(wanted).parent != Path(folder):
            return
        node = self.icon_model.find(wanted)
        if node is None or node.kind != 'item':
            return
        self.pending_rename = None
        QTimer.singleShot(0, self, functools.partial(self.edit_name, wanted))        # NOT now: the folder is being rebuilt under this call

    def edit_name(self, path):
        node = self.icon_model.find(path)
        if node is None:
            return
        view = self.details if self.view_box.currentIndex() == 1 else self.icons
        index = self.icon_model.index_of(node)
        view.setCurrentIndex(index)
        view.edit(index)

    def rename_item(self, path, new_name):
        """A name typed in the folder view: the file is renamed (a name that is taken or that Windows refuses is said, nothing changes)."""
        project = self.need_project()
        try:
            target = core.rename_item(project, path, new_name)
        except core.ZygoteError as error:
            self.say(str(error))
            return
        if target != Path(path):
            for name in self.debugger.close_files([path]):
                self.say(f'Closed the tab of {Path(name).name}: the file was renamed. View it again.')
            self.say(f'Renamed {Path(path).name} to {target.name}.')
        self.icon_model.reload(str(Path(path).parent))

    def move_paths(self, paths, folder):
        """Green files and folders dropped on a folder are moved into it. Nothing is replaced; a refusal names the item and nothing moves."""
        project = self.need_project()
        try:
            made = core.move_into(project, paths, folder)
        except core.ZygoteError as error:
            self.say(str(error))
            return []
        if made:
            for name in self.debugger.close_files(paths):
                self.say(f'Closed the tab of {Path(name).name}: the file was moved. View it again.')
            self.say(f'Moved {len(made)} item(s) into {Path(folder).name}.')
        for place in {str(Path(path).parent) for path in paths} | {str(folder)}:
            self.icon_model.reload(place)
        return made

    def move_up(self, paths):
        """Green items dropped on the up button: moved into the folder above the one in view."""
        current = Path(self.icon_model.filePath(self.icons.rootIndex())) if self.icons.rootIndex().isValid() else None
        if current is None or current.parent == current:
            return []
        return self.move_paths(paths, str(current.parent))

    def trash_action(self, menu, path):
        """Delete (to the trash) for the items that may be thrown away: never the sacred or system ones."""
        if self.project is not None and core.can_trash(self.project, path):
            menu.addSeparator()
            self.add_action(menu, 'Delete (to the trash)', functools.partial(self.trash_paths, [path]))

    def bin_menu(self):
        """The right-click menu of the recycle bin row: it opens the bin; nothing in it throws anything away."""
        menu = QMenu(self)
        self.add_action(menu, 'Open', self.show_trash)
        self.add_action(menu, core.file_manager_label(), self.open_trash_folder)
        menu.addSeparator()
        count = len(core.trash_items(self.project)) if self.project is not None else 0
        self.add_action(menu, 'Empty trash…', self.empty_trash_all).setEnabled(count > 0)
        return menu

    def ask_empty_trash(self, count):
        """The guard of Empty trash: how many go for good, that it cannot be undone, and No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Warning, 'Empty the trash',
                          f'Are you sure you want to empty the trash?\n\n{count} item(s) will be deleted for good. This cannot be undone.',
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def empty_trash_all(self):
        """Right-click on the recycle bin > Empty trash: everything in the bin, after the guard."""
        project = self.need_project()
        count = len(core.trash_items(project))
        if not count:
            self.say('The trash is empty already.')
            return
        if not self.ask_empty_trash(count):
            self.say('Empty trash: cancelled, nothing was deleted.')
            return
        gone = core.empty_trash(project)
        self.say(f'Empty trash: {gone} item(s) deleted for good.')
        self.bin_changed()

    def open_trash_folder(self):
        folder = core.trash_folder(self.need_project())
        if not folder.is_dir():
            self.say('The trash folder does not exist yet: nothing was thrown away.')
            return
        core.open_path(folder)

    def selection_menu(self, paths):
        """The right-click menu when several items are selected: what can be done to all of them at once."""
        menu = QMenu(self)
        throwable = [path for path in paths if self.project is not None and core.can_trash(self.project, path)]
        if throwable:
            self.add_action(menu, f'Copy {len(throwable)} items', functools.partial(self.copy_paths, throwable))
            menu.addSeparator()
            self.add_action(menu, f'Delete {len(throwable)} items (to the trash)', functools.partial(self.trash_paths, throwable))
        else:
            self.add_action(menu, 'These items cannot be thrown away').setEnabled(False)
        return menu

    def selected_paths(self, view):
        """The items selected in a folder view (the recycle bin and the loading row are not items)."""
        model = self.icon_model
        return sorted({model.filePath(index) for index in view.selectionModel().selectedIndexes() if model.node(index).kind == 'item'})

    def menu_for(self, view, position):
        """The right-click menu of the row under the cursor (of the whole selection when that row is part of it), never of the folder in view.
        Empty space has the menu of the folder in view (New, Paste); the loading row and the drives list have none."""
        index = view.indexAt(position)
        if not index.isValid():
            folder = self.shown_folder()
            return self.folder_menu(folder) if folder else None
        model = self.icon_model
        if model.is_bin(index):
            return self.bin_menu()
        if model.node(index).kind != 'item':
            return None
        paths = self.selected_paths(view)
        if len(paths) > 1 and model.filePath(index) in paths:
            return self.selection_menu(paths)
        return self.file_menu(model.filePath(index))

    def show_file_menu(self, view, position):
        menu = self.menu_for(view, position)
        if menu is not None:
            menu.exec(view.viewport().mapToGlobal(position))

    def show_icons_menu(self, position):
        self.guarded(lambda: self.show_file_menu(self.icons, position))

    def show_details_menu(self, position):
        self.guarded(lambda: self.show_file_menu(self.details, position))

    def tools_settings(self):
        dialog = ToolsDialog(core.associations(), self)
        if dialog.exec() == QDialog.Accepted:
            self.say(f'Tools saved: {len(dialog.values())} file types')

    RELOAD_WAIT_MS = 4000                                      # an external console tells nothing when it ends: Reload waits this long after the press
    FINISHED_WAIT_MS = 1500                                    # in the Console tab: Reload follows the end of the commit by this long (TortoiseGit writes its marks first)

    def commit(self):
        """Commit: COMMIT.bat runs TortoiseGit and waits for it, in a process of its own (never the Console tab: a program running under test is not stopped
        and not touched). Its output goes to the Log, its end is a signal, and the views are read again then (the red marks). With "Show external console
        output" ticked the batch file opens its own console, as before, and the reload waits a few seconds after the press."""
        project = self.need_project()
        if core.external_console(project):
            self.launch(core.zrel('bat', 'COMMIT.bat'))
            self.schedule_reload(self.RELOAD_WAIT_MS)
            return
        bat = core.zpath(project, 'bat', 'COMMIT.bat')
        if not bat.exists():
            raise core.ZygoteError(f'{core.zrel("bat", "COMMIT.bat")} not found in {project}. If this project has the older layout, use File > Update project\'s Zygote…')
        if self.committer is None:
            self.committer = CommitRunner(self)
            self.committer.line.connect(self.say)
            self.committer.finished.connect(self.commit_finished)
        if not self.committer.start(self.commit_command(bat), project):
            self.say('A commit is still running: finish it first.')
            return
        self.say('Commit started (separate from the Console).')

    @staticmethod
    def commit_command(bat):
        return ['cmd.exe', '/c', str(bat)]

    def commit_finished(self, code):
        self.say(f'Commit program ended (exit code {code if code >= 0 else "unknown"}).')
        self.schedule_reload(self.FINISHED_WAIT_MS)

    def schedule_reload(self, wait=None):
        """After a commit: do what File > Reload does, a few seconds later (a second commit restarts the wait)."""
        wait = self.RELOAD_WAIT_MS if wait is None else wait
        timer = getattr(self, 'reload_timer', None)
        if timer is None:
            timer = self.reload_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.guarded(self.reload_after_commit))
        timer.start(wait)
        self.say(f'Reload follows in {wait / 1000:g} seconds')

    def reload_after_commit(self):
        if self.project is not None:
            self.reload_views()

    def launch(self, name, external=None):
        """Start a file of the project. A .bat or .cmd runs in the Console tab, or in an external console that stays open when
        "Show external console output" is ticked (external: ask for one or the other). Anything else goes to Windows."""
        project = self.need_project()
        path = project / name.replace('\\', '/')
        if path.suffix.lower() in ('.bat', '.cmd'):
            if not path.exists():
                raise core.ZygoteError(f'{name} not found in {project}')
            external = core.external_console(project) if external is None else external
            self.start_program([str(path)] if external else ['cmd.exe', '/c', str(path)], name, external)      # an external console runs `cmd /k <bat>`
            return
        core.launch(project, name.replace('/', '\\'), debug=False)
        self.say(f'Started {name}')

    # ---- the Console tab (a real terminal; DOCTRINE Part 4: one program per press, held by Zygote, ended by Stop or by closing the window) --------------
    def console_view(self):
        """The terminal view, made on first use. Raises (loudly) when the terminal package is missing."""
        if self.console is None:
            self.console = self.terminal_factory(parent=self.console_page)
            self.console.finished.connect(self.console_finished)
            self.console_split.insertWidget(0, self.console)
            self.console.setAcceptDrops(True)
            self.console_drop = DropToCode(self.console)           # a text file dragged from the folder view onto the console opens the code window
            self.console_drop.dropped.connect(lambda paths: self.guarded(functools.partial(self.debugger.open_dropped, paths)))
            self.console.installEventFilter(self.console_drop)
        return self.console

    def ask_stop_running(self):
        """Run was pressed while a program still runs in the Console. True = stop it first. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', 'A program is still running in the Console.\nStop it first and start the new one?') == QMessageBox.Yes

    def run_in_console(self, command, label):
        """Start one program in the Console tab, in the project folder. Nothing starts without this call (a button)."""
        view = self.console_view()
        if view.is_running():
            if not self.ask_stop_running():
                self.say('Not started: a program is still running in the Console.')
                return False
            self.stop_console()
            if view.is_running():
                self.say('The old program did not end yet. Press Stop again to force it, then press Run again.')
                return False
        view.start(command, self.need_project())
        self.bottom_tabs.setCurrentWidget(self.console_page)
        self.stop_button.setEnabled(True)
        self.debugger.sync()
        view.setFocus()                                           # typing goes straight into the program
        self.say(f'Started in the Console ({label})')
        return True

    CONSOLE_STOP_WAIT_MS = 2000                                   # how long a Stop waits for the program to end before it says so

    def wait_until_ended(self, view):
        """After a stop was asked: wait up to CONSOLE_STOP_WAIT_MS for the program to end (the end arrives from the reader thread through Qt's event loop)."""
        waited = 0
        while view.is_running() and waited < self.CONSOLE_STOP_WAIT_MS:
            QApplication.processEvents()
            QThread.msleep(25)
            waited += 25

    def stop_console(self):
        """Console Stop button: the first press asks the program to end, a second one forces it."""
        if self.console is None or not self.console.is_running():
            return
        self.console.stop()
        self.wait_until_ended(self.console)
        if self.console.is_running():
            self.say('The program did not end yet. Press Stop again to force it.')

    def console_finished(self, code):
        if not self.console.is_running():                          # the end of an old program can arrive after a new one started: Stop stays lit for the new one
            self.stop_button.setEnabled(False)
        self.debugger.sync()
        self.say(f'The program in the Console ended (exit code {code if code >= 0 else "unknown"}).')

    def show_agents(self):
        """AI > AI agents: the agents panel, a window of its own that stays open as long as it is wanted (not modal)."""
        self.need_project()
        if self.agents_window is None:
            self.agents_window = AgentsWindow(self)
        self.agents_window.show()
        self.agents_window.raise_()
        self.agents_window.activateWindow()

    def ai_requested(self):
        """A program of this project (ai.interface.set_model) asked for the AI panel: it opens, in front, with a short note on what to do there."""
        self.show_ai()
        self.show_toast('Load or choose a model here (set the parameters), close the panel, then ask again.')

    def show_layout_ai(self):
        """AI > AI panel (layout): the same panel read from its layout file by the Qt renderer (the first of the panels that a project can carry)."""
        project = self.need_project()
        if self.layout_ai_window is None:
            self.layout_ai_window = PanelWindow(self, project)
        self.layout_ai_window.show()
        self.layout_ai_window.raise_()
        self.layout_ai_window.activateWindow()

    def show_ai(self):
        """File bar > AI: the AI panel, in a window of its own that stays open as long as it is wanted (not modal)."""
        project = self.need_project()
        if self.ai_window is None:
            self.ai_window = AIWindow(self, project)
        self.ai_window.show()
        self.ai_window.raise_()
        self.ai_window.activateWindow()

    # ---- shell tabs (each tab holds one shell; nothing starts except from the "+" tab or a Start button) --------------------------------
    def ask_clear(self, what):
        """Clear was pressed: True = go ahead. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', f'Clear the {what}?') == QMessageBox.Yes

    def copy_text(self, text, what):
        """Put text on the clipboard and say so in a toast. The clipboard is the one place the text is written to."""
        if not text.strip():
            self.show_toast(f'The {what} is empty: nothing to copy')
            return False
        QApplication.clipboard().setText(text)
        self.show_toast(f'{what.capitalize()} copied: {len(text.splitlines())} lines')
        return True

    def copy_log(self):
        """Log tab, Copy: the whole log as text."""
        return self.copy_text(self.log.toPlainText(), 'log')

    def copy_console(self):
        """Console tab, Copy: the whole terminal buffer (the scroll-back too) as text."""
        return self.copy_text('' if self.console is None else self.console.screen_text(), 'Console')

    def copy_shell(self):
        """Shell tab, Copy: the whole terminal buffer of the tab that is shown."""
        page = self.current_shell_page()
        return self.copy_text('' if page is None or page.view is None else page.view.screen_text(), 'shell tab')

    def clear_log(self):
        """Log tab, Clear: empties the log view (after asking). The lines were never kept anywhere else."""
        if self.ask_clear('log'):
            self.log.clear()

    def clear_console(self):
        """Console tab, Clear: empties the terminal screen and its scroll-back (after asking). Nothing to clear before the first run."""
        if self.console is not None and self.ask_clear('Console'):
            self.console.clear_view()

    def bottom_tab_changed(self, index):
        """The "+" tab is a button that looks like a tab: pressing it makes the next shell and the tab that was shown stays (or the new shell shows)."""
        page = self.bottom_tabs.widget(index)
        if page is self.bottom_tabs.plus_page:
            self.bottom_tabs.setCurrentIndex(self.last_tab)
            self.guarded(self.new_shell)
            return
        self.last_tab = index
        self.tab_tools.setCurrentIndex(2 if isinstance(page, ShellPage) else min(index, 1))
        self.refresh_shell_tools()
        if isinstance(page, ShellPage) and page.view is not None:
            page.view.refit()
            page.view.setFocus()                                      # typing goes straight into the shell

    def current_shell_page(self):
        page = self.bottom_tabs.currentWidget()
        return page if isinstance(page, ShellPage) else None

    def refresh_shell_tools(self):
        page = self.current_shell_page()
        self.shell_stop_button.setEnabled(page is not None and page.is_running())
        self.shell_clear_button.setEnabled(page is not None and page.view is not None)

    def next_shell_name(self):
        names = [self.bottom_tabs.tabText(self.bottom_tabs.indexOf(page)) for page in self.bottom_tabs.shell_pages()]
        number = 1
        while f'Shell {number}' in names:
            number += 1
        return f'Shell {number}'

    def add_shell_page(self, name, color):
        """A shell tab before the "+" tab, not started."""
        page = ShellPage()
        page.start_wanted.connect(lambda: self.guarded(functools.partial(self.start_shell_page, page)))
        self.dock_page(page, name, color)
        return page

    def dock_page(self, page, name, color):
        """Put a shell page among the tabs (new, or back from its own window), with its close button."""
        button = close_button()
        button.clicked.connect(lambda: self.guarded(functools.partial(self.close_shell_page, page)))
        self.bottom_tabs.add_shell_page(page, name, color, button)

    def begin_tear(self, index, where):
        """A shell tab was dragged off the bar: the tab leaves the bar and follows the mouse (the shell goes on running)."""
        page = self.bottom_tabs.widget(index)
        if not isinstance(page, ShellPage):
            return
        name, color = self.bottom_tabs.take_shell_page(page)
        ghost = TabGhost(name, core.TAB_COLORS[color])
        ghost.carry_to(where)
        ghost.show()
        self.tear_hold = (page, name, color, ghost)

    def move_tear(self, where):
        if self.tear_hold is not None:
            self.tear_hold[3].carry_to(where)

    def end_tear(self, where):
        """The mouse was let go: the carried tab becomes a window where it was put down."""
        if self.tear_hold is None:
            return None
        page, name, color, ghost = self.tear_hold
        self.tear_hold = None
        ghost.hide()
        ghost.deleteLater()
        return self.shell_window(page, name, color, where)

    def tear_away(self, index, where):
        """Tear a shell tab off and put it down at once (begin and end in one step)."""
        self.begin_tear(index, where)
        return self.end_tear(where)

    def shell_window(self, page, name, color, where):
        window = ShellWindow(page, name, core.TAB_COLORS[color])
        window.color = color
        window.name = name
        window.dock_wanted.connect(lambda: self.guarded(functools.partial(self.dock_back, window)))
        window.close_wanted.connect(lambda: self.guarded(functools.partial(self.close_torn, window)))
        window.released.connect(lambda at: self.guarded(functools.partial(self.shell_window_released, window, at)))
        window.carried.connect(self.shell_window_carried)
        window.move(where - QPoint(80, 12))
        self.torn.append(window)
        window.show()
        self.say(f'"{name}" is in a window of its own. Minimize it to put it back among the tabs; its X ends the shell.')
        return window

    def over_tab_bar(self, where):
        bar = self.bottom_tabs.tab_bar
        return bar.rect().contains(bar.mapFromGlobal(where))

    def shell_window_carried(self, where):
        """A shell window is being moved: the tab bar is lit while the pointer is over it (letting go there puts the shell back)."""
        bar = self.bottom_tabs.tab_bar
        over = self.over_tab_bar(where)
        if bar.drop_hint != over:
            bar.drop_hint = over
            bar.update()

    def shell_window_released(self, window, where):
        bar = self.bottom_tabs.tab_bar
        bar.drop_hint = False
        bar.update()
        if self.over_tab_bar(where):
            self.dock_back(window)

    def dock_back(self, window):
        """A shell window goes back among the tabs, as the shown tab."""
        if window not in self.torn:
            return None
        self.torn.remove(window)
        page = window.page
        window.layout().removeWidget(page)
        self.dock_page(page, window.name, window.color)
        self.bottom_tabs.setCurrentWidget(page)
        window.hide()
        window.deleteLater()
        bar = self.bottom_tabs.tab_bar
        bar.drop_hint = False
        bar.update()
        if page.view is not None:
            page.view.refit()                                           # the screen has its new size: draw all of it again
            page.view.setFocus()
        self.say(f'"{window.name}" is back in the tabs.')
        return page

    def close_torn(self, window):
        """The X of a torn shell window does what the X of its tab does: the shell ends (after asking when a program runs in it) and it is gone."""
        page = self.dock_back(window)
        if page is not None:
            self.close_shell_page(page)

    def dock_all_torn(self):
        for window in list(self.torn):
            self.dock_back(window)

    def new_shell(self):
        """The "+" tab: a new shell tab with its own shell, started in the project folder. One shell per press; at most core.SHELL_LIMIT open."""
        self.need_project()
        pages = self.bottom_tabs.shell_pages()
        if len(pages) + len(self.torn) >= core.SHELL_LIMIT:
            self.say(f'Not started: {core.SHELL_LIMIT} shell tabs are open. Close one first.')
            return None
        used = [self.bottom_tabs.tab_bar.tabData(self.bottom_tabs.indexOf(page)) for page in pages]
        page = self.add_shell_page(self.next_shell_name(), core.next_tab_color(used))
        self.bottom_tabs.setCurrentWidget(page)
        self.start_shell_page(page)
        return page

    def start_shell_page(self, page):
        """Start this tab's shell (its Start button, or the "+" that just made the tab). A tab holds one shell."""
        if page.is_running():
            return
        project = self.need_project()
        view = self.terminal_factory(parent=page)
        view.finished.connect(functools.partial(self.shell_finished, page))
        page.show_view(view)
        try:
            view.start(core.shell_command(), project)
        except Exception:
            page.drop_view()                                      # the tab goes back to its Start button, and the error is shown in full
            raise
        view.setFocus()
        self.say(f'Started a shell in "{self.bottom_tabs.tabText(self.bottom_tabs.indexOf(page))}"')
        self.refresh_shell_tools()

    def shell_finished(self, page, code):
        index = self.bottom_tabs.indexOf(page)
        if index >= 0:
            self.say(f'The shell "{self.bottom_tabs.tabText(index)}" ended (exit code {code if code >= 0 else "unknown"}).')
        self.refresh_shell_tools()

    def stop_shell(self):
        """A shell tab's Stop: ends that shell at once (a shell has nothing to save, so it is not asked politely first)."""
        page = self.current_shell_page()
        if page is None or not page.is_running():
            return
        page.view.stop(force=True)
        self.wait_until_ended(page.view)
        if page.is_running():
            self.say('The shell did not end yet. Press Stop again.')
        self.refresh_shell_tools()

    def clear_shell(self):
        page = self.current_shell_page()
        if page is not None and page.view is not None and self.ask_clear('shell tab'):
            page.view.clear_view()

    def ask_close_shell(self, name):
        """The X of a tab whose shell still runs: True = end it and close the tab. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', f'A program is still running in the shell "{name}".\nEnd it and close the tab?') == QMessageBox.Yes

    def close_shell_page(self, page):
        """The X (or Close in the tab's menu): a running shell is ended first, after asking. Nothing else changes."""
        index = self.bottom_tabs.indexOf(page)
        if index < 0:
            return False
        name = self.bottom_tabs.tabText(index)
        if page.is_running():
            if page.view.is_busy() and not self.ask_close_shell(name):      # an idle shell (nothing running in it) closes without a question
                self.say(f'Left open: a program is still running in "{name}".')
                return False
            page.view.stop(force=True)
            self.wait_until_ended(page.view)
            if page.is_running():
                self.say(f'The shell in "{name}" did not end yet. Press Stop, then close the tab.')
                return False
        self.remove_shell_page(page)
        return True

    def remove_shell_page(self, page):
        """Take a tab away (its shell has ended): no signal of the dead shell may reach the window afterwards."""
        if page.view is not None:
            page.view.finished.disconnect()
        index = self.bottom_tabs.indexOf(page)
        if self.bottom_tabs.currentWidget() is page:
            self.bottom_tabs.setCurrentIndex(index - 1)
        self.bottom_tabs.remove_shell_page(page)
        self.refresh_shell_tools()

    def shell_menu(self, index, where):
        """Right-click on a shell tab: Rename, one of the eight colour pairs, Close."""
        page = self.bottom_tabs.widget(index)
        menu = QMenu(self)
        menu.addAction('Rename').setData('rename')
        colors = menu.addMenu('Color')
        for at, (back, _text) in enumerate(core.TAB_COLORS):
            pixmap = QPixmap(14, 14)
            pixmap.fill(QColor(back))
            colors.addAction(QIcon(pixmap), core.TAB_COLOR_NAMES[at]).setData(f'color:{at}')
        menu.addAction('Close').setData('close')
        chosen = menu.exec(where)
        if chosen is not None:
            self.guarded(functools.partial(self.run_shell_menu, page, chosen.data()))

    def run_shell_menu(self, page, choice):
        if choice == 'rename':
            self.bottom_tabs.rename_in_place(self.bottom_tabs.indexOf(page))
        elif choice == 'close':
            self.close_shell_page(page)
        elif choice.startswith('color:'):
            self.bottom_tabs.set_color(page, int(choice.split(':')[1]))
        else:
            raise core.ZygoteError(f'Unknown tab menu choice: {choice!r}')

    def shell_records(self):
        """The shell tabs as they are kept per project: name and colour pair, in tab order (the shells themselves are never kept)."""
        return [{'name': self.bottom_tabs.tabText(self.bottom_tabs.indexOf(page)),
                 'color': self.bottom_tabs.tab_bar.tabData(self.bottom_tabs.indexOf(page))} for page in self.bottom_tabs.shell_pages()]

    def restore_shells(self):
        """Opening a project: its shell tabs come back with their names and colours, not running. Each shows a Start button."""
        for record in core.shell_tabs(self.project):
            self.add_shell_page(record['name'], record['color'])

    def ask_stop_shells(self, count):
        """Another project is being opened while shells run: True = end them. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', f'{count} shell(s) are still running.\nEnd them and open the other project?') == QMessageBox.Yes

    def leave_shells(self):
        """Before another project is opened: running shells end (after asking); declining stops the opening, nothing changes."""
        self.dock_all_torn()
        running = [page for page in self.bottom_tabs.shell_pages() if page.is_running()]
        if not running:
            return
        if not self.ask_stop_shells(len(running)):
            raise core.ZygoteError('Not opened: a shell is still running. Stop it, or close its tab, then open the project again.')
        for page in running:
            page.view.stop(force=True)
            self.wait_until_ended(page.view)

    def clear_shell_pages(self):
        for page in self.bottom_tabs.shell_pages():
            self.remove_shell_page(page)

    def closeEvent(self, event):
        """Closing with a program still running in the Console or a shell tab asks first; yes ends it (nothing is left running after Zygote
        closes). The drag bars are kept where they are."""
        self.dock_all_torn()
        self.scout.stop()
        shells = [page for page in self.bottom_tabs.shell_pages() if page.is_running()]
        console = self.console is not None and self.console.is_running()
        if console or shells:
            where = 'in the Console' if console and not shells else ('in a shell tab' if shells and not console else 'in the Console and a shell tab')
            if QMessageBox.question(self, 'Zygote', f'A program is still running {where}.\nStop it and close Zygote?') != QMessageBox.Yes:
                event.ignore()
                return
            for view in ([self.console] if console else []) + [page.view for page in shells]:
                view.stop()
                if view.is_running():
                    view.stop()                                   # the person said stop: the second call forces it
        self.save_all()
        if self.instance is not None:
            self.instance.release()                           # a second start must not find a window that is closing
        super().closeEvent(event)

    def ask_overwrite(self, dest):
        """A ZIP with this version name is already in the zip folder. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', f'{dest.name} is already in the zip folder.\nReplace it?') == QMessageBox.Yes

    def ask_zip(self, project):
        """Make ZIP was pressed: one short dialog (ZIP, EXE or both; user info and credentials, both off). None = cancelled.
        Tests replace this."""
        dialog = MakeZipDialog(project, self)
        return (dialog.include_user, dialog.include_credentials, dialog.kind) if dialog.exec() == QDialog.Accepted else None

    def make_zip(self):
        project = self.need_project()
        choice = self.ask_zip(project)
        if choice is None:
            self.say('Cancelled: nothing made')
            return
        user, credentials, kind = choice
        dest = core.made_zip_path(project, include_user=user, include_credentials=credentials)
        for path in core.package_paths(dest, kind):
            if path.exists() and not self.ask_overwrite(path):
                self.say(f'Cancelled: {path.name} left alone')
                return
        if kind != 'zip':
            self.say('Making the setup program (one compiler run, a few seconds)…')
        count, written = core.make_package(project, dest, kind, include_user=user, include_credentials=credentials)
        self.refresh()
        included = [name for name, on in (('user info', user), ('credentials', credentials)) if on]
        for path in written:
            if path.suffix == '.exe':
                self.say(f'Wrote zip\\{path.name}: the setup program, with {count} files inside ({path.stat().st_size // 1024} KB)')
            else:
                self.say(f'Wrote zip\\{path.name}: {count} files' + (f' (with {" and ".join(included)})' if included else ''))
        core.show_in_explorer(written[0])                     # the press must show a result: the zip folder opens with the new file selected

    def ask_replace_deploy(self, names):
        """The deploy folder holds an earlier program (and the folder it made when it was run there). 'delete' wipes all of it, 'backup' moves it into the zip folder,
        None = cancel. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Zygote', f'The deploy folder already holds: {", ".join(names)}.\n\nThe new program replaces all of it, including the home folder '
                          'and every file in it.', QMessageBox.NoButton, self)
        delete = box.addButton('Delete it', QMessageBox.AcceptRole)
        backup = box.addButton('Back it up first', QMessageBox.AcceptRole)
        box.addButton('Cancel', QMessageBox.RejectRole)
        box.exec()
        return 'delete' if box.clickedButton() is delete else 'backup' if box.clickedButton() is backup else None

    def ask_deploy(self, project, plan):
        """Deploy was pressed: the requirements file and the window choice. (requirements, window, args, ticked), or None when cancelled. Tests replace this."""
        from functional import deploy as deploying
        dialog = DeployDialog(project, plan, deploying.settings(project), self)
        return (dialog.requirements, dialog.window, dialog.args, dialog.ticked) if dialog.exec() == QDialog.Accepted else None

    def deploy(self):
        """Deploy: one program of the project, in the deploy folder at the top, named like the project. Its own button next to Make ZIP (Make ZIP stays the snapshot)."""
        from functional import deploy as deploying
        project = self.need_project()
        plan = deploying.plan(project)                         # refuses loudly (no entry point, not Python) before anything is asked
        choice = self.ask_deploy(project, plan)
        if choice is None:
            self.say('Cancelled: nothing deployed')
            return
        deploying.save_settings(project, *choice)
        old = deploying.old_output(project)
        if old:                                                # the exe AND its home folder go together: a home left behind would start stale files
            answer = self.ask_replace_deploy([path.name for path in old])
            if answer is None:
                self.say(f'Cancelled: {", ".join(path.name for path in old)} left alone')
                return
            if answer == 'backup':
                self.say(f'Earlier deploy moved to {deploying.backup_old(project)}')
            else:
                self.say(f'Earlier deploy removed: {", ".join(deploying.remove_old(project))}')
        self.say('Making the program (one compiler run, a few seconds)…')
        path, count = deploying.build(project)
        self.refresh()
        self.say(f'Wrote deploy\\{path.name}: {count} project files inside ({path.stat().st_size // 1024} KB). On another computer it unpacks {deploying.home_name(project)} beside itself and starts {plan["entry"]}.')
        core.show_in_explorer(path)

    def ask_drop(self, judged):
        """A dropped build that goes back to an older version (or has no version to compare): ask, and No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Warning, 'Zygote', judged['text'], QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)                    # the safe answer is the default
        return box.exec() == QMessageBox.Yes

    def refuse_drop(self, judged):
        """A dropped build that is not an update of this project: said loudly and not unpacked. When it is another project's build, a second button offers to open it as a
        new project (True is returned for it). Tests replace this."""
        box = QMessageBox(QMessageBox.Critical, 'Zygote - not an update of this project', '', QMessageBox.NoButton, self)
        box.setTextFormat(Qt.RichText)
        box.setText(f'<b>{html.escape(judged["text"]).replace(chr(10), "<br>")}</b>')      # no colour of its own: the dialog's words follow the brightness of the person's colour (theme)
        new = box.addButton('Open as a new project', QMessageBox.AcceptRole) if judged.get('new_project') else None
        ok = box.addButton('OK', QMessageBox.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        return new is not None and box.clickedButton() is new

    def ask_new_project_place(self, zip_path, name):
        """Where the new project's folder goes: the person picks the folder it is made in (the folder NAME is made inside it). None = cancelled. Tests replace this."""
        desktop = Path.home() / 'Desktop'
        start = str(desktop if desktop.is_dir() else Path(zip_path).parent)
        chosen = QFileDialog.getExistingDirectory(self, f'Where should the new project {name} go? A folder called {name} is made inside the one you pick '
                                                  f'(one that is there already is moved aside, never deleted).', start)
        return Path(chosen) if chosen else None

    def open_zip_as_new_project(self, zip_path):
        """A build ZIP becomes a project of its own: asks where, unpacks there (an old folder of that name is moved aside, never deleted), opens it. With no project open it
        opens in this window; otherwise in a window of its own. This window's project is never written to."""
        zip_path = Path(zip_path)
        plan = core.inspect_zip(zip_path)
        name = core.new_project_name(plan)
        parent = self.ask_new_project_place(zip_path, name)
        if parent is None:
            self.say(f'Cancelled: {zip_path.name} was not opened as a project.')
            return None
        if self.project is not None and (parent / name).resolve() == Path(self.project).resolve():
            raise core.ZygoteError(f'{name} here is the project that is open now. Pick another folder for the new project.')
        dest, old = core.unpack_new_project(zip_path, parent)
        if old is not None:
            self.say(f'The folder {name} was already there: moved to {old.name} beside it (delete it when you no longer need it).')
        self.say(f'{zip_path.name} unpacked as the new project {dest}.')
        if self.project is None:
            self.drop_project(dest)
        else:
            self.open_in_own_window(dest)
        return dest

    def install_zip(self, zip_path):
        """Take in one build ZIP. The guard judges it first (another project's build is refused, an older version is asked about); raises on any problem."""
        if self.project is None:                                # nothing to update: the ZIP can only become a project of its own
            return self.open_zip_as_new_project(zip_path)
        project = self.project
        plan = core.inspect_zip(zip_path)
        judged = core.check_drop(project, plan)
        if judged['verdict'] == 'refuse':
            self.say(f'Refused: {Path(zip_path).name} is not an update of this project. Nothing was unpacked.')
            if self.refuse_drop(judged):
                return self.open_zip_as_new_project(zip_path)
            return None
        if judged['verdict'] != 'ok' and not self.ask_drop(judged):
            self.say(f'Cancelled: {Path(zip_path).name} left alone')
            return None
        report = core.install_zip(zip_path, project)
        self.note(f'Installed {Path(zip_path).name}: {report["before"] or "?"} -> {report["after"] or "?"}')
        self.refresh()
        direction = core.version_direction(report['before'], report['after'])
        headline = f'Updated {report["before"] or "?"} -> {report["after"] or "?"} ({direction})'
        self.say(f'{Path(zip_path).name}: {headline}, {report["written"]} files replaced  (Project > Revert project… puts them back)')
        self.show_toast(f'Updated to {report["after"] or "?"}' + (f'  (older than {report["before"]})' if direction == 'back' else ''))
        names = core.protected_folders(report['skipped'])
        if names:
            self.say_protected('Not overwritten:', names)
        if report['restart_needed']:
            self.offer_restart(headline)
        return report

    def show_toast(self, text):
        """A message over the window that goes away by itself after about two seconds (the person sees at once which version was taken)."""
        self.toast = Toast(self, text)

    def ask_replace_asset(self, dest):
        """A dropped asset has the name of one that is already there. True = replace it. Tests replace this."""
        return QMessageBox.question(self, 'Zygote', f'{dest.name} is already in {dest.parent.name}.\nReplace it?') == QMessageBox.Yes

    def drop_asset(self, path):
        """A file that is not a ZIP was dropped: a known asset type is copied into its folder under app_tree\\assets (it asks before replacing a file).
        Any other type raises, loudly, with the types that are taken."""
        project = self.need_project()
        dest = core.asset_destination(project, path)
        if dest.exists() and not self.ask_replace_asset(dest):
            self.say(f'Cancelled: {dest.name} left as it is')
            return None
        core.add_asset(project, path)
        self.say(f'{dest.name} copied into app_tree\\assets\\{dest.parent.name}')
        self.show_toast(f'Added {dest.name} to assets\\{dest.parent.name}')
        self.refresh()
        return dest

    def choose_snapshot(self, snapshots):
        """Show the revert list. The snapshot file name the person picked, or None. Tests replace this."""
        dialog = RevertDialog(snapshots, self)
        return dialog.chosen if dialog.exec() == QDialog.Accepted else None

    def revert_project(self):
        project = self.need_project()
        chosen = self.choose_snapshot(core.list_snapshots(project))
        if chosen is None:
            return
        report = core.revert_project(project, chosen)
        self.note(f'Reverted {report["drops"]} drop(s): {report["version_after"]} -> {report["version_before"] or "?"}')
        self.refresh()
        self.say(f'Reverted {report["drops"]} drop(s) ({", ".join(report["zips"])}): {report["restored"]} files restored, '
                 f'{report["removed"]} new files removed ({report["version_after"]} -> {report["version_before"] or "?"})')
        if report['restart_needed']:
            direction = core.version_direction(report['version_after'], report['version_before'])
            self.offer_restart(f'Rolled back {report["version_after"]} -> {report["version_before"] or "?"} ({direction})')

    def ask_restart(self, headline):
        """Zygote's own files changed. True when the person presses Restart now."""
        box = QMessageBox(self)
        box.setWindowTitle('Zygote')
        box.setText(f'{headline}\n\nZygote\'s own files changed. Restart now to run this version?')
        restart = box.addButton('Restart now', QMessageBox.AcceptRole)
        box.addButton('Later', QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is restart

    def offer_restart(self, headline):
        self.say(f'{headline}: Zygote runs the old code until it restarts.')
        if self.ask_restart(headline):
            self.restart()

    def restart(self, updated=False):
        core.restart_zygote(self.project, updated)      # one process, started by a button
        self.close()

    # ---- events ----------------------------------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.source() is None:       # only from outside (Explorer): a file dragged inside Zygote is for a panel's drop box
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() is not None:
            return
        folders, files = [], []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                folders.append(path)
            elif path.suffix.lower() == '.zip':
                self.guarded(functools.partial(self.install_zip, path))                # a ZIP is still an update
            else:
                files.append(path)
        if self.is_zygote_itself():                                             # Zygote itself stays as it is: a folder is a project of its own, files are only added when the switch is on
            if folders or files:
                self.guarded(functools.partial(self.drop_on_zygote, folders, files))
        elif self.project is not None:                                          # a project is open: files and folders alike are only copied in, after a Yes
            if folders or files:
                self.guarded(functools.partial(self.drop_copy_in, folders + files))
        else:
            for path in folders:
                self.guarded(functools.partial(self.drop_project, path))        # no project open: as before
            for path in files:
                self.guarded(functools.partial(self.drop_asset, path))          # no project: said plainly (an asset needs a project)
        event.acceptProposedAction()

    # ---- Zygote itself: protected -------------------------------------------------------------------------------
    def is_zygote_itself(self):
        return self.project is not None and self.project == core.ZYGOTE_ROOT

    def show_zygote_menu(self):
        """The Zygote menu is there while Zygote itself is open, and its switch shows what is kept."""
        itself = self.is_zygote_itself()
        self.zygote_menu.menuAction().setVisible(itself)
        if itself:
            self.allow_adding_action.setChecked(core.allow_adding(self.project))

    def toggle_allow_adding(self):
        on = self.allow_adding_action.isChecked()
        core.set_allow_adding(self.project, on)
        self.say(f'Adding files to Zygote by dropping them: {"allowed" if on else "not allowed (a dropped folder opens as its own project)"}.')

    def ask_drop_choice(self, names, can_add):
        """A folder was dropped on Zygote itself. Returns 'project' (open or start it as a project in its own window), 'add' (copy it into the workbench; only offered when
        the switch is on) or None. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Zygote \u2014 dropped folder', f'{", ".join(names)} was dropped on Zygote.\n\nOpen it as a project in its own window?', parent=self)
        project = box.addButton('Open as a project', QMessageBox.AcceptRole)
        add = box.addButton('Add to the workbench', QMessageBox.ActionRole) if can_add else None
        box.addButton('Cancel', QMessageBox.RejectRole)
        box.setDefaultButton(project)
        box.exec()
        return 'project' if box.clickedButton() is project else ('add' if box.clickedButton() is add and add is not None else None)

    def drop_on_zygote(self, folders, files):
        """Things dropped on Zygote itself. A folder opens as a project in its own window (this Zygote stays); with the switch on it may also be added to the
        workbench. A file is only added when the switch is on; otherwise it is said, plainly, that Zygote is protected and nothing is copied."""
        can_add = core.allow_adding(self.project)
        added = []
        for folder in folders:
            choice = self.ask_drop_choice([folder.name], can_add)
            if choice == 'project':
                self.open_in_own_window(folder)
            elif choice == 'add':
                added.append(folder)
            else:
                self.say(f'Cancelled: {folder.name} was not opened.')
        if files and not can_add:
            self.say(f'Zygote is protected: {", ".join(path.name for path in files)} was not copied. Zygote > Allow adding files to Zygote turns adding on.')
            self.show_toast('Zygote is protected: nothing was added')
            files = []
        if added or files:
            self.drop_copy_in(added + files)

    def open_in_own_window(self, folder):
        """The folder opens as a project in a Zygote window of its own, as if its launcher was double-clicked: one process, started by this drop. When that project
        is already open its window comes forward instead. Its window asks for the update when its Zygote is older (see offer_core_update)."""
        folder = core.clean_path(folder)
        if self.project_runs_elsewhere(folder):
            return False
        core.start_zygote(folder)
        old = core.core_version(folder)
        self.say(f'Opening {folder.name} in its own window' + (f' (its Zygote is {old}; this one is {core.installed_version()}).' if old else ' (it has no Zygote core copy yet).'))
        self.show_toast(f'Opening {folder.name}…')
        return True

    def offer_core_update(self):
        """A project (not Zygote itself) whose own copy of Zygote is older than the installed one: the update is offered, once per start. No leaves it as it is."""
        if self.project is None or self.is_zygote_itself() or core.core_version(self.project) == core.installed_version():
            return False
        return self.update_core()

    def ask_copy_in(self, names, folder):
        """Folders were dropped on an open project: True = copy them into the folder in view. No is the default. Tests replace this."""
        box = QMessageBox(QMessageBox.Question, 'Zygote \u2014 copy these in?', f'Copy {", ".join(names)} into {folder}?\n\nThe originals stay where they are.', QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def drop_copy_in(self, folders):
        project = self.need_project()
        folder = self.shown_folder() or str(project)
        if not self.ask_copy_in([path.name for path in folders], Path(folder).name or folder):
            self.say('Cancelled: nothing was copied.')
            return []
        made = core.copy_in_from_outside(project, folders, folder)
        self.say(f'Copied {len(made)} item(s) into {Path(folder).name}: ' + ', '.join(path.name for path in made))
        self.icon_model.reload(str(folder))
        return made

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.refresh()
        super().changeEvent(event)
