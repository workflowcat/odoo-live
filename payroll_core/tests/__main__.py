# -*- coding: utf-8 -*-
"""Усі перевірки пакета: python3 -m payroll_core.tests"""
import sys

from . import dps, golden

code = golden.main()
print()
code |= dps.main()
sys.exit(code)
