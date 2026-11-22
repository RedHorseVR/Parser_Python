"""SameProgram - are two Python files the same program with only things moved around?
Both are read with Python's own parser. A class, a method and a function are each compared by name, as a tree without line numbers, so spacing, blank lines and comments do not count. What stands loose (imports, constants, other statements) is compared as a set: the order is free, how many of each is not.
Order is free at the top of the file and inside a class. Inside a function or a method the order of the statements is the program, so it is compared as it is.
The answer is a list of lines naming what is missing, extra or different; empty when the programs are the same."""

import ast
import collections
import sys


def dump(node):
    """A node as text, without line numbers."""
    return ast.dump(node)


def split_body(body):
    """({name: [nodes]} of the defs and classes, Counter of the dumps of everything else, {name: node} of the classes)."""
    named = collections.defaultdict(list)
    loose = collections.Counter()
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            named[node.name].append(node)
        else:
            loose[dump(node)] += 1
    return named, loose


def compare_named(where, left, right, found):
    """Compare the defs and classes of two bodies that have the same name."""
    for name in sorted(set(left) | set(right)):
        here = "%s%s" % (where, name)
        if name not in right:
            found.append("missing in the second: %s" % here)
        elif name not in left:
            found.append("extra in the second: %s" % here)
        elif len(left[name]) != len(right[name]):
            found.append("%s is defined %d times and %d times" % (here, len(left[name]), len(right[name])))
        else:
            for one, other in zip(left[name], right[name]):
                compare_node(here, one, other, found)


def compare_loose(where, left, right, found):
    for text in sorted((left - right).elements()):
        found.append("missing in the second, %sloose statement: %s" % (where, text[:120]))
    for text in sorted((right - left).elements()):
        found.append("extra in the second, %sloose statement: %s" % (where, text[:120]))


def class_head(node):
    """The line of a class (name, bases, decorators) as text."""
    return dump(ast.ClassDef(node.name, node.bases, node.keywords, [], node.decorator_list))


def compare_node(here, one, other, found):
    """A class is compared piece by piece (order free); a function as a whole."""
    if isinstance(one, ast.ClassDef) and isinstance(other, ast.ClassDef):
        if class_head(one) != class_head(other):
            found.append("%s: the line of the class (bases, decorators) differs" % here)
        left, loose_left = split_body(one.body)
        right, loose_right = split_body(other.body)
        compare_named(here + ".", left, right, found)
        compare_loose(here + ".", loose_left, loose_right, found)
    elif dump(one) != dump(other):
        found.append("different: %s" % here)


def compare(first, second):
    """The differences between two Python texts, as a list of lines (empty: the same program)."""
    found = []
    left, loose_left = split_body(ast.parse(first).body)
    right, loose_right = split_body(ast.parse(second).body)
    compare_named("", left, right, found)
    compare_loose("", loose_left, loose_right, found)
    return found


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as one, open(sys.argv[2], encoding="utf-8") as other:
        problems = compare(one.read(), other.read())
    print("\n".join(problems) if problems else "the same program")
    sys.exit(1 if problems else 0)
