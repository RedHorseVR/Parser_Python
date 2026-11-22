"""Tests of Parser_Python: the rows the parser writes, the exporter, the round trip check, and the parser parsing itself.
Run: python test_parser.py   (Black must be installed)"""

import glob
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP = os.path.join(ROOT, "app")
sys.path.insert(0, APP)

import FlowFile  # noqa: E402
import FlowToPy  # noqa: E402
import PyComments  # noqa: E402
import RoundTrip  # noqa: E402
import SameProgram  # noqa: E402
import parse_Python  # noqa: E402
from FlowFile import Row  # noqa: E402


def rows(text):
    return parse_Python.rows_of(RoundTrip.black_text(text))


def kinds(text):
    return [row.kind for row in rows(text)]


def round_trip(text):
    """The Check of Python text, through a real flow file."""
    formatted = RoundTrip.black_text(text)
    folder = tempfile.mkdtemp()
    try:
        path = os.path.join(folder, "case.vfc")
        FlowFile.write_file(path, parse_Python.rows_of(formatted), "_case.py")
        return RoundTrip.check(formatted, path)
    finally:
        shutil.rmtree(folder)


class RowTests(unittest.TestCase):
    def test_statements_and_their_kinds(self):
        text = "import os\nx = 1\ndef f(a):\n    return a\nclass C:\n    pass\n"
        self.assertEqual(
            kinds(text), ["event", "set", "input", "set", "end", "input", "set", "end"]
        )

    def test_a_signature_that_black_cuts_over_lines_is_one_row(self):
        text = "def add_comments(self, filename: str, output_filename: Optional[str] = None, more: int = 1) -> str:\n    pass\n"
        found = rows(text)
        self.assertEqual(len([r for r in found if r.kind == "input"]), 1)
        self.assertTrue(found[0].text.startswith("def add_comments("))
        self.assertIn("filename: str,", found[0].text)
        self.assertTrue(found[0].text.endswith(") -> str:"))

    def test_if_elif_else(self):
        text = "if a:\n    x = 1\nelif b:\n    x = 2\nelse:\n    x = 3\n"
        self.assertEqual(
            kinds(text), ["branch", "path", "set", "path", "set", "path", "set", "bend"]
        )
        self.assertEqual([r.text for r in rows(text) if r.kind == "path"], ["", "elif b:", "else:"])

    def test_an_if_inside_an_else_is_not_an_elif(self):
        text = "if a:\n    x = 1\nelse:\n    if b:\n        x = 2\n"
        self.assertEqual([r.text for r in rows(text) if r.kind == "path"], ["", "else:", ""])

    def test_loops_with_else_and_try(self):
        text = "for i in y:\n    pass\nelse:\n    z = 1\ntry:\n    a()\nexcept E as e:\n    b()\nelse:\n    c()\nfinally:\n    d()\n"
        self.assertEqual(
            kinds(text),
            [
                "loop",
                "set",
                "path",
                "set",
                "lend",
                "branch",
                "path",
                "set",
                "path",
                "set",
                "path",
                "set",
                "path",
                "set",
                "bend",
            ],
        )

    def test_with_and_decorators(self):
        text = "@dec(1)\ndef f():\n    with open(a) as h:\n        pass\n"
        self.assertEqual(kinds(text), ["set", "input", "branch", "path", "set", "bend", "end"])
        self.assertEqual(rows(text)[0].text, "@dec(1)")

    def test_a_comment_after_code_is_the_comment_of_its_row_and_one_on_a_line_is_a_row(
        self,
    ):
        found = rows("# above\nx = 1  #  two spaces\n")
        self.assertEqual(found[0], Row("set", "", " above"))
        self.assertEqual(found[1], Row("set", "x = 1", "  two spaces"))

    def test_the_comment_of_a_header_is_on_the_header(self):
        self.assertEqual(rows("else_ = 1\nif a:  # why\n    pass\n")[1].comment, " why")

    def test_a_string_over_several_lines_keeps_its_lines_as_they_are(self):
        found = rows('def f():\n    x = """one\n  two\n\tthree"""\n    return x\n')
        self.assertEqual(
            [r.kind for r in found],
            ["input", "set", "generic", "generic", "set", "end"],
        )
        self.assertEqual(found[3].text, '\tthree"""')

    def test_a_comment_inside_a_statement_stays_where_it_is(self):
        text = "x = foo(\n    1,  # one\n    2,\n)\n"
        self.assertEqual([r.kind for r in rows(text)], ["set", "generic", "generic", "generic"])

    def test_non_ascii_text_is_cut_in_the_right_place(self):
        self.assertEqual(rows("x = 'é' + y\n")[0].text, 'x = "é" + y')

    def test_a_row_cannot_hold_the_end_mark(self):
        with self.assertRaises(FlowFile.FlowError):
            FlowFile.row_line(Row("set", 'x = ")' + ';//"', None))


class VarTests(unittest.TestCase):
    TEXT = 'x = 1\nENDS = [\n    "a",\n    "b",  # why\n]\nBEGINS = {\n    "k": 1,\n}\ny = []\n'

    def test_a_literal_over_lines_is_between_two_notes_and_each_line_is_a_generic_row(self):
        found = rows(self.TEXT)
        self.assertEqual(
            [r.kind for r in found],
            [
                "set",
                "note",
                "generic",
                "generic",
                "generic",
                "generic",
                "note",
                "note",
                "generic",
                "generic",
                "generic",
                "note",
                "set",
            ],
        )
        self.assertEqual(found[1].text, FlowFile.BEGIN_VAR)
        self.assertEqual(found[6].text, FlowFile.END_VAR)
        self.assertEqual(found[3].text, '\t"a",')

    def test_two_literals_in_a_row_stay_two_vars(self):
        found = [r.text for r in rows(self.TEXT) if r.kind == "note"]
        self.assertEqual(found, [";@beginvar", ";@endvar"] * 2)

    def test_the_white_space_in_front_of_a_var_is_left_off_and_the_export_puts_it_back(self):
        text = "def f():\n    y = [\n        1,\n        2,\n    ]\n    return y\n"
        found = rows(text)
        self.assertEqual([r.text for r in found if r.kind == "generic"], ["y = [", "\t1,", "\t2,", "]"])
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "a.vfc")
            FlowFile.write_file(path, found, "_a.py")
            self.assertEqual(FlowToPy.export(FlowFile.read_rows(path, notes=True)), text)
        finally:
            shutil.rmtree(folder)

    def test_a_literal_on_one_line_is_a_plain_row(self):
        self.assertEqual(kinds("y = [1, 2]\n"), ["set"])

    def test_the_notes_are_lines_of_the_file_that_the_reader_skips(self):
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "a.vfc")
            FlowFile.write_file(path, rows(self.TEXT), "_a.py")
            with open(path) as handle:
                text = handle.read()
            self.assertEqual(text.count(";@beginvar"), 2)
            self.assertEqual([r.kind for r in FlowFile.read_rows(path)].count("note"), 0)
        finally:
            shutil.rmtree(folder)

    def test_the_round_trip_is_perfect_with_vars(self):
        self.assertEqual(round_trip(self.TEXT).difference, [])
        self.assertEqual(
            round_trip("class A:\n    X = (\n        1,\n        2,\n    )\n").difference, []
        )

    def test_black_is_used_at_one_hundred(self):
        self.assertEqual(RoundTrip.LINE_LENGTH, 100)
        self.assertEqual(RoundTrip.black_text("x = foo(" + "a, " * 30 + "b)\n").count("\n"), 1)


class ScanTests(unittest.TestCase):
    def test_comments_and_hash_inside_strings(self):
        scan = PyComments.Scan('x = "a # b"  # real\n# alone\n')
        self.assertEqual(scan.trailing, {1: " real"})
        self.assertEqual(scan.standalone, {2: (0, " alone")})

    def test_the_colon_that_ends_a_header_is_outside_brackets(self):
        scan = PyComments.Scan("def f(a: int = {1: 2}) -> dict[str, int]:\n    pass\n")
        self.assertEqual(scan.colon_after(1, 0), (1, 41))


class ExportTests(unittest.TestCase):
    def test_a_path_stands_level_with_its_branch(self):
        text = FlowToPy.export(
            [
                Row("branch", "if a:", None),
                Row("path", "", None),
                Row("set", "x", None),
                Row("path", "else:", None),
                Row("set", "y", None),
                Row("bend", "", None),
            ]
        )
        self.assertEqual(text, "if a:\n    x\nelse:\n    y\n")

    def test_a_case_is_one_level_in_from_match(self):
        text = FlowToPy.export(
            [
                Row("branch", "match a:", None),
                Row("path", "case 1:", None),
                Row("set", "x", None),
                Row("bend", "", None),
            ]
        )
        self.assertEqual(text, "match a:\n    case 1:\n        x\n")

    def test_rows_that_do_not_close_are_refused(self):
        with self.assertRaises(FlowFile.FlowError):
            FlowToPy.export([Row("input", "def f():", None)])
        with self.assertRaises(FlowFile.FlowError):
            FlowToPy.export([Row("bend", "", None)])

    def test_the_file_is_read_back_as_the_rows_that_were_written(self):
        original = [
            Row("set", "x = 1", None),
            Row("set", "", ""),
            Row("set", "", "  two"),
            Row("generic", "   raw  ", None),
        ]
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "a.vfc")
            FlowFile.write_file(path, original, "_a.py")
            self.assertEqual(FlowFile.read_rows(path), original)
        finally:
            shutil.rmtree(folder)


class RoundTripTests(unittest.TestCase):
    CASES = {
        "else of a loop": "for i in y:\n    if i:\n        break\nelse:\n    z = 1\n",
        "try with everything": "try:\n    a()\nexcept (A, B) as e:\n    b()\nexcept C:\n    c()\nelse:\n    d()\nfinally:\n    e()\n",
        "comment above an elif": "if a:\n    x = 1\n# note\nelif b:\n    x = 2\n",
        "comment at the end of a block": "def f():\n    x = 1\n    # last\n\n\ndef g():\n    pass\n",
        "nested definitions are still valid": "class A:\n    def f(self):\n        def g():\n            return 1\n        return g\n",
        "docstring over lines": 'def f():\n    """One\n\n    Two\n    """\n    return 1\n',
        "string with tabs and less indent": 'def f():\n    return """\n\t\tx\ny\n"""\n',
        "long call with comments": "x = foo(\n    aaaaaaaaaaaaaaaaaaaa,  # one\n    # alone\n    bbbbbbbbbbbbbbbbbbbbbbbbbb,\n)\n",
        "match with a case in brackets": "match p:\n    case (\n        aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n        | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n    ):\n        x = 1\n    case _:\n        x = 2\n",
        "async and decorators": "@a\n@b(1)\nasync def f():\n    async with x as y:\n        await z\n    async for i in q:\n        pass\n",
        "one line bodies": "if a: x = 1\nclass E(Exception): pass\n",
        "fstring over lines": "x = f'''a {b}\n  c'''\n",
        "main guard": "if __name__ == '__main__':\n    main()\n",
        "non ascii": "x = '\u00e9'  # caf\u00e9\n",
        "empty file": "",
        "only comments": "# a\n# b\n",
    }

    def test_each_case_comes_back_the_same(self):
        for name, text in self.CASES.items():
            with self.subTest(name):
                result = round_trip(text)
                self.assertEqual(result.problem, "")
                self.assertEqual(result.difference, [], "\n".join(result.difference))

    def test_a_real_difference_is_reported(self):
        self.assertTrue(RoundTrip.difference("a = 1\n", "a = 2\n"))
        self.assertEqual(RoundTrip.difference("a = 1\n\n\nb = 2\n", "a = 1\nb = 2\n"), [])
        self.assertEqual(
            RoundTrip.difference("if a:\n    pass\n    # c\n", "if a:\n    pass\n# c\n"),
            [],
        )


class SelfCheckTests(unittest.TestCase):
    """The parser parses itself, and the sample files."""

    def test_every_file_of_the_parser_round_trips(self):
        for path in sorted(glob.glob(os.path.join(APP, "*.py"))):
            with self.subTest(os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    result = round_trip(handle.read())
                self.assertEqual(result.problem, "")
                self.assertEqual(result.difference, [], "\n".join(result.difference))

    def test_every_sample_file_round_trips(self):
        for path in sorted(glob.glob(os.path.join(ROOT, "test_files", "*.py"))):
            with self.subTest(os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    result = round_trip(handle.read())
                self.assertEqual(result.difference, [], "\n".join(result.difference))


class TestFileTests(unittest.TestCase):
    def test_test1_runs_and_round_trips(self):
        import runpy

        path = os.path.join(ROOT, "test_files", "test1.py")
        out = io.StringIO()
        with redirect_stdout(out):
            runpy.run_path(path, run_name="__main__")
        self.assertIn("hello you", out.getvalue())
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(round_trip(handle.read()).difference, [])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "case.py")
        self.source = "def f(a):\n    if a:\n        return 1\n    return 2\n"
        with open(self.path, "w") as handle:
            handle.write(self.source)

    def tearDown(self):
        shutil.rmtree(self.folder)

    def run_main(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = parse_Python.main(argv)
        return code, out.getvalue()

    def test_no_file_name_prints_help_and_nothing_else_happens(self):
        code, out = self.run_main(["parse_Python.py"])
        self.assertIn("parse_Python", out)
        self.assertEqual(os.listdir(self.folder), ["case.py"])
        self.assertEqual(self.run_main(["p", "a", "b"])[0], 0)

    def test_a_run_writes_the_flow_file_and_never_changes_the_source(self):
        code, out = self.run_main(["p", self.path])
        self.assertEqual(code, 0)
        self.assertIn("PERFECT", out)
        with open(self.path) as handle:
            self.assertEqual(handle.read(), self.source)
        self.assertTrue(os.path.exists(self.path + ".vfc"))
        self.assertEqual(sorted(os.listdir(self.folder)), ["case.py", "case.py.vfc"])

    def test_the_footer_names_the_export_with_an_underscore(self):
        self.run_main(["p", self.path])
        with open(self.path + ".vfc") as handle:
            self.assertIn("; export _case.py", handle.read())

    def test_a_leftover_export_is_removed_when_the_next_run_starts(self):
        leftover = self.path + parse_Python.LEFTOVER
        with open(leftover, "w") as handle:
            handle.write("old")
        self.run_main(["p", self.path])
        self.assertFalse(os.path.exists(leftover))

    def test_a_file_that_is_not_python_stops_and_writes_no_flow_file(self):
        with open(self.path, "w") as handle:
            handle.write("def (:\n")
        code, out = self.run_main(["p", self.path])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.path + ".vfc"))

    def test_a_missing_file_is_said(self):
        code, out = self.run_main(["p", os.path.join(self.folder, "nope.py")])
        self.assertEqual(code, 1)
        self.assertIn("no such file", out)


class SameProgramTests(unittest.TestCase):
    BASE = "import os\nclass A:\n    X = 1\n    def f(self):\n        return 1\n    def g(self):\n        return 2\n"

    def test_moved_things_are_the_same_program(self):
        moved = "class A:\n    def g(self):\n        return 2\n    def f(self):\n        return 1\n    X = 1\nimport os\n"
        self.assertEqual(SameProgram.compare(self.BASE, moved), [])

    def test_spacing_and_comments_do_not_count(self):
        other = self.BASE.replace("return 1", "# a note\n\n        return 1")
        self.assertEqual(SameProgram.compare(self.BASE, other), [])

    def test_a_changed_body_is_named(self):
        self.assertEqual(SameProgram.compare(self.BASE, self.BASE.replace("return 2", "return 3")), ["different: A.g"])

    def test_a_missing_method_is_named(self):
        other = self.BASE.replace("    def g(self):\n        return 2\n", "")
        self.assertEqual(SameProgram.compare(self.BASE, other), ["missing in the second: A.g"])

    def test_a_missing_import_is_named(self):
        found = SameProgram.compare(self.BASE, self.BASE.replace("import os\n", ""))
        self.assertEqual(len(found), 1)
        self.assertIn("import", found[0].lower())

    def test_the_order_inside_a_method_counts(self):
        one = "def f():\n    a = 1\n    b = 2\n"
        two = "def f():\n    b = 2\n    a = 1\n"
        self.assertEqual(SameProgram.compare(one, two), ["different: f"])


if __name__ == "__main__":
    unittest.main()
