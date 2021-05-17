#!/usr/bin/python
# -*- coding: utf-8 -*-

# copyright (c) 2020, Jacob Floyd
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = r"""
---
module: rpm_remote
short_description: Manage rpm remotes of a pulp api server instance
description:
  - "This performs CRUD operations on rpm remotes in a pulp api server instance."
options:
  name:
    description:
      - Name of the remote to query or manipulate
    type: str
  policy:
    description:
      - Whether downloads should be performed immediately, or lazy.
    type: str
    choices:
      - immediate
      - on_demand
      - streamed
extends_documentation_fragment:
  - pulp.squeezer.pulp
  - pulp.squeezer.pulp.entity_state
  - pulp.squeezer.pulp.remote
author:
  - Jacob Floyd (@cognifloyd)
"""

EXAMPLES = r"""
- name: Read list of rpm remotes from pulp api server
  rpm_remote:
    api_url: localhost:24817
    username: admin
    password: password
  register: remote_status
- name: Report pulp rpm remotes
  debug:
    var: remote_status
- name: Create a rpm remote
  rpm_remote:
    api_url: localhost:24817
    username: admin
    password: password
    name: new_rpm_remote
    url: https://example.org/centos/8/BaseOS/x86_64/os/
    state: present
- name: Delete a rpm remote
  rpm_remote:
    api_url: localhost:24817
    username: admin
    password: password
    name: new_rpm_remote
    state: absent
"""

RETURN = r"""
  remotes:
    description: List of rpm remotes
    type: list
    returned: when no name is given
  remote:
    description: Rpm remote details
    type: dict
    returned: when name is given
"""


from ansible_collections.pulp.squeezer.plugins.module_utils.pulp import (
    PulpEntityAnsibleModule,
    PulpRpmRemote,
)


def main():
    with PulpEntityAnsibleModule(
        argument_spec=dict(
            name=dict(),
            url=dict(),
            download_concurrency=dict(type="int"),
            policy=dict(choices=["immediate", "on_demand", "streamed"]),
            remote_username=dict(),
            remote_password=dict(no_log=True),
            ca_cert=dict(),
            client_cert=dict(),
            client_key=dict(),
            tls_validation=dict(type="bool"),
            proxy_url=dict(),
            proxy_username=dict(),
            proxy_password=dict(no_log=True),
        ),
        required_if=[("state", "present", ["name"]), ("state", "absent", ["name"])],
    ) as module:

        natural_key = {"name": module.params["name"]}
        desired_attributes = {
            key: module.params[key]
            for key in ["url", "download_concurrency", "policy", "tls_validation"]
            if module.params[key] is not None
        }

        # Nullifiable values
        if module.params["remote_username"] is not None:
            desired_attributes["username"] = module.params["remote_username"] or None
        if module.params["remote_password"] is not None:
            desired_attributes["password"] = module.params["remote_password"] or None
        desired_attributes.update(
            {
                key: module.params[key] or None
                for key in [
                    "proxy_url",
                    "proxy_username",
                    "proxy_password",
                    "ca_cert",
                    "client_cert",
                    "client_key",
                ]
                if module.params[key] is not None
            }
        )

        PulpRpmRemote(module, natural_key, desired_attributes).process()


if __name__ == "__main__":
    main()
