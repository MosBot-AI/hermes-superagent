"""Hide only the selected synthetic receipt from the recovery reader."""

import os
import runpy
from pathlib import Path

from tools import bot_waiter_receipt

root = Path(os.environ["HERMES_BOT_ACCEPTANCE_ROOT"])
target = Path(os.environ["HERMES_HOME"])
delivery_id = (root / "delay-bot-receipt").read_text(encoding="ascii")
read_bound_file = bot_waiter_receipt._read_bound_file
attempts = 0


def read_with_delay(home, directory, key):
    global attempts
    if home == target and key == delivery_id and not (root / "release-bot-receipt").exists():
        attempts += 1
        proof = root / "bot-receipt-misses"
        staged = proof.with_suffix(".tmp")
        staged.write_text(str(attempts), encoding="ascii")
        staged.replace(proof)
        raise FileNotFoundError("Synthetic first-pass Bot receipt absence")
    return read_bound_file(home, directory, key)


bot_waiter_receipt._read_bound_file = read_with_delay
runpy.run_module("gateway.run", run_name="__main__")
