# Contributing to hookyard

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

- Replay host checks must resolve DNS and use `ipaddress`, not string prefixes.
- Metadata IPs stay blocked even with `--allow-remote-replay`.
- UI list rows must use `textContent`, not `innerHTML` for method/path.
- Catch URLs stay unauthenticated; UI/API may require `--token`.
- Keep the Apache-2.0 license notice intact.
