"""Test setup for Sur's modules: make Sur/ and Jyotir/ importable (same idea as Jyotir's tests)."""

import os
import sys

SUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JYOTIR_DIR = os.path.join(os.path.dirname(SUR_DIR), "Jyotir")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

for path in (SUR_DIR, JYOTIR_DIR, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
