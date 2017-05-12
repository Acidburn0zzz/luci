# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import httplib

from recipe_engine import recipe_test_api

class UrlTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover

  def _response(self, step_name, data, size, status_code, error_body):
    step_data = [
        self.m.json.output({
          'status_code': status_code,
          'success': status_code in (httplib.OK, httplib.NO_CONTENT),
          'size': size,
          'error_body': error_body,
        }, name='status_json'),
    ]
    if data:
      step_data.append(data)
    return self.step_data(step_name, *step_data)

  def error(self, step_name, status_code, body=None):
    body = body or 'HTTP Error (%d)' % (status_code,)
    return self._response(
        step_name,
        None,
        len(body),
        status_code,
        body)

  def text(self, step_name, v):
    return self._response(
        step_name,
        self.m.raw_io.output_text(v, name='output'),
        len(v),
        200,
        None)

  def json(self, step_name, obj):
    return self._response(
        step_name,
        self.m.json.output(obj, name='output'),
        len(self.m.json.dumps(obj)),
        200,
        None)
