"""Zygote's look, in one place: two palettes (dark is the default, light is the option), the style block and the colors
that other parts of the window share.

Every color is stated explicitly, so text stays readable whatever theme Windows is set to (a light button with white text
is the bug this prevents). One rule per selector; no widget carries its own color, it takes an object name and is styled here.
"""
from PySide6.QtGui import QColor, QPalette
from functional import core


class Theme:
    MODES = {
        'dark': dict(window='#1e052b', base='#1e1e1e', text='#e6e6e6', disabled='#8a8a8a', dim='#a0a0a0',
                     button_top='#f2f2f2', button_bottom='#cfcfcf', hover='#e3efff', pressed='#b9cde8',
                     highlight='#2f6fb8', title_bg='#383838', title_border='#555555', frame='#6a6a6a',
                     drop_bg='#262626', error='#ff7b7b', warning='#ffd23f', sacred='#5aa9ff', rebuild='#2ec4b6', work='#8fd18f', outline='#ffffff', bright='#ffc94d'),
        'light': dict(window='#f0f0f0', base='#ffffff', text='#111111', disabled='#8a8a8a', dim='#6a6a6a',
                      button_top='#fdfdfd', button_bottom='#d9d9d9', hover='#eaf3ff', pressed='#c4d6ee',
                      highlight='#3b7bd4', title_bg='#e4e4e4', title_border='#b0b0b0', frame='#7a7a7a',
                      drop_bg='#f6f6f6', error='#b00020', warning='#8a6d00', sacred='#1f6fb5', rebuild='#00796b', work='#1f7a1f', outline='#8a8a8a', bright='#b35c00'),
    }
    DEFAULT = 'dark'
    BUTTON_TEXT = '#000000'              # buttons stay light in both themes, so their text is always black
    SACRED_HUE = 205                     # the yellow of a folder icon becomes this blue (0..359)
    WORK_HUE = 120                       # ... and this green for the folders the person works on
    mode = DEFAULT
    outer = None                         # the person's colour for the outer container (menu bar, toolbar, frame): one colour in both themes
    SACRED_TEXT = MODES[DEFAULT]['sacred']      # names of folders a build ZIP never overwrites: tree, icon view and log
    WORK_TEXT = MODES[DEFAULT]['work']          # names of the files and folders the person works on (not Zygote's own structure)
    STYLE = ''

    @classmethod
    def colors(cls):
        colors = cls.MODES[cls.mode]
        return dict(colors, window=cls.outer) if cls.outer else colors

    @staticmethod
    def check_outer(text):
        """A colour written like #1a7a1a. Raises ValueError for anything else (no silent default)."""
        if not (isinstance(text, str) and text.startswith('#') and QColor.isValidColorName(text)):
            raise ValueError(f'not a colour like #1a7a1a: {text!r}')
        return QColor(text).name()

    @classmethod
    def style(cls):
        c = cls.colors()
        bar = QColor(c['window'])
        note = '#000000' if (0.299 * bar.redF() + 0.587 * bar.greenF() + 0.114 * bar.blueF()) > 0.5 else c['text']          # the note under the version: black on a light bar, the text colour on a dark one, never grey on the bar colour
        light_window = (0.299 * bar.redF() + 0.587 * bar.greenF() + 0.114 * bar.blueF()) > 0.5
        on_window = '#111111' if light_window else '#f2f2f2'            # the words on a dialog's own background (the person's colour): dark on a light one, light on a dark one, whatever the theme
        error_fill = QColor(c['error'])
        on_error = '#000000' if (0.299 * error_fill.redF() + 0.587 * error_fill.greenF() + 0.114 * error_fill.blueF()) > 0.5 else '#ffffff'      # the words of the red toast
        error_on_window = '#b00020' if light_window else '#ff9a9a'
        base = QColor(c['base'])
        check = core.ui_picture('check_dark.png' if (0.299 * base.redF() + 0.587 * base.greenF() + 0.114 * base.blueF()) > 0.5 else 'check_light.png').as_posix()     # a check mark in the text's contrast, never a filled square
        tick_check = core.ui_picture('check_dark.png').as_posix()       # the boxes of the layout panel and the tick lists: always a light box with a black mark, clear on a dark window
        tick_dash = core.ui_picture('dash_dark.png').as_posix()
        return f'''
QToolBar {{ background: {c['window']}; border: none; spacing: 6px; }}
QPushButton {{ color: {cls.BUTTON_TEXT}; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {c['button_top']}, stop:1 {c['button_bottom']});
              border: 1px solid {c['outline']}; border-radius: 4px; padding: 5px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {c['hover']}; border-color: {c['highlight']}; }}
QPushButton:pressed {{ background: {c['pressed']}; padding-top: 6px; padding-bottom: 4px; }}
QPushButton:disabled {{ color: {c['disabled']}; }}
QPushButton#toolbutton, QPushButton#toolbutton:pressed {{ padding: 0 12px; min-height: 0; }}
QPushButton#picturebutton {{ background: transparent; border: none; padding: 0; min-height: 0; }}
QPushButton#picturebutton:hover {{ background: {c['hover']}; }}
QCheckBox {{ color: {c['text']}; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {c['text']}; border-radius: 2px; background: {c['base']}; }}
QCheckBox::indicator:checked {{ image: url({check}); }}
QListWidget#tickbox::indicator {{ width: 16px; height: 16px; border: 1px solid #4a4a4a; border-radius: 2px; background: #f4f4f4; }}
QListWidget#tickbox::indicator:checked, QListWidget#tickbox::indicator:checked:disabled {{ image: url({tick_check}); }}
QListWidget#tickbox::indicator:indeterminate, QListWidget#tickbox::indicator:indeterminate:disabled {{ image: url({tick_dash}); }}
QListWidget#tickbox::indicator:disabled {{ background: #e6e6e6; border: 1px solid #777777; }}
QFrame#layoutrule {{ color: #9a9a9a; }}
QLabel#restartwarning {{ color: #ffc24a; font-weight: bold; font-size: 14px; }}
QWidget#restartnote {{ background: #ffd54a; border-radius: 4px; }}
QLabel#restarttext {{ color: #5a0000; font-weight: bold; background: transparent; }}
QLabel {{ color: {c['text']}; }}
QMenuBar {{ color: {c['text']}; background: {c['window']}; }}
QMenuBar::item:selected {{ background: {c['highlight']}; }}
QMenu {{ color: {c['text']}; background: {c['base']}; border: 1px solid {c['title_border']}; }}
QMenu::item:selected {{ color: #ffffff; background: {c['highlight']}; }}
QMenu::separator {{ height: 1px; background: {c['outline']}; margin: 4px 8px; }}
QGroupBox {{ color: {c['text']}; border: 1px solid {c['title_border']}; border-radius: 4px; margin-top: 10px; padding: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QMenu::item:disabled {{ color: {c['disabled']}; }}
QTreeView, QListView, QPlainTextEdit, QTextBrowser {{ color: {c['text']}; background: {c['base']}; border: 1px solid {c['title_border']}; }}
QSplitter::handle {{ background: {c['title_border']}; }}
QToolTip {{ color: #000000; background: #ffffe1; border: 1px solid #555555; }}
QTabBar::tab {{ color: {c['text']}; background: {c['title_bg']}; border: 1px solid {c['text']}; border-bottom: none; padding: 3px 14px; margin-right: 2px; }}
QTabBar::tab:selected {{ color: {c['bright']}; background: {c['base']}; font-weight: bold; }}
QTabBar::tab:hover {{ background: #ffffff; color: #000000; }}
QTabBar::tab:selected:hover {{ background: #ffffff; color: #000000; }}
#consolepage {{ background: #000000; }}
#panelheader {{ background: {c['title_bg']}; border-bottom: 1px solid {c['title_border']}; }}
#paneltitle {{ color: {c['text']}; font-weight: bold; padding: 4px 8px; }}
QComboBox {{ color: {c['text']}; background: {c['base']}; border: 1px solid {c['title_border']}; border-radius: 3px; padding: 2px 8px; }}
QComboBox QAbstractItemView {{ color: {c['text']}; background: {c['base']}; selection-background-color: {c['highlight']}; selection-color: #ffffff; }}
QHeaderView::section {{ color: {c['text']}; background: {c['title_bg']}; border: none; border-right: 1px solid {c['title_border']}; padding: 3px 6px; }}
QTableWidget {{ color: {c['text']}; background: {c['base']}; border: 1px solid {c['title_border']}; gridline-color: {c['title_border']}; }}
#bright {{ color: {c['bright']}; }}
#toast {{ color: #000000; background: {c['bright']}; border: 2px solid #ffffff; border-radius: 8px; padding: 10px 26px; font-size: 16px; font-weight: bold; }}
#toast[kind="warning"] {{ color: {on_error}; background: {c['error']}; }}
#dropbox {{ border: 2px dashed {c['frame']}; border-radius: 6px; color: {c['text']}; background: {c['drop_bg']}; }}
#entryline {{ border: 2px dotted {c['frame']}; border-radius: 4px; padding: 3px; }}
#dim {{ color: {note}; }}
#error {{ color: {c['error']}; }}
QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QDialog QGroupBox {{ color: {on_window}; }}
QDialog #error {{ color: {error_on_window}; }}
'''

    @classmethod
    def palette(cls):
        c = cls.colors()
        palette = QPalette()
        for role, color in ((QPalette.Window, c['window']), (QPalette.WindowText, c['text']), (QPalette.Base, c['base']),
                            (QPalette.AlternateBase, c['window']), (QPalette.Text, c['text']), (QPalette.Button, c['button_bottom']),
                            (QPalette.ButtonText, cls.BUTTON_TEXT), (QPalette.Highlight, c['highlight']),
                            (QPalette.HighlightedText, '#ffffff'), (QPalette.ToolTipBase, '#ffffe1'),
                            (QPalette.ToolTipText, '#000000'), (QPalette.PlaceholderText, c['disabled'])):
            palette.setColor(role, QColor(color))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(c['disabled']))
        return palette

    @classmethod
    def apply(cls, app, mode=None):
        """Switch the whole application to 'dark' or 'light'. Raises on any other name (no silent default)."""
        if mode is not None:
            if mode not in cls.MODES:
                raise ValueError(f'unknown theme: {mode}')
            cls.mode = mode
        cls.SACRED_TEXT = cls.colors()['sacred']
        cls.WORK_TEXT = cls.colors()['work']
        cls.STYLE = cls.style()
        app.setStyle('Fusion')
        app.setPalette(cls.palette())
        app.setStyleSheet(cls.STYLE)
