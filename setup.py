#!/usr/bin/env python
from distutils.core import setup

setup(name='scancam',
      version=open('version').readline().strip(),
      author='Jake Freeman',
      author_email='jacob.freeman@colorado.edu',
      package_dir={'': 'lib'},
      packages = ['scancam', 'bst_camera', 'zaber'],
      scripts = ['bin/scancam', 'bin/flight_scan_builder', \
             'bin/proto_scan_builder', 'bin/scancam_tester',],
      data_files=[('/etc', ['etc/scancam.conf'])],
)
     
