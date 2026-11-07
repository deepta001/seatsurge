# Primer 1: Type hints, modules and imports, virtual environments

**Analogy:** a project is a kitchen. **Modules** are labelled drawers (one
drawer per kind of tool). **Imports** are "go fetch the whisk from the baking
drawer". **Type hints** are labels on the containers ("sugar, not salt"). A
**virtual environment** is a private pantry for this kitchen, so another
kitchen's ingredients never get mixed in.

## Type hints

```python
def sell(quantity: int) -> bool: ...
```

`quantity: int` says "this should be a whole number", and `-> bool` says
"this returns True or False". For collections: `dict[str, int]` is a dict with
text keys and whole-number values.

Python **does not enforce** hints when it runs. They're for humans, editors
(VS Code underlines mistakes) and checkers like **mypy**, which reads the code
and reports mismatches before you run it. We'll add mypy in S0.9.

## Classes

A class is a template for objects that hold data and the actions on that data.
`__init__` runs when you create an object, and `self` is "this particular
object".

## Modules and imports

Every `.py` file is a **module**. `from seats import Tier` means "load
`seats.py` and give me its `Tier`". The code that runs only when the file is
started directly (not imported) goes under:

```python
if __name__ == "__main__":
    main()
```

## Virtual environments

A **virtual environment** (`.venv` folder) is a private copy of Python with
its own installed libraries. Project A can use library version 1 while
project B uses version 2. In this project, `uv` creates and manages it for us
(S0.4).

## Try it

- `learning/examples/s0_3/seats.py`: a `Tier` class and a `summary` function
- `learning/examples/s0_3/main.py`: imports and uses them

```
python learning/examples/s0_3/main.py
```
