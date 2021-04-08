from setuptools import setup
from hn2epub.cli import __version__

setup(
    name="hn2epub",
    version=__version__,
    py_modules=["hn2epub"],
    install_requires=[
        "Flask",
        "requests",
        "requests_cache",
        "ebooklib",
        "Pillow",
        "selenium",
        "click",
        "cerberus",
        "timestring",
        "yoyo-migrations",
        "python-dateutil",
    ],
    entry_points={"console_scripts": ["hn2epub=hn2epub.cli:app"],},
)
