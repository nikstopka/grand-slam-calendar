#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

scripts = [
    "scripts/fetch_news.py",
    "scripts/generate_ics.py",
]
for s in scripts:
    print("RUN", s)
    try:
        subprocess.run([sys.executable, s], check=False)
    except Exception as e:
        print(e)
print("done")
