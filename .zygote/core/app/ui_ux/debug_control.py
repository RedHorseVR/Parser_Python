"""Stepping through the debug entry point of the open project: the toolbar buttons, the Debug menu and the code window work through this one class.

Run debug is the same path as Continue (F5). Step over (F10), Step into (F11) or Continue (F5) with no debug run going START one: the debugger of the project's
language bundle (Python: pdb) runs the debug entry point in the Console tab. Where it stops is read from its own output (no extra process, no
timer); the code window shows that file and line. Only a button press starts or ends anything; closing a code tab never stops the run."""
from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QMessageBox, QSplitter

from functional import core, debugger
from functional.core import ZygoteError
from PySide6.QtCore import QPoint

from ui_ux.code_window import BreakpointsWindow, CodeFloat, CodeWindow, read_source
from ui_ux.shell_tabs import TabGhost


class DebugControl:
    TOP = 'top'                                                    # the start key of a restart: stop at the first line

    def __init__(self, window):
        self.window = window
        self.bundle = None                                         # the bundle of the debug run that is going
        self.reader = None                                         # reads its output
        self.live = False                                          # a debug run is going in the Console
        self.waiting = False                                       # the debugger shows its prompt: it can be told what to do
        self.first = None                                          # the bundle key of the button that started the run (typed at the first prompt)
        self.read_one = self.warned = False                        # a position was read in this run / the missing position was already reported
        self.queue = []                                            # breakpoint changes made while the program ran: typed at its next prompt
        self.listening = None                                      # the console view this listens to
        self.code = None                                           # the CodeWindow, made when first needed
        self.floating = None                                       # the CodeFloat window while the code window is torn off
        self.ghost = None                                          # the torn tab that follows the cursor while the mouse is down
        self.breakpoint_window = None                              # the Breakpoints list window, made when first needed

    # ---- questions (tests replace these) ----------------------------------------------------------------------
    def ask(self, text):
        return QMessageBox.question(self.window, 'Zygote', text) == QMessageBox.Yes

    def pick(self, title, names):
        name, ok = QInputDialog.getItem(self.window, 'Zygote', title, names, 0, False)
        return name if ok else None

    # ---- the code window --------------------------------------------------------------------------------------
    def code_window(self):
        if self.code is None:
            self.code = CodeWindow()
            self.code.breakpointToggled.connect(lambda path, line: self.window.guarded(lambda: self.toggle(path, line)))
            self.code.pathsDropped.connect(lambda paths: self.window.guarded(lambda: self.open_dropped(paths)))
            self.code.dropRefused.connect(self.window.say)
            self.code.emptied.connect(self.hide_code)               # the last tab closed: the Console has the whole panel again
            self.code.tabBar().tear_wanted.connect(self.begin_tear)
            self.code.tabBar().tear_moved.connect(self.move_tear)
            self.code.tabBar().tear_dropped.connect(lambda where: self.window.guarded(lambda: self.end_tear(where)))
            self.window.console_split.addWidget(self.code)
            self.code.hide()
        return self.code

    def hide_code(self):
        self.dock_back()
        self.code.hide()

    def begin_tear(self, where):
        """The tab left the bar: a ghost of it follows the cursor, as a shell tab does."""
        name = self.code.tabText(self.code.currentIndex()) if self.code.count() else 'code'
        self.ghost = TabGhost(name, ('#2b2b2b', '#d4d4d4'))
        self.ghost.carry_to(where)
        self.ghost.show()

    def move_tear(self, where):
        if self.ghost is not None:
            self.ghost.carry_to(where)

    def end_tear(self, where):
        if self.ghost is not None:
            self.ghost.hide()
            self.ghost.deleteLater()
            self.ghost = None
        self.tear_off(where)

    def tear_off(self, where):
        """The code window leaves the Console tab for a window of its own where the mouse was let go (the Console keeps the whole panel)."""
        code = self.code_window()
        if self.floating is None and code.count():
            self.floating = CodeFloat(code)
            self.floating.dock_wanted.connect(lambda: self.window.guarded(self.dock_back))
            self.floating.close_wanted.connect(lambda: self.window.guarded(self.close_floating))
            self.floating.move(where - QPoint(80, 12))
            self.floating.show()
            self.window.say('The code window is in a window of its own. Its X closes it; minimize it to put it back beside the Console.')
        return self.floating

    def close_floating(self):
        """The X of the torn-off window: the code window is closed for real. With several files open it asks first (breakpoints are kept in the project)."""
        count = self.code.count()
        if count > 1 and not self.ask(f'Close the code window and its {count} files?'):
            return
        self.dock_back()
        self.code.close_all()
        self.code.hide()

    def dock_back(self):
        """Put a torn-off code window back beside the Console."""
        if self.floating is not None:
            floating, self.floating = self.floating, None
            self.window.console_split.addWidget(self.code)
            floating.hide()
            floating.deleteLater()
            self.code.show()

    def show_window(self):
        code = self.code_window()
        if self.floating is not None:
            self.floating.raise_()
            self.floating.activateWindow()
            return code
        self.window.console_view()                                  # the Console shows (black, empty) beside the code from the start: the person sees it is there
        self.window.bottom_tabs.setCurrentWidget(self.window.console_page)     # from the Log or a shell tab too: the code window lives on this tab
        if code.isHidden():
            code.show()
            split = self.window.console_split
            total = max(split.width(), 600)
            split.setSizes([total * 55 // 100, total * 45 // 100])
        return code

    def project(self):
        return self.window.need_project()

    def open_source(self, path):
        """The tab of a file: read-only text, with its breakpoints. None when the file cannot be shown (the debugger can stop in files that are not on disk)."""
        path = Path(path)
        text = read_source(path)
        if text is None:
            return None
        project = self.project()
        bundle = self.bundle or debugger.bundle_for(project, path)
        lines = []
        if bundle is not None:
            store = debugger.Breakpoints(project, bundle)
            try:
                lines, _ = store.read(path)
            except ZygoteError:
                lines = []                                         # a file outside the project has no breakpoints
            self.report_dropped(store)
        view = self.show_window().open_file(path, text, lines)
        return view

    def report_dropped(self, store):
        for file, count in store.dropped:
            self.window.say(f'{Path(file).name} changed since its {count} breakpoint(s) were set: they are dropped (the lines may have moved).')
        store.dropped.clear()

    # ---- the debug entry point and its bundle ------------------------------------------------------------------
    def entry(self):
        project = self.project()
        kind, rel = core.run_choice(project, 'debug')
        if kind != 'entry':
            raise ZygoteError(f'Debugging needs a debug entry point: {rel}. Set it in Settings > Project settings… (Debug).')
        return Path(project) / rel

    def pick_bundle(self, entry):
        """The bundle that owns the entry file. A project without one is offered Zygote's matching bundle (nothing is added without a Yes)."""
        project = self.project()
        bundle = debugger.bundle_for(project, entry)
        if bundle is not None:
            return bundle
        matching = [name for name in debugger.shelf_names() if debugger.Bundle(debugger.SHELF / name).owns(entry)]
        if not matching:
            raise ZygoteError(f'No language bundle owns {entry.name}: this project has none for {entry.suffix or "this file type"}, and Zygote\'s shelf has none either.')
        if not self.ask(f'This project has no language bundle for {entry.suffix} files. Zygote has one: {matching[0]}. Add it to the project (app_tree\\language\\{matching[0]})?'):
            raise ZygoteError(f'Not started: stepping through {entry.name} needs the {matching[0]} language bundle.')
        debugger.add_from_shelf(project, matching[0])
        self.window.say(f'Language bundle {matching[0]} added to the project.')
        return debugger.bundle_for(project, entry)

    # ---- the buttons -------------------------------------------------------------------------------------------
    def press(self, key):
        """step_over, step_into or continue (the bundle's names): typed to a stopped debugger, or they start the debug run."""
        if self.live and self.waiting:
            self.send([self.bundle.text(key)])
        elif self.live:
            self.window.say(f'The program is running (the debugger prompt has not been seen). Press Stop debugging to end it. Last output: {self.reader.seen()}')
        else:
            self.start(key)

    def breakpoint_count(self):
        """How many breakpoints the project has (all its language bundles)."""
        project = self.window.project
        if project is None:
            return 0
        return sum(len(lines) for bundle in debugger.bundles(project) for lines in debugger.Breakpoints(project, bundle).everything().values())

    def sync(self):
        """Light the debug buttons that can do something now (the window decides how they look). Called whenever the state changes."""
        console = self.window.console
        stopped = bool(self.live and self.waiting)
        running = bool(self.live) or (console is not None and console.is_running())
        self.window.set_debug_states(running, stopped, self.breakpoint_count())

    def can_debug(self):
        """True when a language bundle (the project's, else Zygote's shelf) owns the debug entry point: then Run debug is the debugger's Continue."""
        try:
            entry = self.entry()
        except ZygoteError:
            return False
        if debugger.bundle_for(self.project(), entry) is not None:
            return True
        return any(debugger.Bundle(debugger.SHELF / name).owns(entry) for name in debugger.shelf_names())

    def start(self, key):
        project = self.project()
        entry = self.entry()
        bundle = self.pick_bundle(entry)
        words = bundle.start_words(project, entry, core.run_settings(project, 'debug')['args'])
        self.bundle, self.reader = bundle, debugger.PositionReader(bundle)
        self.waiting, self.queue = False, []
        self.read_one = self.warned = False
        self.open_source(entry)
        if not self.window.run_in_console(words, f'debug: {" ".join(words)}'):
            self.bundle = self.reader = None
            return
        self.live, self.first = True, key
        self.sync()
        console = self.window.console
        if self.listening is not console:
            console.output.connect(self.output)
            console.finished.connect(self.ended)
            self.listening = console
        orphans = debugger.Breakpoints(project, bundle).orphans()
        for orphan in orphans:
            self.window.say(f'Breakpoints without a source file: {orphan.name} is not in the project any more (its breakpoint file is still there).')

    def restart(self):
        """The Restart button: asks, then ends what runs in the Console (when something does) and starts the debug run again, stopped at its first line.
        It works from any state: nothing running, running, or stopped at a prompt."""
        if not self.ask('Restart the debugger from the top?'):
            return
        console = self.window.console
        if console is not None and console.is_running():
            self.window.stop_console()
        self.live = self.waiting = False
        self.start(self.TOP)

    def send(self, texts):
        self.waiting = False
        self.sync()
        self.reader.reset()
        self.window.console.send_text('\n'.join(texts) + '\n')

    def output(self, text):
        """What the debugger printed (in the window's thread). Its prompt means it stopped; the last 'file(line)' before it says where."""
        if not self.live:
            return
        stop = self.reader.feed(text)
        if stop is None:
            return
        self.waiting = True
        self.sync()
        if self.reader.finished:                                   # the program ended: the debugger would start it over, so it is told to quit
            self.window.say('Debug: the program finished.')
            self.send([self.bundle.text('quit')])
            return
        path, line = stop
        if path:
            self.read_one = True
            count = len(self.reader.positions)
            self.window.say(f'Debug: stopped at {Path(path).name} line {line}' + (f' (read {count} positions in the output, took the last)' if count > 1 else ''))
            self.show_stop(path, line)
        elif not self.read_one and not self.warned:
            self.warned = True                                     # the first prompts of a run print no position; only a run that never shows one is reported
            self.window.say(f'Debug: the debugger stopped but no file and line could be read. Last output: {self.reader.seen()}')
        self.at_prompt()

    def at_prompt(self):
        if self.first:
            key, self.first = self.first, None
            texts = [self.bundle.text('set_breakpoint', file=file, line=line) for file, lines in self.stored().items() for line in lines]
            if key == self.TOP:                                    # restart: only the breakpoints are typed, the program stays stopped at its first line
                if texts:
                    self.send(texts)
                return
            self.send(texts + [self.bundle.text(key)])
        elif self.queue:
            texts, self.queue = self.queue, []
            self.send(texts)

    def stored(self):
        store = debugger.Breakpoints(self.project(), self.bundle)
        found = store.everything()
        self.report_dropped(store)
        return found

    def show_stop(self, path, line):
        view = self.open_source(path)
        if view is None:
            return
        self.code_window().show_stop(path, line)
        self.window.bottom_tabs.setCurrentWidget(self.window.console_page)

    def ended(self, code):
        """A program of the Console ended. The end of an OLD program can arrive after a new one was started (a Run or a Step asked the old one to stop): it must not end the new run."""
        if self.window.console is not None and self.window.console.is_running():
            return
        if self.live:
            self.live = self.waiting = False
            if self.code is not None:
                self.code.clear_stop()
        self.sync()

    def stop(self):
        console = self.window.console
        if self.live or (console is not None and console.is_running()):
            self.window.stop_console()                             # Run debug is not a debugger run, but this button ends what the Console runs all the same
        else:
            self.window.say('There is no debug run to stop.')

    # ---- breakpoints -------------------------------------------------------------------------------------------
    def toggle(self, path, line):
        """A line number was clicked in the code window: set or clear its breakpoint (kept in the bundle's folder; a run that is going is told)."""
        project = self.project()
        bundle = self.bundle or debugger.bundle_for(project, path)
        if bundle is None:
            bundle = self.pick_bundle(Path(path))                  # a project without the language's bundle is offered Zygote's (a Yes adds it); loud when none fits
        store = debugger.Breakpoints(project, bundle)
        try:
            on = store.toggle(path, line)
        except ZygoteError as error:
            self.window.say(str(error))
            return
        self.report_dropped(store)
        self.code_window().view_of(path).set_breakpoints(store.read(path)[0])
        self.window.say(f'Breakpoint {"set" if on else "cleared"}: {Path(path).name} line {line}')
        self.sync()
        if self.live:
            self.tell(bundle.text('set_breakpoint' if on else 'clear_breakpoint', file=path, line=line))

    def tell(self, text):
        """Type a breakpoint change to the debugger now when it waits, else at its next prompt."""
        if self.waiting:
            self.send([text])
        else:
            self.queue.append(text)

    def clear_all(self):
        project = self.project()
        total = 0
        for bundle in debugger.bundles(project):
            removed = debugger.Breakpoints(project, bundle).clear()
            for file, lines in removed.items():
                total += len(lines)
                if self.live and bundle is self.bundle:
                    for line in lines:
                        self.tell(bundle.text('clear_breakpoint', file=file, line=line))
        if self.code is not None:
            for view in self.code.views():
                view.set_breakpoints([])
        self.window.say(f'{total} breakpoint(s) cleared.' if total else 'There were no breakpoints.')
        self.sync()

    def list_breakpoints(self):
        project = self.project()
        found = {file: lines for bundle in debugger.bundles(project) for file, lines in debugger.Breakpoints(project, bundle).everything().items()}
        if self.breakpoint_window is None:
            self.breakpoint_window = BreakpointsWindow(self.window)
        self.breakpoint_window.show_found(found)
        self.breakpoint_window.show()
        self.breakpoint_window.raise_()
        self.window.say(f'Breakpoints: {sum(len(lines) for lines in found.values())} in {len(found)} file(s).')

    # ---- the Debug menu ----------------------------------------------------------------------------------------
    def show_code(self):
        """Show code window: the debug entry point's file, so breakpoints can be set before the run. With no entry point the window opens empty and the Log says why."""
        try:
            entry = self.entry()
        except ZygoteError as error:
            self.show_window()
            self.window.say(f'Code window: {error}')
            return
        if self.open_source(entry) is None:
            self.show_window()
            self.window.say(f'Code window: {entry.name} cannot be shown (it is missing or too large).')

    def toggle_window(self):
        """The Code button: hides the code window when it is shown, shows it (with the entry point's file) when it is not."""
        if self.floating is not None:
            self.dock_back()
            self.code.hide()
        elif self.code is not None and not self.code.isHidden():
            self.code.hide()
        else:
            self.show_code()

    def close_files(self, paths):
        """Files thrown away or renamed in the workbench: their tabs in the code window close (the Console has the whole panel when none is left)."""
        return self.code.close_paths(paths) if self.code is not None else []

    def open_dropped(self, paths):
        """Files dragged from the folder view: a text file opens in a tab (one already open just comes forward); anything else is refused with a Log line."""
        for path in paths:
            path = Path(path)
            if path.is_dir():
                self.window.say(f'Not opened: {path.name} is a folder.')
            elif not core.is_text_file(path):
                self.window.say(f'Not opened: {path.name} is not a text file.')
            else:
                self.open_source(path)

    def language_bundle(self):
        project = self.project()
        have = [bundle.name for bundle in debugger.bundles(project)]
        missing = [name for name in debugger.shelf_names() if not core.zpath(project, debugger.LANGUAGE, name).exists()]
        self.window.say(f'Language bundles of this project: {", ".join(have) if have else "none"}.')
        if not missing:
            return
        name = self.pick('Add a language bundle from Zygote\'s shelf to this project:', missing)
        if name:
            debugger.add_from_shelf(project, name)
            self.window.say(f'Language bundle {name} added (app_tree\\language\\{name}).')
