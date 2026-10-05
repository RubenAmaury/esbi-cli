# Coding standards

Read during review. Each rule is a judgement call that no linter or test in this repo can make; anything mechanical belongs in ruff, a test or CI instead.

## Test fakes keep the real signature

A fake that replaces a real function or method (through `monkeypatch.setattr` or an injected seam) takes the same parameters, by the same names, as the thing it replaces. A catch-all such as `def fake(*args, **kwargs)` or `lambda *a, **k: ...` lets a renamed or removed parameter pass every test and fail only on a user's machine. That is how 0.2.0 shipped a crash: one branch renamed a keyword argument of `netguard.safe_get` while another still passed the old name, and the fake accepted both.

- Write the parameters out, or build the fake with `unittest.mock.create_autospec(real, side_effect=...)`.
- A catch-all is fine only where the real callable takes one too.
- When a change renames or removes a parameter, look for every fake of that callable in `tests/`.
