#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" pyfirebasestockscli

  Copyright 2019 Slash Gordon

  Use of this source code is governed by an MIT-style license that
  can be found in the LICENSE file.
"""

from setuptools import setup, find_packages

EXCLUDE_FROM_PACKAGES = ['test', 'test.*', 'test*']
VERSION = '1.0.1'

with open('README.md', 'r') as fh:
    long_description = fh.read()

INSTALL_REQUIRES = (
    [
        'firebase-admin==2.17.0',
        'pystockfilter>=1.0.6'
    ]
)

setup(
    name='pyfirebasestockscli',
    version=VERSION,
    author='Slash Gordon',
    author_email='slash.gordon.dev@gmail.com',
    package_dir={'': 'src'},
    description='portfolio+ command line interface for firebase operations.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/SlashGordon/pyfirebasestockscli',
    install_requires=INSTALL_REQUIRES,
    packages=find_packages('src', exclude=EXCLUDE_FROM_PACKAGES),
    entry_points={'console_scripts': [
            'stocks = pyfirebasestockscli:app',
    ]},
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
