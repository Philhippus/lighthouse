# Lighthouse

Lighthouse is an experimental pipeline that generates verified bare-metal firmware for the ESP32 from a natural language prompt. It wraps an LLM in a multi-agent loop:

- **Generator** — produces C code from the user request and a machine-readable register map.
- **Hardware Auditor** — checks the generated code against the register map and returns structured errors.
- **Deterministic Safety Net** — catches common failure modes with hardcoded rules.

The project was built as **Project Babbage** to demonstrate that low-level expertise is the missing layer that makes AI-generated code safe for physical hardware.

## Files

- `babbage.py` — main orchestration script
- `README.md` — this file
- Generated output includes `.c` firmware and a Wokwi-compatible `diagram.json`

## Requirements

- Python 3.9+
- `openai` Python package

```bash
pip install openai
