"""Shared scheduling bounds; courses and DDL keep their exact minute boundaries."""
from datetime import timedelta
from .validator import expand_time_rules

from .grid import GRID_MINUTES, WINDOW_DAYS

def expand_window_rules(week, rules):
    return (*expand_time_rules(week, rules), *expand_time_rules(week + timedelta(days=7), rules))
