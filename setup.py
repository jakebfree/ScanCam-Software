#!/usr/bin/env python
from distutils.core import setup

setup(name='scancam',
      version=open('version').readline().strip(),
      author='Jake Freeman',
      author_email='jacob.freeman@colorado.edu',
      package_dir={'': 'lib'},
      packages = ['scancam', 'bst_camera', 'zaber'],
      scripts = ['bin/scancam', 'bin/micro5-scan-builder', \
             'bin/proto-scan-builder', 'bin/scancam-tester',\
             'bin/scancam-prepare-to-stow', ],
      data_files=[('/etc', ['etc/scancam.conf'])],
)
     
