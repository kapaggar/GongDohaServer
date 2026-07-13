"""Arm a demo: a 10 Day course on Day 1 today, plus two extra gong events a
few minutes from now so a first look at the UI shows something firing."""
import sqlite3
from datetime import timedelta

from gong_ng import config as configmod, db, model
from gong_ng.clock import Clock

config = configmod.load()
conn = db.connect(config.db_path)
clk = Clock(config.time.timezone)
now = clk.now()

# The real centre calendar may be seeded but have no course running today;
# the demo needs an ACTIVE course so armed events actually fire.
if model.active_course(conn, now.date()) is None:
    start = (now.date() - timedelta(days=1)).isoformat()  # today = Day 1
    model.add_course(conn, 1, start, note="docker demo")
    print(f"demo: added 10 Day course starting {start} (today = Day 1)")

for minutes, repeats in ((2, 3), (5, 2)):
    t = (now + timedelta(minutes=minutes)).strftime("%H:%M")
    try:
        model.add_event(conn, 1, 1, t, repeats)
        print(f"demo: armed gong at {t} x{repeats} (IST)")
    except sqlite3.IntegrityError:
        pass
conn.close()
