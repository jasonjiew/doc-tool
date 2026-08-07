# -*- coding: utf-8 -*-

import os
import subprocess
import sys


HERE = os.path.dirname(os.path.abspath(__file__))


def run(name):
    print("\n== {0} ==".format(name), flush=True)
    return subprocess.run([sys.executable, os.path.join(HERE, name)], check=False).returncode


if __name__ == "__main__":
    if run("test_docx_common.py") != 0:
        sys.exit(1)
    if run("test_validator_negative.py") != 0:
        sys.exit(1)
    if run("test_iteration_scenarios.py") != 0:
        sys.exit(1)
    sys.exit(run("test_project_model.py"))
