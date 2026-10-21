"""Analog outputs of the HIL404 for the oscilloscope (breakout board, range +-10 V).

Set at run time (no recompile): from the SCADA panel's initialization code and from the scripts.
SCALING is in signal units per volt at the output (API example: scaling=100 -> 100 V per 1 V).
With this convention, 230 V rms PCC voltage (326 V peak) shows as about 6.5 V peak on channel 1.
"""
import os

AO = [
    # channel, signal,   scaling (units per V), what the scope shows
    (1, "Va",     50.0, "PCC voltage, phase a: 50 V/V -> 326 V peak = 6.5 V, 14 % THD still < 8 V"),
    (2, "Ia",     25.0, "grid current, phase a: 25 A/V -> 204 A peak = 8.2 V"),
    (3, "iref_a", 25.0, "reference current, phase a, same scale as channel 2: overlay them"),
    (4, "err_a",   1.0, "tracking error iref - i (alpha axis): 1 A/V, magnified 25 x against ch 2"),
]


def set_all(hil, device=0):
    """Route the signals above to the analog outputs; returns the list of channels that failed."""
    bad = []
    for ch, name, scale, _ in AO:
        if not hil.set_analog_output(ch, name, scaling=scale, offset=0.0, device=device):
            bad.append(ch)
    return bad


def init_code():
    """Lines for the SCADA panel initialization code."""
    lines = ["# analog outputs for the oscilloscope (hil_bench/analog_out.py)"]
    for ch, name, scale, what in AO:
        lines.append("hil.set_analog_output(%d, %r, scaling=%r, offset=0.0)   # %s" % (ch, name, scale, what))
    return "\n".join(lines) + "\n"


def connect_device(serial=None):
    """Register a HIL device found on the network (Ethernet). serial: the device's serial number, or the
    HIL_SERIAL environment variable, or else the first available device."""
    from typhoon.api.device_manager import DeviceManagerAPI
    dm = DeviceManagerAPI()
    if dm.is_setup_connected():                 # left connected by the previous script: reuse it
        print("setup already connected", flush=True)
        return True
    found = dm.get_available_devices()
    print("available devices:", [d.get("product_name") for d in found], flush=True)
    serial = serial or os.environ.get("HIL_SERIAL") or found[0]["serial_number"]
    dm.add_devices_to_setup([serial])
    dm.connect_setup()
    ok = dm.is_setup_connected()
    print("setup connected:", ok, flush=True)
    return ok
