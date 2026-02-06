import ast
import os
import sys
import re
from typing import List, Dict, Set, Optional, Tuple, Any
from collections import defaultdict


class CompleteStructureCommenter:
    """A more robust Python structure commenter that handles multi-block endings."""

    def __init__(self):
        self.source_lines = []
        self.result_lines = []
        self.begin_comments = {}
        self.end_comments = defaultdict(list)

    def add_comments(self, filename: str, output_filename: Optional[str] = None) -> str:
        """Add structural comments to a Python file."""
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        return self.add_comments_to_string(content, output_filename)

    def add_comments_to_string(
        self, content: str, output_filename: Optional[str] = None
    ) -> str:
        """Add structural comments to a Python string."""
        self.source_lines = content.splitlines()

        try:
            clean_content = re.sub(r"\*([a-zA-Z0-9_]+)\*", r"\1", content)
            tree = ast.parse(clean_content)
        except SyntaxError as e:
            print(f"Syntax error in input file: {e}")
            input("enter to continue")
            return content

        self._collect_comments(tree)
        self._apply_comments()

        modified_content = "\n".join(self.result_lines)

        if output_filename:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(modified_content)

        return modified_content

    def _get_indent(self, line_idx: int) -> str:
        """Get the indentation of a line."""
        if line_idx < 0 or line_idx >= len(self.source_lines):
            return ""
        line = self.source_lines[line_idx]
        return line[: len(line) - len(line.lstrip())]

    def _collect_comments_for_node(self, node, node_type, begin_comment, end_comment):
        """Collect begin and end comments for a specific node."""
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            return

        start_line = node.lineno - 1
        end_line = node.end_lineno - 1
        indent = self._get_indent(start_line)

        if start_line not in self.begin_comments:
            self.begin_comments[start_line] = []

        self.begin_comments[start_line].append(begin_comment)
        self.end_comments[end_line].append((end_comment, indent, start_line))

    def _collect_comments(self, tree):
        """First pass: collect all the begin/end comments."""
        self.begin_comments = {}
        self.end_comments = defaultdict(list)

        parent_map = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_map[child] = parent

        for node in ast.walk(tree):

            if isinstance(node, ast.FunctionDef):
                parent = parent_map.get(node)
                if parent and isinstance(parent, ast.ClassDef):
                    self._collect_comments_for_node(
                        node, "method", "#beginmethod", "#endmethod"
                    )
                else:
                    self._collect_comments_for_node(
                        node, "function", "#beginfunc", "#endfunc"
                    )

            elif isinstance(node, ast.ClassDef):
                self._collect_comments_for_node(
                    node, "class", "#beginclass", "#endclass"
                )

            elif isinstance(node, ast.If):
                start_line = node.lineno - 1
                if start_line < len(self.source_lines):
                    line = self.source_lines[start_line].strip()
                    if line.startswith("elif "):
                        self._collect_comments_for_node(
                            node, "elif", "#beginelif", "#endlif"
                        )
                    else:
                        self._collect_comments_for_node(
                            node, "if", "#beginif", "#endif"
                        )
                else:
                    self._collect_comments_for_node(node, "if", "#beginif", "#endif")

            elif isinstance(node, ast.For):
                self._collect_comments_for_node(node, "for", "#beginfor", "#endfor")

            elif isinstance(node, ast.While):
                self._collect_comments_for_node(
                    node, "while", "#beginwhile", "#endwhile"
                )

            elif isinstance(node, ast.With):
                self._collect_comments_for_node(node, "with", "#beginwith", "#endwith")

            elif isinstance(node, ast.Try):
                self._collect_comments_for_node(node, "try", "#begintry", "#endtry")

    def _should_skip_comment(self, line, comment_tag):
        if comment_tag not in line:
            return False

        str_positions = []

        for match in re.finditer(r'"[^"\\]*(?:\\.[^"\\]*)*"', line):
            str_positions.append((match.start(), match.end()))

        for match in re.finditer(r"'[^'\\]*(?:\\.[^'\\]*)*'", line):
            str_positions.append((match.start(), match.end()))

        for match in re.finditer(re.escape(comment_tag), line):
            tag_start = match.start()
            tag_end = match.end()

            inside_string = False
            for str_start, str_end in str_positions:
                if str_start <= tag_start and tag_end <= str_end:
                    inside_string = True
                    break

            if not inside_string:
                return True

        return False

    def _apply_comments(self):
        self.result_lines = []

        for i, line in enumerate(self.source_lines):

            if i in self.begin_comments:

                begin_comments = self.begin_comments[i]
                begin_comment_str = " ".join(begin_comments)

                if "#" in line and not line.strip().startswith("#"):

                    should_skip = any(
                        self._should_skip_comment(line, comment)
                        for comment in begin_comments
                    )
                    if should_skip:

                        comment_pos = line.find("#")
                        code_part = line[:comment_pos].rstrip()
                        existing_comment = line[comment_pos:]

                        modified = f"{code_part} {begin_comment_str} {existing_comment}"
                        self.result_lines.append(modified)
                    else:

                        self.result_lines.append(f"{line} {begin_comment_str}")

                else:

                    self.result_lines.append(f"{line} {begin_comment_str}")

            else:

                self.result_lines.append(line)

            if i in self.end_comments:

                sorted_end_comments = sorted(
                    self.end_comments[i], key=lambda x: x[2], reverse=True
                )

                for end_comment, indent, _ in sorted_end_comments:
                    self.result_lines.append(f"{indent}{end_comment}")


Ends = [
    "endfunc",
    "endmethod",
    "endclass",
    "endif",
    # "endlif",
    "endwith",
    "endtry",
    "endfor",
    "endwhile",
]
Begins = [
    "beginfunc",
    "beginmethod",
    "beginclass",
    "beginif",
    "beginelif",
    "begintry",
    "beginwith",
    "beginwhile",
    "beginfor",
]

begin_type = {
    "beginfunc": "input",
    "beginmethod": "input",
    "beginclass": "input",
    "beginif": "branch",
    "beginelif": "branch",
    "begintry": "branch",
    "beginwith": "branch",
    "beginwhile": "loop",
    "beginfor": "loop",
}

end_type = {
    "endfunc": "end",
    "endmethod": "end",
    "endclass": "end",
    "endif": "bend",
    # "endlif": "bend",
    "endwith": "bend",
    "endtry": "bend",
    "endfor": "lend",
    "endwhile": "lend",
}
path_type = [
    "elif",
    "else",
    "except",
    "finally",
]
event_type = [
    "import",
    "from",
]
output_type = [
    "print",
    ".write",
]
VFCSEPERATOR = ";//"


def is_path(line: str) -> bool:
    parts = line.strip().split(None, 1)
    if not parts:
        return False
    return parts[0].strip(" :") in path_type


def replace_string_literals(input_string):
    result = re.sub(r'(["\'])(.*?)(\1)', "0", input_string)
    return result


def split_on_comment(input_string):
    match = re.search(r'(?<!")#.*$', input_string)
    if match:
        s1 = input_string[: match.start()].rstrip()
        s2 = input_string[match.start() :].rstrip("\n")
    else:
        s1, s2 = input_string.rstrip("\n"), ""
    return (s1, s2)


def split_string(line: str):
    """
    Splits a line into (code, comment) while preserving exact comment text.
    - Comment-only lines: code == "", comment is full line including '#'
    - Code + comment lines: code is left side, comment is full '#...'
    """
    stripped = line.lstrip()

    if stripped.startswith("#"):
        return "", stripped

    in_single = False
    in_double = False
    saw_code = False

    for i, ch in enumerate(line):
        if not saw_code and ch not in " \t":
            saw_code = True

        if saw_code:
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double

        if ch == "#" and not in_single and not in_double:
            code = line[:i].rstrip()
            comment = line[i:].rstrip("\n")
            return code, comment

    return line.rstrip(), ""


def get_marker(comment: str) -> str:
    parts = comment.strip().split(None, 1)
    if not parts:
        return "none"
    return parts[0]


def get_VFC_type(code: str, comment: str) -> Optional[str]:
    token = code.strip().split(None, 1)[0] if len(code) > 1 else "none"

    if token in event_type:
        return "event"

    if is_path(code):
        return "path"

    c = comment.lstrip()
    if c.startswith("#"):
        c = c[1:].lstrip()
    parts = c.split(None, 1)
    if parts:
        marker = parts[0]
        if marker in Begins:
            return begin_type[marker]
        if marker in Ends:
            return end_type[marker]

    if token in ("def", "class"):
        return "input"
    if token == "if":
        return "branch"
    if token in ("for", "while"):
        return "loop"
    if token in ("try", "with"):
        return "branch"

    return "set"


STRUCT_COMMENT_LINES = {
    "#endfunc",
    "#endmethod",
    "#endclass",
    "#endif",
    "#endlif",
    "#endwith",
    "#endtry",
    "#endfor",
    "#endwhile",
}


def generate_VFC(input_string):
    strings = input_string.split("\n")
    VFC = ""
    for string in strings:

        if not string.strip():
            continue

        stripped = string.lstrip()

        # Comment-only structural marker lines: treat like old structure
        if stripped in STRUCT_COMMENT_LINES:
            comment = stripped[1:].lstrip()
            code = ""
            vtype = get_VFC_type(code, comment)
            marker = get_marker(comment)

            if marker == "endclass":
                VFC += f"bend(){VFCSEPERATOR}\n"

            out_comment = comment[len(marker) :].lstrip() if comment.startswith(marker) else comment
            VFC += f"{vtype}({code}){VFCSEPERATOR} {out_comment}\n"

            if vtype == "branch":
                VFC += f"path(){VFCSEPERATOR}\n"

            if marker == "beginclass":
                VFC += f"branch(){VFCSEPERATOR}\n"
                VFC += f"path(){VFCSEPERATOR}\n"
                VFC += f"path(){VFCSEPERATOR}\n"

            continue

        # Non-struct comment-only lines → set(#)
        if stripped.startswith("#"):
            if len(stripped.rstrip()) == 1:
                VFC += f"set(#){VFCSEPERATOR}{stripped[1:]}\n"
            else:
                VFC += f"set(){VFCSEPERATOR} {stripped[1:]}\n"
            continue

        code, comment = split_string(string)
        code = code.strip()
        vtype = get_VFC_type(code, comment)

        c = comment.lstrip()
        if c.startswith("#"):
            c_no_hash = c[1:].lstrip()
        else:
            c_no_hash = c

        marker = get_marker(c_no_hash)
        is_struct = marker in Begins or marker in Ends

        if is_struct:
            if c_no_hash.startswith(marker):
                tail = c_no_hash[len(marker) :].lstrip()
            else:
                tail = c_no_hash
            out_comment = tail
        else:
            if c.startswith("#"):
                out_comment = c[1:].lstrip()
            else:
                out_comment = comment.strip()

        if is_struct and marker == "endclass":
            VFC += f"bend(){VFCSEPERATOR}\n"

        VFC += f"{vtype}({code}){VFCSEPERATOR} {out_comment}\n"

        if vtype == "branch":
            VFC += f"path(){VFCSEPERATOR}\n"

        if is_struct and marker == "beginclass":
            VFC += f"branch(){VFCSEPERATOR}\n"
            VFC += f"path(){VFCSEPERATOR}\n"
            VFC += f"path(){VFCSEPERATOR}\n"

    return VFC


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add structure comments to Python code"
    )
    parser.add_argument("input_file", help="Input Python file")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args = parser.parse_args()
    commenter = CompleteStructureCommenter()
    modified_code = commenter.add_comments(args.input_file, args.output)
    VFC = generate_VFC(modified_code)
    with open(args.input_file + ".vfc", "w") as VFC_output:
        VFC_output.write(VFC)
       	VFC_output.write(
		";INSECTA EMBEDDED SESSION INFORMATION\n"+
		"; 255 16777215 65280 16777088 16711680 13158600 16777088 0 255 255 65535 6946660 986895\n"+
		f"; { root_filename }      #    '\n"+
		"; notepad.exe\n"+
		";INSECTA EMBEDDED ALTSESSION INFORMATION\n"+
		"; 260 260 1130 1751 0 130   137   4294966452    python.key  0"
		)
		 
    return modified_code


if __name__ == "__main__":
    t = main()
