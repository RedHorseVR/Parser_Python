"""test1: a legal Python file that runs by itself and holds every structure the parser handles.

Run it:  python test_files/test1.py
It prints a few lines, so the output can be compared before and after a round trip.
"""

import asyncio
import os
from collections import defaultdict

# A literal over several lines: the parser marks it as a var.
COLORS = [
    "red",
    "green",  # a comment inside the list
    "blue",
]

LIMITS = {
    "low": 1,
    "high": 10,
}

NAMES = ("ann", "bob")
TOTAL: int = 0
note = """A string over
    several lines, with  spaces
kept as they are."""


class Trace:
    """A decorator as a class: calls the function and says so."""

    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        print("calling", self.function.__name__)
        return self.function(*args)


@Trace
def greet(name):
    return "hello " + name


class Counter:
    """A class with methods and a property."""

    kind = "counter"  # a comment after code

    def __init__(self, start=0):
        self.value = start
        self.seen = defaultdict(list)

    @property
    def double(self):
        return self.value * 2

    def add(self, amount):
        # a comment on its own line
        self.value += amount
        return self.value

    def describe(self, width, height, depth, color="red", shape="box", label="a long label", more=None):
        """A signature that Black cuts over several lines."""
        return f"{color} {shape} {width}x{height}x{depth} {label} {more}"


def classify(number):
    if number < 0:
        return "negative"
    # dedented comment above an elif
    elif number == 0:
        return "zero"
    elif number < 10:
        return "small"
    else:
        return "large"


def loops(limit):
    found = []
    for i in range(limit):
        if i % 2:
            continue
        found.append(i)
    else:
        found.append("for done")
    count = 0
    while count < 3:
        count += 1
    else:
        found.append("while done")
    return found


def attempt(value):
    try:
        result = 10 // value
    except ZeroDivisionError as problem:
        result = "zero: %s" % problem
    except (TypeError, ValueError):
        result = "bad"
    else:
        result = result + 1
    finally:
        print("attempt", value)
    return result


def reader(path):
    with open(path, "r", encoding="utf-8") as first, open(path, "r", encoding="utf-8") as second:
        return len(first.read()) == len(second.read())


def shape(point):
    match point:
        case (0, 0):
            return "origin"
        case (x, 0):
            return "on x %d" % x
        case _:
            return "elsewhere"


async def pause(seconds):
    await asyncio.sleep(seconds)
    return seconds


def main():
    counter = Counter(1)
    print(greet("you"))
    print(counter.add(2), counter.double, Counter.kind)
    print(counter.describe(1, 2, 3))
    print([classify(n) for n in (-1, 0, 5, 50)])
    print(loops(5))
    print(attempt(2), attempt(0), attempt("x"))
    print(reader(__file__))
    print(shape((0, 0)), shape((3, 0)), shape((1, 1)))
    print(asyncio.run(pause(0)))
    print(COLORS, LIMITS, NAMES, TOTAL)
    print(note)
    print(os.path.basename(__file__))
    square = lambda x: x * x
    print(square(4))


if __name__ == "__main__":
    main()
