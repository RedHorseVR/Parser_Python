# 🌀 Self-Grokking Python Parser

> Built in on evening with the help of Claude and VFCode - A parser that parses itself to understand and visualize its own structure — using AST logic, structural comments, and flow graph generation.

---

## 📌 Overview

Python’s indentation is elegant—but not always easy to work with. Especially when debugging or refactoring deeply nested code, it’s hard to know **where you are** in the structure.

This project introduces a solution:

- A **Python parser** that walks the AST
- Inserts `#begin...` / `#end...` comments (`#endfunc`, `#endif`, `#endclass`, etc.)
- Makes block structure explicitly visible — even where Python normally relies on indentation only

---

## 🔁 The Self-Parsing Experiment

To test it, I pointed the parser at **itself**.

After some tuning, the AI-assisted logic began successfully:
- Identifying class/function/loop structures
- Annotating opening and closing logic
- Working recursively, even when parsing its own code

Once annotated, the file was fed into **VFCode**, a visual flow graph renderer. This revealed the parser’s full logical structure in a form that was explorable and editable.

I was then able to:
- Export the visualized version back to Python
- And successfully run the parser... on itself

---

## 📊 Example

### Before:
```python
class MyParser:
    def parse(self):
        if token:
            do_something()
```
### After:
```
class MyParser: #beginclass
    def parse(self): #beginfunc
        if token: #beginif
            do_something()
        #endif
    #endfunc
#endclass
```
### A veiw within VFCode
![pyCommentParserVFC](https://github.com/user-attachments/assets/94fd3028-484b-4a98-8b71-0e0a9ebca18d)
