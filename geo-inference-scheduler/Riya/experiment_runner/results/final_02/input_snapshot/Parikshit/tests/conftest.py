"""Test setup for Parikshit's modules: make Parikshit/ and Jyotir/ importable, plus small shared helpers."""

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PARIKSHIT_DIR = os.path.dirname(TESTS_DIR)
JYOTIR_DIR = os.path.join(os.path.dirname(PARIKSHIT_DIR), "Jyotir")

for path in (PARIKSHIT_DIR, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
if JYOTIR_DIR not in sys.path:
    sys.path.append(JYOTIR_DIR)
