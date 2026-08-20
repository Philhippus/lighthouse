#!/usr/bin/env python3
"""
Project Babbage: Automated AI-to-Silicon Firmware Verification Pipeline
Accepts a natural language prompt and produces verified bare-metal firmware.
"""

import os
import json
import argparse
from typing import Optional
from openai import OpenAI

# ============================================================================
# CONFIGURATION
# ============================================================================

# Change these to match your LLM provider
CLIENT = OpenAI(
    base_url="https://api.deepseek.com/v1",  # or http://localhost:11434/v1 for Ollama
    api_key=os.environ.get("DEEPSEEK_API_KEY", "ollama")  # Ollama doesn't need a real key
)
MODEL = "deepseek-chat"  # or "llama3.1:70b" for Ollama

MAX_ITERATIONS = 5  # Maximum audit-regenerate cycles

# ============================================================================
# REGISTER MAP (Ground Truth)
# ============================================================================

# This would normally come from your RAG pipeline ingesting the TRM.
# For the demo, we hardcode the Wokwi-compatible ESP32 map.
ESP32_GPIO_REGISTER_MAP = {
    "peripheral": "GPIO",
    "chip": "ESP32 (Xtensa LX6)",
    "base_address": "0x3FF44000",
    "registers": [
        {
            "name": "GPIO_ENABLE_W1TS_REG",
            "absolute_address": "0x3FF44008",
            "description": "Write 1 to bit n to set GPIO n as output.",
            "width": 32,
            "access": "WO",
            "fields": [
                {"name": "ENABLE_W1TS", "bits": "0-31",
                 "description": "Set bit n to 1 to enable output on GPIO n"}
            ]
        },
        {
            "name": "GPIO_OUT_W1TS_REG",
            "absolute_address": "0x3FF4400C",
            "description": "Write 1 to bit n to set GPIO n output high.",
            "width": 32,
            "access": "WO",
            "fields": [
                {"name": "OUT_W1TS", "bits": "0-31",
                 "description": "Set bit n to 1 to drive GPIO n high"}
            ]
        },
        {
            "name": "GPIO_OUT_W1TC_REG",
            "absolute_address": "0x3FF44010",
            "description": "Write 1 to bit n to set GPIO n output low.",
            "width": 32,
            "access": "WO",
            "fields": [
                {"name": "OUT_W1TC", "bits": "0-31",
                 "description": "Set bit n to 1 to drive GPIO n low"}
            ]
        }
    ],
    "io_mux_registers": [
        {
            "pad": "GPIO5",
            "absolute_address": "0x3FF49014",
            "name": "IO_MUX_GPIO5_REG",
            "function_field_bits": "0-2",
            "gpio_function_code": 2,
            "description": "Set FUNC_SEL bits [0:2] to 2 for GPIO function on pad GPIO5"
        }
    ],
    "global_dependencies": [
        "ESP32 does not require an explicit clock gate enable for GPIO.",
        "Each GPIO pad used must have its IO_MUX register FUNC_SEL field set to the GPIO function code.",
        "Use GPIO_ENABLE_W1TS_REG to set output enable; writing 0 has no effect.",
        "Use GPIO_OUT_W1TS_REG to set output high; use GPIO_OUT_W1TC_REG to set output low.",
        "Always use volatile pointers. Delay loops must use volatile counters to prevent optimization."
    ]
}

REGISTER_MAP_JSON = json.dumps(ESP32_GPIO_REGISTER_MAP, indent=2)

# ============================================================================
# LLM CALL HELPER
# ============================================================================

def llm(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Send a prompt to the LLM and return the response text."""
    kwargs = dict(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,  # Low temperature for deterministic, correct output
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = CLIENT.chat.completions.create(**kwargs)
    return response.choices[0].message.content

# ============================================================================
# AGENT PROMPTS
# ============================================================================

GENERATOR_SYSTEM_PROMPT = f"""You are an expert bare-metal firmware engineer for the ESP32 (Xtensa LX6) microcontroller.
Below is the machine-readable register map for the GPIO peripheral. Use ONLY these absolute addresses.

=== ESP32 GPIO REGISTER MAP ===
{REGISTER_MAP_JSON}

=== RULES ===
1. Use ONLY absolute addresses from the map. No SDK, no HAL, no Arduino functions.
2. Use volatile uint32_t pointers for all MMIO access.
3. Satisfy ALL dependencies listed in the register map and global_dependencies.
4. For delay loops, use `for(volatile int i=0; i<1000000; i++);` to prevent compiler optimization.
5. Generate ONLY the C code, no explanation, no markdown fences unless wrapping the entire code block.
6. The function must be named `app_main` (not `main`) because the ESP32 bare-metal runtime expects this.
7. Write the complete, compilable C file including any necessary #include for stdint.
"""

AUDITOR_SYSTEM_PROMPT = f"""You are a hardware auditor for ESP32 (Xtensa LX6) bare-metal firmware.
You will receive generated C code and the GPIO register map.

=== ESP32 GPIO REGISTER MAP ===
{REGISTER_MAP_JSON}

=== AUDIT CHECKLIST ===
1. Does every written absolute address exist in the register map?
2. Are all global_dependencies satisfied (IO_MUX configured, etc.)?
3. Are there any writes to GPIO_OUT before GPIO_ENABLE for the same pin?
4. Are there any reserved bits being set?
5. Are all MMIO accesses through volatile pointers?
6. Is the function named `app_main`?

Return a JSON object with an "errors" array. Each error must have:
  - severity: "FATAL" or "WARNING"
  - line: approximate line number
  - type: error category
  - message: human-readable description
  - fix_code: exact C code to insert/change to fix the error

If no errors, return {{"errors": []}}.
"""

# ============================================================================
# PIPELINE STEPS
# ============================================================================

def generate_firmware(user_request: str, previous_errors: Optional[list] = None) -> str:
    """Agent 1: Generate firmware, optionally with prior audit feedback."""
    user_prompt = f"Generate bare-metal C code to: {user_request}"

    if previous_errors:
        error_feedback = json.dumps(previous_errors, indent=2)
        user_prompt += f"\n\n=== PREVIOUS AUDIT ERRORS TO FIX ===\n{error_feedback}\nRegenerate the code addressing ALL errors."

    return llm(GENERATOR_SYSTEM_PROMPT, user_prompt)


def audit_firmware(code: str) -> list:
    """Agent 2: Audit the generated firmware against the register map."""
    user_prompt = f"Audit this ESP32 firmware for hardware-level errors:\n\n```c\n{code}\n```"
    response = llm(AUDITOR_SYSTEM_PROMPT, user_prompt, json_mode=True)
    result = json.loads(response)
    return result.get("errors", [])


def extract_code_from_response(response: str) -> str:
    """Extract C code from an LLM response that may contain markdown fences."""
    if "```c" in response:
        start = response.find("```c") + 4
        end = response.find("```", start)
        if end != -1:
            return response[start:end].strip()
    if "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        if end != -1:
            return response[start:end].strip()
    return response.strip()


def deterministic_safety_check(code: str) -> list:
    """
    Minimal deterministic checker for failures LLMs consistently miss.
    Add rules here as you discover them during testing.
    """
    errors = []

    # Rule 1: Must use app_main, not main
    if "main(void)" in code and "app_main" not in code:
        errors.append({
            "severity": "FATAL",
            "line": 0,
            "type": "WRONG_ENTRY_POINT",
            "message": "ESP32 bare-metal expects `app_main`, not `main`. The program will not start.",
            "fix_code": "Replace `void main(void)` with `void app_main(void)`"
        })

    # Rule 2: Must have at least one volatile pointer
    if "volatile" not in code:
        errors.append({
            "severity": "FATAL",
            "line": 0,
            "type": "NO_VOLATILE",
            "message": "All MMIO accesses must use volatile pointers to prevent optimization.",
            "fix_code": "Add `volatile` qualifier to all MMIO pointer declarations."
        })

    # Rule 3: Must reference an IO_MUX register if using a specific GPIO pad
    if "GPIO5" in code or "pin 5" in code.lower():
        if "0x3FF49014" not in code:  # IO_MUX_GPIO5_REG
            errors.append({
                "severity": "FATAL",
                "line": 0,
                "type": "IO_MUX_NOT_CONFIGURED",
                "message": "GPIO5 used but IO_MUX_GPIO5_REG (0x3FF49014) not configured.",
                "fix_code": "IO_MUX_GPIO5_REG = (IO_MUX_GPIO5_REG & ~0x7) | 0x2; // GPIO function"
            })

    return errors


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def run_pipeline(user_request: str) -> dict:
    """Execute the full generate-audit-fix loop until verification passes."""
    print(f"\n{'='*70}")
    print(f"PROJECT BABBAGE PIPELINE")
    print(f"Request: {user_request}")
    print(f"{'='*70}\n")

    all_errors = []
    code = None

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"--- Iteration {iteration}/{MAX_ITERATIONS} ---")

        # Step 1: Generate firmware
        print("  [Generate] Calling firmware generator...")
        response = generate_firmware(user_request, all_errors if all_errors else None)
        code = extract_code_from_response(response)
        print(f"  [Generate] Received {len(code)} characters of C code")

        # Step 2: Deterministic safety net (runs first, catches the stupid stuff)
        print("  [Deterministic Check] Running safety checks...")
        det_errors = deterministic_safety_check(code)
        if det_errors:
            print(f"  [Deterministic Check] Found {len(det_errors)} error(s)")
            for e in det_errors:
                print(f"    - {e['type']}: {e['message']}")
            all_errors = det_errors
            if iteration < MAX_ITERATIONS:
                print("  -> Feeding back to generator...\n")
                continue
        else:
            print("  [Deterministic Check] Passed")

        # Step 3: AI Auditor
        print("  [AI Audit] Calling hardware auditor...")
        audit_errors = audit_firmware(code)
        if audit_errors:
            print(f"  [AI Audit] Found {len(audit_errors)} error(s)")
            for e in audit_errors:
                print(f"    - [{e['severity']}] {e['type']}: {e['message']}")
            all_errors = audit_errors
            if iteration < MAX_ITERATIONS:
                print("  -> Feeding back to generator...\n")
                continue
        else:
            print("  [AI Audit] No errors found")
            all_errors = []

        # If we get here with no errors, we're done
        if not all_errors:
            print(f"\n{'='*70}")
            print("VERIFICATION PASSED")
            print(f"{'='*70}")
            break
    else:
        print(f"\n{'='*70}")
        print(f"MAX ITERATIONS REACHED - Verification may be incomplete")
        print(f"Remaining errors: {len(all_errors)}")
        print(f"{'='*70}")

    return {
        "request": user_request,
        "verified": len(all_errors) == 0,
        "iterations": iteration,
        "remaining_errors": all_errors,
        "code": code
    }


# ============================================================================
# OUTPUT FORMATTERS
# ============================================================================

def output_wokwi_json(result: dict, filename: str = "babbage_output.json"):
    """Write a wokwi-compatible project file alongside the verified code."""
    # Extract the C code
    code = result["code"]

    # Write the C file
    c_filename = filename.replace(".json", ".c")
    with open(c_filename, "w") as f:
        f.write(code)
    print(f"  Wrote C code to: {c_filename}")

    # Write a wokwi diagram.json
    diagram = {
        "version": 1,
        "author": "Project Babbage",
        "editor": "wokwi",
        "parts": [
            {"type": "board-esp32-devkit-c-v4", "id": "esp", "top": 0, "left": 0, "attrs": {}}
        ],
        "connections": [
            ["esp:5", "led:anode", "green", ""],
            ["led:cathode", "res:1", "green", ""],
            ["res:2", "esp:gnd", "green", ""]
        ]
    }
    with open(filename, "w") as f:
        json.dump(diagram, f, indent=2)
    print(f"  Wrote wokwi diagram to: {filename}")

    # Print summary
    print(f"\n  To test in Wokwi:")
    print(f"  1. Go to https://wokwi.com")
    print(f"  2. Create a new ESP32 project")
    print(f"  3. Replace main.c with the contents of {c_filename}")
    print(f"  4. Replace diagram.json with the contents of {filename}")
    print(f"  5. Add an LED + 220Ω resistor connected to GPIO5 and GND")
    print(f"  6. Set framework to 'baremetal' in sketch.ini")
    print(f"  7. Press Start Simulation")


def print_verified_code(result: dict):
    """Print the verified code to stdout with optional error summary."""
    print("\n" + "="*70)
    print("VERIFIED FIRMWARE")
    print("="*70)
    print(result["code"])
    print("="*70)

    if not result["verified"]:
        print("\n⚠️  WARNING: Verification incomplete. Remaining errors:")
        for e in result["remaining_errors"]:
            print(f"  - [{e['severity']}] {e['type']}: {e['message']}")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Project Babbage: AI-to-Silicon Verified Firmware Generator"
    )
    parser.add_argument(
        "request",
        nargs="?",
        default="blink the LED on GPIO pin 5 once per second",
        help="Natural language firmware request (default: 'blink the LED on GPIO pin 5 once per second')"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output filename prefix for wokwi-compatible files (e.g., 'my_blink' produces my_blink.c and my_blink.json)"
    )
    parser.add_argument(
        "--max-iterations", "-n",
        type=int,
        default=MAX_ITERATIONS,
        help=f"Maximum generate-audit cycles (default: {MAX_ITERATIONS})"
    )
    parser.add_argument(
        "--print-only", "-p",
        action="store_true",
        help="Print verified code to stdout only, no file output"
    )

    args = parser.parse_args()

    # Override global if provided
    global MAX_ITERATIONS
    MAX_ITERATIONS = args.max_iterations

    # Run the pipeline
    result = run_pipeline(args.request)

    # Output
    if args.print_only:
        print_verified_code(result)
    else:
        prefix = args.output or "babbage_output"
        output_wokwi_json(result, prefix + ".json")
        print_verified_code(result)


if __name__ == "__main__":
    main()