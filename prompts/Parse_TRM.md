```
Please parse the attached esp32 microcontroller technical reference manual. 
Extract:
- Every register name, absolute address, and bitfield description
- Any dependencies mentioned (clock gates, power domains, other registers that must be configured first)
- Reset values
Output as JSON matching this schema: 
{
  "peripheral": "GPIO",
  "base_address": "0x60004000",
  "source_page": "Section 5.2 GPIO Registers, pp. 123-124",
  "registers": [
    {
      "name": "GPIO_ENABLE_REG",
      "absolute_address": "0x60004000",
      "description": "GPIO output enable register. Set bit n to 1 to make GPIO pad n an output; 0 for input (default).",
      "width": 32,
      "access": "RW",
      "reset_value": "0x00000000",
      "fields": [
        {
          "name": "GPIO_ENABLE",
          "bits": "0-31",
          "description": "Bit n: 1 = GPIOn is output, 0 = input. Bits for non-existent pads are reserved and must be written as 0."
        }
      ],
      "dependencies": [
        "Clock gate: bit 6 of SYSTEM_PERIP_CLK_EN0_REG (0x60008008) must be set to 1 before accessing this register.",
        "Pad configuration: For any pad being used, its IO_MUX register must have the MCU_SEL bit cleared (GPIO function selected). Example: for GPIO5, configure IO_MUX_GPIO5_REG (0x60009014)."
      ]
    },
    {
      "name": "GPIO_OUT_REG",
      "absolute_address": "0x60004004",
      "description": "GPIO output data register. Writes set the output level of pads configured as outputs; reads return the last written value.",
      "width": 32,
      "access": "RW",
      "reset_value": "0x00000000",
      "fields": [
        {
          "name": "GPIO_OUT_DATA",
          "bits": "0-31",
          "description": "Bit n: output level for GPIOn. Has no effect if GPIOn is not enabled as output."
        }
      ],
      "dependencies": [
        "GPIO_ENABLE_REG must be configured first to set the corresponding bits as outputs."
      ]
    },
    {
      "name": "GPIO_IN_REG",
      "absolute_address": "0x60004008",
      "description": "GPIO input status register. Read-only; reflects the current input level on each pad, regardless of output enable setting.",
      "width": 32,
      "access": "RO",
      "reset_value": "0x00000000",
      "fields": [
        {
          "name": "GPIO_IN_DATA",
          "bits": "0-31",
          "description": "Bit n: current input level on GPIO pad n."
        }
      ],
      "dependencies": []
    }
  ],
  "global_dependencies": [
    "GPIO peripheral clock must be enabled before any register access: set bit 6 of SYSTEM_PERIP_CLK_EN0_REG (0x60008008).",
    "Each GPIO pad used must have its IO_MUX register programmed to select the GPIO function (clear MCU_SEL bit). Consult the IO_MUX chapter for pad-specific register addresses."
  ]
}

```
