#!/usr/bin/env vpython
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Automatically updates the .proto files in this directory.

This is not necessarily used for all proto files in this directory;
but should update those listed in SUB_PATHS.
"""

import json
import os
import tarfile

import requests

BASE_URL = 'https://chromium.googlesource.com/infra/luci/luci-go'
LOG_URL = BASE_URL+'/+log/master/%s?format=JSON&n=1'
TAR_URL = BASE_URL+'/+archive/%s/%s.tar.gz'

SUB_PATHS = [
  'buildbucket/proto',
  'common/proto',
  'gce/api/config/v1',
  'led/job',
  'lucictx',
  'resultdb/proto',
]

def main():
  """Automatically updates the .proto files in this directory."""
  base_dir = os.path.abspath(os.path.dirname(__file__))

  for sub in SUB_PATHS:
    sub_dir = os.path.join(base_dir, os.path.normpath(sub))
    if not os.path.exists(sub_dir):
      os.makedirs(sub_dir)
    os.chdir(sub_dir)

    resp = requests.get(LOG_URL % (sub,))
    commit = str(json.loads(resp.text[4:])['log'][0]['commit'])
    print 'Updating %r to %r' % (sub, commit)

    resp = requests.get(TAR_URL % (commit, sub), stream=True).raw
    with tarfile.open(mode='r|*', fileobj=resp) as tar:
      for item in tar:
        if item.name.endswith('_test.proto'):
          print 'Skipping %r' % item.name
          continue
        if 'internal' in item.name:
          print 'Skipping %r' % item.name
          continue
        if item.name.endswith('.proto'):
          print 'Extracting %r' % item.name
          tar.extract(item, '.')

    with open('README.md', 'w') as rmd:
      print >> rmd, '// Generated by update.py. DO NOT EDIT.'
      print >> rmd, 'These protos were copied from:'
      print >> rmd, BASE_URL+'/+/'+commit+'/'+sub

  print 'Done.'


if __name__ == '__main__':
  main()
