# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from . import StreamEngine
from .product import ProductStreamEngine


class StreamEngineInvariants(StreamEngine):
  """Checks that the users are using a StreamEngine hygenically.

  Multiply with actually functional StreamEngines so you don't have to check
  these all over the place.
  """
  def __init__(self):
    self._streams = set()

  @classmethod
  def wrap(cls, other):
    """Returns (ProductStreamEngine): A product applying invariants to "other".
    """
    return ProductStreamEngine(cls(), other)

  class StepStream(StreamEngine.StepStream):
    def __init__(self, engine, step_name):
      super(StreamEngineInvariants.StepStream, self).__init__()
      self._engine = engine
      self._step_name = step_name
      self._open = True
      self._logs = {}
      self._status = 'SUCCESS'

    def write_line(self, line):
      assert '\n' not in line
      assert self._open

    def close(self):
      assert self._open
      for log_name, log in self._logs.iteritems():
        assert not log._open, 'Log %s still open when closing step %s' % (
          log_name, self._step_name)
      self._open = False

    def new_log_stream(self, log_name):
      assert self._open
      assert log_name not in self._logs, 'Log %s already exists in step %s' % (
        log_name, self._step_name)
      ret = self._engine.LogStream(self, log_name)
      self._logs[log_name] = ret
      return ret

    def add_step_text(self, text):
      pass

    def add_step_summary_text(self, text):
      pass

    def add_step_link(self, name, url):
      assert isinstance(name, basestring), 'Link name %s is not a string' % name
      assert isinstance(url, basestring), 'Link url %s is not a string' % url

    def set_step_status(self, status):
      assert status in ('SUCCESS', 'WARNING', 'FAILURE', 'EXCEPTION')
      if status == 'SUCCESS':
        # A constraint imposed by the annotations implementation
        assert self._status == 'SUCCESS', (
          'Cannot set successful status after status is %s' % self._status)
      self._status = status

    def set_build_property(self, key, value):
      pass

    def trigger(self, spec):
      assert '\n' not in spec # Spec must fit on one line.
      json.loads(spec) # Spec must be a valid json object.

    def set_manifest_link(self, name, sha256, url):
      pass

  class LogStream(StreamEngine.Stream):
    def __init__(self, step_stream, log_name):
      self._step_stream = step_stream
      self._log_name = log_name
      self._open = True

    def write_line(self, line):
      assert '\n' not in line
      assert self._step_stream._open
      assert self._open

    def close(self):
      assert self._step_stream._open
      assert self._open
      self._open = False

  def new_step_stream(self, step_config):
    assert step_config.name not in self._streams, (
        'Step %s already exists' % step_config.name)
    self._streams.add(step_config.name)
    return self.StepStream(self, step_config.name)

