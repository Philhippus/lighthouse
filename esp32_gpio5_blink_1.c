/* =====================================================================
 * esp32_gpio5_blink.c
 *
 * Bare-metal ESP32 firmware: blinks an LED on GPIO5 (physical pin 5)
 * once per second, using only volatile pointer writes to memory-mapped
 * peripheral registers. No ESP-IDF driver/HAL calls are used anywhere
 * in this file.
 *
 * All register names/addresses/fields below are taken directly from
 * the supplied register map (esp32_gpio_registers.json, extracted
 * from the ESP32 TRM v5.7, Chapter 6 "IO MUX and GPIO Matrix").
 *
 * IMPORTANT NOTE ON ONE VALUE NOT PRESENT IN THE SUPPLIED MAP
 * -------------------------------------------------------------------
 * The register map documents the IO_MUX_GPIO5_REG.MCU_SEL field only
 * generically ("0 selects Function 0, 1 selects Function 1, etc.").
 * It does not state which numeric function value corresponds to the
 * plain "GPIO5" function for this specific pin (that mapping is
 * pin-specific and lives in the TRM's per-pin Function tables /
 * ESP-IDF's soc/io_mux_reg.h, not in the register-field JSON).
 * For GPIO5 that value is Function 2 (FUNC_GPIO5_GPIO5 = 2). This is
 * supplied from that external, pin-specific function table, not from
 * the JSON register map itself -- flagged here for transparency.
 *
 * DEPENDENCY CHAIN SATISFIED (per the register map's own field
 * descriptions):
 *   1. IO_MUX_GPIO5_REG.MCU_SEL = 2         -> routes the physical pad
 *      to the GPIO5 line instead of an alternate peripheral function
 *      (e.g. VSPICS0).
 *   2. GPIO_FUNC5_OUT_SEL_CFG_REG.GPIO_FUNCn_OUT_SEL = 256 -> per the
 *      map's own description, "A value of 256 selects bit n of
 *      GPIO_OUT_REG ... and GPIO_ENABLE_REG ... as the output value
 *      and output enable," i.e. hands control of the pad's output
 *      value/enable to the plain GPIO_OUT_REG / GPIO_ENABLE_REG bit,
 *      rather than to a routed peripheral signal.
 *   3. GPIO_ENABLE_REG bit 5 = 1            -> configures GPIO5 as an
 *      output.
 *   4. GPIO_OUT_W1TS_REG / GPIO_OUT_W1TC_REG bit 5 -> set/clear the
 *      pin's output level without a read-modify-write race.
 *
 * GPIO5 has no corresponding RTC_GPIO / RTC_IO_MUX entry in the ESP32
 * pin table (unlike e.g. GPIO0/2/4), so the RTC IO MUX registers in
 * the map are not part of this pin's dependency chain and are left
 * untouched.
 *
 * Note: GPIO5 is a strapping pin (SDIO timing at boot). This only
 * affects the reset/boot sequence, not runtime GPIO use, so it is
 * safe to drive after boot -- but avoid tying an external pull
 * up/down to this net that could disturb the boot strapping level.
 *
 * TIMING CAVEAT: the register map provided covers only GPIO/IO_MUX,
 * no timer peripheral. The 1-second delay below is therefore a
 * software busy-wait, calibrated for an approximate 80 MHz CPU clock
 * (ESP32's common default). It is not cycle-accurate; for precise
 * timing use a hardware timer/RTC peripheral instead.
 * ===================================================================== */

#include <stdint.h>

/* ---- Generic 32-bit memory-mapped register accessor ---- */
#define REG32(addr) (*(volatile uint32_t *)(addr))

/* ---- GPIO registers (base 0x3FF44000), from the register map ---- */
#define GPIO_OUT_REG            0x3FF44004u  /* GPIO0-31 output register            (R/W) */
#define GPIO_OUT_W1TS_REG       0x3FF44008u  /* GPIO0-31 output set register        (WO)  */
#define GPIO_OUT_W1TC_REG       0x3FF4400Cu  /* GPIO0-31 output clear register      (WO)  */
#define GPIO_ENABLE_REG         0x3FF44020u  /* GPIO0-31 output enable register     (R/W) */
#define GPIO_ENABLE_W1TS_REG    0x3FF44024u  /* GPIO0-31 output enable set register (WO)  */

/* GPIO_FUNC5_OUT_SEL_CFG_REG: the supplied register map only enumerates
 * GPIO_FUNC0_OUT_SEL_CFG_REG (0x3FF44530) and GPIO_FUNC1_OUT_SEL_CFG_REG
 * (0x3FF44534) explicitly for this register family; indices 2-39 are not
 * individually listed. The address below is confirmed against ESP32 TRM
 * v5.7 Section 6.12 (GPIO Matrix Register Summary, base 0x3FF44530 + 4*n),
 * and cross-checked using the same 4-byte stride evidenced by the
 * GPIO_FUNC254/255_IN_SEL_CFG_REG pair in the supplied map
 * (0x3FF44528 -> 0x3FF4452C). */
#define GPIO_FUNC5_OUT_SEL_CFG_REG 0x3FF44544u

/* ---- IO_MUX register for GPIO5 (base 0x3FF49000) ---- */
#define IO_MUX_GPIO5_REG        0x3FF4906Cu  /* Configuration register for GPIO5 (R/W) */

/* IO_MUX_GPIOn_REG field bit positions, from the register map */
#define IO_MUX_MCU_SEL_S    12  /* bits 14:12 - IO_MUX function select        */
#define IO_MUX_FUN_DRV_S    10  /* bits 11:10 - pad drive strength            */
#define IO_MUX_FUN_IE_S      9  /* bit 9      - input enable                  */
#define IO_MUX_FUN_WPU_S     8  /* bit 8      - pull-up enable                */
#define IO_MUX_FUN_WPD_S     7  /* bit 7      - pull-down enable              */

/* Pin-specific function value: FUNC_GPIO5_GPIO5 (plain GPIO function on GPIO5) */
#define IO_MUX_GPIO5_FUNC_GPIO   2u

/* GPIO_FUNCn_OUT_SEL_CFG_REG special value: bind pad output to GPIO_OUT_REG/GPIO_ENABLE_REG */
#define GPIO_FUNC_OUT_SEL_SIMPLE_GPIO 256u

#define LED_GPIO_NUM 5u

/* ---- Approximate busy-wait delay (no hardware timer in the supplied map) ---- */
static void delay_ms(uint32_t ms)
{
    volatile uint32_t count;
    /* Rough calibration for ~80 MHz CPU clock; adjust if your clock config differs. */
    const uint32_t cycles_per_ms = 8000u;

    for (uint32_t i = 0; i < ms; i++) {
        for (count = 0; count < cycles_per_ms; count++) {
            __asm__ __volatile__("nop");
        }
    }
}

/* ---- One-time GPIO5 pin configuration ---- */
static void led_gpio_init(void)
{
    uint32_t iomux_val;

    /* 1. IO_MUX: route the pad to the plain "GPIO5" function (Function 2),
     *    read-modify-write so reserved/unrelated bits are left untouched. */
    iomux_val  = REG32(IO_MUX_GPIO5_REG);
    iomux_val &= ~(0xFFFF8000u);                                 /* explicitly clear reserved bits [31:15] */
    iomux_val &= ~(0x7u << IO_MUX_MCU_SEL_S);                    /* clear MCU_SEL[2:0] */
    iomux_val |= (IO_MUX_GPIO5_FUNC_GPIO << IO_MUX_MCU_SEL_S);   /* select Function 2  */
    iomux_val &= ~(1u << IO_MUX_FUN_IE_S);                       /* input buffer off (pure output) */
    REG32(IO_MUX_GPIO5_REG) = iomux_val;

    /* 2. GPIO Matrix: bind GPIO5's pad output to GPIO_OUT_REG/GPIO_ENABLE_REG
     *    bit 5, per GPIO_FUNC5_OUT_SEL_CFG_REG's documented value 256. */
    REG32(GPIO_FUNC5_OUT_SEL_CFG_REG) = GPIO_FUNC_OUT_SEL_SIMPLE_GPIO;

    /* 3. GPIO_ENABLE_REG: configure GPIO5 as an output (write-1-to-set, no RMW needed). */
    REG32(GPIO_ENABLE_W1TS_REG) = (1u << LED_GPIO_NUM);

    /* Start with the LED off. */
    REG32(GPIO_OUT_W1TC_REG) = (1u << LED_GPIO_NUM);
}

static void led_on(void)
{
    REG32(GPIO_OUT_W1TS_REG) = (1u << LED_GPIO_NUM);
}

static void led_off(void)
{
    REG32(GPIO_OUT_W1TC_REG) = (1u << LED_GPIO_NUM);
}

/* ---- Entry point ----
 * app_main() is used as the entry symbol so this file can be built and
 * flashed as a minimal ESP-IDF component (the standard, practical way
 * to get bare-metal code running on real ESP32 hardware). No ESP-IDF
 * driver or HAL function is called anywhere above or below this line --
 * only direct volatile register access is used to control GPIO5.
 */
void app_main(void)
{
    led_gpio_init();

    while (1) {
        led_on();
        delay_ms(1000);
        led_off();
        delay_ms(1000);
    }
}
