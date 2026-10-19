"""Packaging hook: ship CHANGELOG.md inside the package for the About window.

Everything else is configured in pyproject.toml.
"""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithChangelog(build_py):
    def run(self):
        super().run()
        source = Path(__file__).resolve().parent / "CHANGELOG.md"
        if source.is_file():
            target = Path(self.build_lib) / "aula_f87" / "data" / "CHANGELOG.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


setup(cmdclass={"build_py": BuildWithChangelog})
