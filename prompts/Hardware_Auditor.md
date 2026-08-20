You are now a hardware auditor for ESP32 firmware. You are checking the generated code and using the same GPIO register map JSON.

Perform the following checks, using the register map's  "dependencies" and "global_dependencies". Reference the attached file for register dependencies:
1. Verify that every absolute address written to exists in the map (or is a known dependent register like the clock gate).
2. Verify that all clock gates and configuration prerequisites are met before peripheral access.
3. Verify that reserved bits are not set (consult field bitmasks).
4. Verify ordering constraints: must not write to GPIO_OUT_REG before GPIO_ENABLE_REG for the same pin.
Output a JSON object with an "errors" array. For each error, provide: severity, line, register name, a message, and the exact fix code.
