# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for Tricium analyzers to use.

This recipe module is intended to support different kinds of
analyzer recipes, including:
  * Recipes that wrap one or more legacy analyzers.
  * Recipes that accumulate comments one by one.
  * Recipes that wrap other tools and parse their output.
"""

import fnmatch

from google.protobuf import json_format

from recipe_engine import recipe_api

from . import legacy_analyzers

from PB.tricium.data import Data


class TriciumApi(recipe_api.RecipeApi):
  """TriciumApi provides basic support for Tricium."""

  # Expose pre-defined analyzers, as well the LegacyAnalyzer class.
  LegacyAnalyzer = legacy_analyzers.LegacyAnalyzer
  analyzers = legacy_analyzers.Analyzers

  def __init__(self, **kwargs):
    """Sets up the API.

    Initializes an empty list of comments for use with
    add_comment and write_comments.
    """
    super(TriciumApi, self).__init__(**kwargs)
    self._comments = []

  def add_comment(self,
                  category,
                  message,
                  path,
                  start_line=0,
                  end_line=0,
                  start_char=0,
                  end_char=0,
                  suggestions=()):
    """Adds one comment to accumulate."""
    comment = Data.Comment()
    comment.category = category
    comment.message = message
    comment.path = path
    comment.start_line = start_line
    comment.end_line = end_line
    comment.start_char = start_char
    comment.end_char = end_char
    for s in suggestions:
      # Convert from dict to proto message by way of JSON.
      json_format.Parse(self.m.json.dumps(s), comment.suggestions.add())
    self._add_comment(comment)

  def _add_comment(self, comment):
    if comment not in self._comments:
      self._comments.append(comment)

  def write_comments(self):
    """Emit the results accumulated by `add_comment` and `run_legacy`."""
    results = Data.Results()
    results.comments.extend(self._comments)
    step = self.m.step('write results', [])
    num_comments = len(results.comments)
    if num_comments > 50:
      # Tricium will refuse to post comments if there are too many, but we
      # don't yet know how many of these comments are included in changed lines
      # and would be posted. Add a warning to try to help with clarification in
      # the case that Tricium unexpectedly emits no comments.
      step.presentation.status = self.m.step.WARNING
      step.presentation.step_text = (
          '%s comments created, Tricium may refuse to post comments if there '
          'are too many in changed lines.' % num_comments)
      return
    # The "tricium" output property is read by the Tricium service.
    results_json = json_format.MessageToJson(results, indent=0)
    step.presentation.properties['tricium'] = results_json

  def run_legacy(self,
                 analyzers,
                 input_base,
                 affected_files,
                 commit_message,
                 emit=True):
    """Runs legacy analyzers.

    This function internally accumulates the comments from the analyzers it
    runs to the same global storage used by `add_comment()`. By default it
    emits comments from legacy analyzers to the tricium output property,
    along with any comments previously created by calling `add_comment()`
    directly, after running all the specified analyzers.

    Args:
      * analyzers (List(LegacyAnalyer)): Analyzers to run.
      * input_base (Path): The Tricium input dir, generally a checkout base.
      * affected_files (List(str)): Paths of files in the change, relative
        to input_base.
      * commit_message (str): Commit message from Gerrit.
      * emit (bool): Whether to write results to the tricium output
        property. If unset, the caller will be responsible for calling
        `write_comments` to emit the comments added by the legacy analyzers.
        This is useful for recipes that need to run a mixture of custom
        analyzers (using `add_comment()` to store comments) and legacy
        analyzers.
    """
    self._write_files_data(affected_files, commit_message, input_base)
    # For each analyzer, download the CIPD package, run it and accumulate
    # results. Note: Each analyzer could potentially be run in parallel.
    for analyzer in analyzers:
      with self.m.step.nest(analyzer.name) as parent_step:
        # Check analyzer.path_filters and conditionally skip.
        if not _matches_path_filters(affected_files, analyzer.path_filters):
          parent_step.presentation.step_text = 'skipped due to path filters'
        try:
          analyzer_dir = self.m.path['cleanup'].join(analyzer.name)
          output_base = analyzer_dir.join('out')
          package_dir = analyzer_dir.join('package')
          self._fetch_legacy_analyzer(package_dir, analyzer)
          results = self._run_legacy_analyzer(
              package_dir,
              analyzer,
              input_dir=input_base,
              output_dir=output_base)
          # Show step results. If there are too many comments, don't include
          # them. If one analyzer fails, continue running the rest.
          for comment in results.comments:
            self._add_comment(comment)
          num_comments = len(results.comments)
          parent_step.presentation.step_text = '%s comment(s)' % num_comments
          parent_step.presentation.logs['result'] = json_format.MessageToJson(
              results)
        except self.m.step.StepFailure:
          parent_step.presentation.step_text = 'failed'
    # The tricium data dir with files.json is written in the checkout cache
    # directory and should be cleaned up.
    self.m.file.rmtree('clean up tricium data dir', input_base.join('tricium'))

    if emit:
      self.write_comments()

  def _write_files_data(self, affected_files, commit_message, base_dir):
    """Writes a Files input message to a file.

    Args:
      * affected_files (List(str)): File paths. This should
        be relative to `base_dir`.
      * commit_message (str): The commit message from Gerrit.
      * base_dir (Path): Input files base directory.
    """
    files = Data.Files()
    files.commit_message = commit_message
    for path in affected_files:
      # TODO(qyearsley): Set the is_binary and status fields for each file.
      # Analyzers use these fields to determine whether to skip files.
      f = files.files.add()
      f.path = path
    data_dir = self._ensure_data_dir(base_dir)
    # Note: The JSON written self.m.file.write_proto doesn't work for what
    # Tricium analyzers expect, but json_format.MessageToJson does.
    files_json = json_format.MessageToJson(files)
    self.m.file.write_text('write files.json', data_dir.join('files.json'),
                           files_json)

  def _read_results(self, base_dir):
    """Reads a Tricium Results message from a file.

    Args:
      * base_dir (Path): A directory. Generally this will
        be the same as the -output arg passed to the analyzer.

    Returns: Results protobuf message.
    """
    data_dir = self._ensure_data_dir(base_dir)
    results_json = self.m.file.read_text(
        'read results',
        data_dir.join('results.json'),
        test_data='{"comments":[]}')
    return json_format.Parse(results_json, Data.Results())

  def _ensure_data_dir(self, base_dir):
    """Creates the Tricium data directory if it doesn't exist.

    Simple Tricium analyzers assume that data is input/output from a
    particular subpath relative to the input/output paths passed.

    Args:
      * base_dir (Path): A directory, could be either the -input
        or -output passed to a Tricium analyzer.

    Returns: Tricium data file directory inside base_dir.
    """
    data_dir = base_dir.join('tricium', 'data')
    self.m.file.ensure_directory('ensure tricium data dir', data_dir)
    return data_dir

  def _fetch_legacy_analyzer(self, package_dir, analyzer):
    """Fetches an analyzer package from CIPD.

    Args:
      * packages_dir (Path): The path to fetch to.
      * analyzer (LegacyAnalyzer): Analyzer package to fetch.
    """
    ensure_file = self.m.cipd.EnsureFile()
    ensure_file.add_package(analyzer.package, version='live')
    self.m.cipd.ensure(package_dir, ensure_file)

  def _run_legacy_analyzer(self, package_dir, analyzer, input_dir, output_dir):
    """Runs a simple legacy analyzer executable and returns the results.

    Args:
      * package_dir (Path): The directory where the analyzer CIPD package
        contents have been unpacked to.
      * analyzer (LegacyAnalyzer): Analyzer object to run.
      * input_dir (Path): The Tricium input dir, which is expected to contain
        files as well as the metadata at tricium/data/files.json.
      * output_dir (Path): The directory to write results into.
    """
    # Some analyzers depend on other files in the CIPD package, so cwd is
    # expected to be the directory with the analyzer.
    with self.m.context(cwd=package_dir):
      cmd = [
          package_dir.join(analyzer.executable), '-input', input_dir, '-output',
          output_dir
      ] + analyzer.extra_args
      self.m.step('run analyzer',
                  cmd).presentation.logs['cmd'] = ' '.join(str(c) for c in cmd)
    return self._read_results(output_dir)


def _matches_path_filters(files, patterns):
  if len(patterns) == 0:
    return True
  for p in patterns:
    if any(fnmatch.fnmatch(f, p) for f in files):
      return True
  return False
