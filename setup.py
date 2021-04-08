from setuptools import setup
from hn2ebook import __version__

setup(
    name="hn2ebook",
    version=__version__,
    py_modules=["hn2ebook"],
    install_requires=[
        "toml",
        "Flask",
        "requests",
        "requests_cache",
        "ebooklib",
        "Pillow",
        "selenium",
        "Click",
        "cerberus",
        "timestring",
        "yoyo-migrations",
        "python-dateutil",
    ],
    entry_points={"console_scripts": ["hn2ebook=hn2ebook.cli:app"],},
)
