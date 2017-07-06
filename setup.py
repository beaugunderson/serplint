#!/usr/bin/env python

import sys

from setuptools import find_packages, setup

setup_requires = []

# I only release from OS X so markdown/pypandoc isn't needed in Windows
if not sys.platform.startswith('win'):
    setup_requires.extend([
        'setuptools-markdown',
    ])

setup(
    name='serplint',
    author='Beau Gunderson',
    author_email='beau@beaugunderson.com',
    url='https://github.com/beaugunderson/serplint',
    description='A linter for the serpent language',
    long_description_markdown_filename='README.md',
    keywords=['serpent', 'ethereum'],
    version='1.4.0',
    license='MIT',
    packages=find_packages(),
    py_modules=['serplint'],
    entry_points={
        'console_scripts': [
            'serplint = serplint:serplint',
        ]
    },
    install_requires=[
        'click==6.7',
        'ethereum-serpent-augur-temp==2.0.2',
    ],
    setup_requires=setup_requires,
    classifiers=[
        'Development Status :: 5 - Production/Stable',

        'Intended Audience :: End Users/Desktop',

        'License :: OSI Approved :: MIT License',

        'Operating System :: POSIX',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS :: MacOS X',

        'Topic :: Utilities',

        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 3',
    ])
