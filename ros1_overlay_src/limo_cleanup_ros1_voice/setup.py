#!/usr/bin/env python3

from pathlib import Path

from setuptools import setup


PACKAGE_ROOT = Path(__file__).resolve().parent
AUTHORITATIVE_PACKAGE_RELATIVE = (
    Path('..') / 'limo_cleanup_voice' / 'limo_cleanup_voice')
AUTHORITATIVE_PACKAGE = (
    PACKAGE_ROOT / AUTHORITATIVE_PACKAGE_RELATIVE).resolve()


if not AUTHORITATIVE_PACKAGE.is_dir():
    raise RuntimeError(
        'authoritative limo_cleanup_voice package directory is missing')


setup(
    name='limo_cleanup_ros1_voice',
    version='0.1.0',
    packages=['limo_cleanup_voice'],
    package_dir={
        'limo_cleanup_voice': AUTHORITATIVE_PACKAGE_RELATIVE.as_posix()},
)
