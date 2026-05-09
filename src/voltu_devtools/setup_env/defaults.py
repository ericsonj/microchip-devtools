"""Common environment variable defaults shared across all Voltu firmware projects.

Projects add project-specific vars in their own pymake/env.py as PROJECT_DEFAULTS.
Resolution priority (highest to lowest):
    1. Shell environment variables
    2. .env file
    3. PROJECT_DEFAULTS (project pymake/env.py)
    4. COMMON_DEFAULTS (this file)
"""

COMMON_DEFAULTS: dict[str, str] = {
    "XC32_PATH": "/opt/microchip/xc32/v4.60/bin/",
    "DFP_PATH":  "~/.mchp_packs/Microchip/PIC32MK-MC_DFP/1.12.263",
    "IPE_CMD":   "/opt/microchip/mplabx/v6.25/mplab_platform/mplab_ipe/ipecmd.sh",
}
