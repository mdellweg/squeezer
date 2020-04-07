#!/usr/bin/python
# -*- coding: utf-8 -*-

# copyright (c) 2020, Matthias Dellweg
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r"""
---
module: repair
short_description: Repair corrupted artifacts in a repository version on a pulp server
description:
  - "This performes a repair task that identifies corrupted artifact files and attempts to refetch them."
options:
  repository:
    description:
      - Name of the repository to have a version repaired
    type: str
    required: true
  version:
    description:
      - Version number to be repaired
    type: int
    required: false
extends_documentation_fragment:
  - pulp.squeezer.pulp
author:
  - Matthias Dellweg (@mdellweg)
"""

EXAMPLES = r"""
- name: Repair latest version of a repository
  repair:
    api_url: localhost:24817
    username: admin
    password: password
    repository: my_file_repo
- name: Repair first version of a repository
  repair:
    api_url: localhost:24817
    username: admin
    password: password
    repository: my_file_repo
    version: 1
"""

RETURN = r"""
  corrupted:
    description: Number of identified corrupted artifacts
    type: int
    returned: always
  repaired:
    description: Number of successfully repaired artifacts
    type: int
    returned: always
"""


from ansible_collections.pulp.squeezer.plugins.module_utils.pulp import (
    PulpAnsibleModule,
    PulpFileRepository,
    PulpFileRepositoryVersion,
    SqueezerException,
)


def main():
    with PulpAnsibleModule(
        argument_spec=dict(repository=dict(required=True), version=dict(type="int"),),
    ) as module:

        repository_name = module.params["repository"]
        version = module.params["version"]

        repository = PulpFileRepository(module, {"name": module.params["repository"]})
        repository.find()
        if repository is None:
            raise SqueezerException(
                "Repository '{0}' not found.".format(module.params["repository"])
            )
        # TODO check if version exists
        if version:
            repository_version_href = repository.entity[
                "versions_href"
            ] + "{version}/".format(version=version)
        else:
            repository_version_href = repository.entity["latest_version_href"]
        natural_key = {"repository_version": repository_version_href}

        repository_version = PulpFileRepositoryVersion(module)
        # Hack
        repository_version.entity = {"pulp_href": repository_version_href}
        repository_version.read()
        report = repository_version.repair()

        module.set_result("corrupted", report["corrupted"])
        module.set_result("repaired", report["repaired"])


if __name__ == "__main__":
    main()
