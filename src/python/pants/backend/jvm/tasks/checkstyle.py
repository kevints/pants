# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.option.options import Options
from pants.process.xargs import Xargs
from pants.util.dirutil import safe_open


class Checkstyle(NailgunTask, JvmToolTaskMixin):

  _CHECKSTYLE_MAIN = 'com.puppycrawl.tools.checkstyle.Main'

  _CONFIG_SECTION = 'checkstyle'

  _JAVA_SOURCE_EXTENSION = '.java'

  _CHECKSTYLE_BOOTSTRAP_KEY = "checkstyle"

  @classmethod
  def register_options(cls, register):
    super(Checkstyle, cls).register_options(register)
    register('--skip', action='store_true', help='Skip checkstyle.')
    register('--configuration', help='Path to the checkstyle configuration file.')
    register('--properties', type=Options.dict, default={},
             help='Dictionary of property mappings to use for checkstyle.properties.')
    register('--confs', default=['default'],
             help='One or more ivy configurations to resolve for this target. This parameter is '
                  'not intended for general use. ')
    register('--bootstrap-tools', type=Options.list, default=['//:checkstyle'],
             help='Pants targets used to bootstrap this tool.')

  def __init__(self, *args, **kwargs):
    super(Checkstyle, self).__init__(*args, **kwargs)
    self.register_jvm_tool(self._CHECKSTYLE_BOOTSTRAP_KEY, self.get_options().bootstrap_tools)

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    # TODO(John Sirois): this is a fake requirement on 'ivy_jar_products' in order to force
    # resolve to run before this goal. Require a new CompileClasspath product to be produced by
    # IvyResolve instead.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('ivy_jar_products')
    round_manager.require_data('exclusives_groups')

  def _is_checked(self, target):
    return (isinstance(target, Target) and
            target.has_sources(self._JAVA_SOURCE_EXTENSION) and
            (not target.is_synthetic))

  def execute(self):
    if self.get_options().skip:
      return
    targets = self.context.targets(self._is_checked)
    with self.invalidated(targets) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)
      sources = self.calculate_sources(invalid_targets)
      if sources:
        result = self.checkstyle(sources, invalid_targets)
        if result != 0:
          raise TaskError('java {main} ... exited non-zero ({result})'.format(
            main=self._CHECKSTYLE_MAIN, result=result))

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if source.endswith(self._JAVA_SOURCE_EXTENSION))
    return sources

  def checkstyle(self, sources, targets):
    egroups = self.context.products.get_data('exclusives_groups')
    etag = egroups.get_group_key_for_target(targets[0])
    classpath = self.tool_classpath(self._CHECKSTYLE_BOOTSTRAP_KEY)
    cp = egroups.get_classpath_for_group(etag)
    classpath.extend(jar for conf, jar in cp if conf in self.get_options().confs)

    args = [
      '-c', self.get_options().configuration,
      '-f', 'plain'
    ]

    if self.get_options().properties:
      properties_file = os.path.join(self.workdir, 'checkstyle.properties')
      with safe_open(properties_file, 'w') as pf:
        for k, v in self.get_options().properties.items():
          pf.write('{key}={value}\n'.format(key=k, value=v))
      args.extend(['-p', properties_file])

    # We've hit known cases of checkstyle command lines being too long for the system so we guard
    # with Xargs since checkstyle does not accept, for example, @argfile style arguments.
    def call(xargs):
      return self.runjava(classpath=classpath, main=self._CHECKSTYLE_MAIN,
                          args=args + xargs, workunit_name='checkstyle')
    checks = Xargs(call)

    return checks.execute(sources)
