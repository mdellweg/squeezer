# -*- coding: utf-8 -*-

# copyright (c) 2019, Matthias Dellweg
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import traceback
from time import sleep

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.pulp.squeezer.plugins.module_utils.openapi import OpenAPI


PAGE_LIMIT = 20
CONTENT_CHUNK_SIZE = 512 * 1024  # 1/2 MB


class SqueezerException(Exception):
    pass


class PulpAnsibleModule(AnsibleModule):
    def __init__(self, **kwargs):
        argument_spec = dict(
            pulp_url=dict(required=True),
            username=dict(required=True),
            password=dict(required=True, no_log=True),
            validate_certs=dict(type="bool", default=True),
        )
        argument_spec.update(kwargs.pop("argument_spec", {}))
        supports_check_mode = kwargs.pop("supports_check_mode", True)
        super(PulpAnsibleModule, self).__init__(
            argument_spec=argument_spec,
            supports_check_mode=supports_check_mode,
            **kwargs
        )

    def __enter__(self):
        self._changed = False
        self._results = {}
        self.pulp_api = OpenAPI(
            base_url=self.params["pulp_url"],
            doc_path="/pulp/api/v3/docs/api.json",
            username=self.params["username"],
            password=self.params["password"],
            validate_certs=self.params["validate_certs"],
        )

        return self

    def __exit__(self, exc_class, exc_value, tb):
        if exc_class is None:
            self.exit_json(changed=self._changed, **self._results)
        else:
            if issubclass(exc_class, SqueezerException):
                self.fail_json(msg=str(exc_value), changed=self._changed)
                return True
            elif issubclass(exc_class, Exception):
                self.fail_json(
                    msg=str(exc_value),
                    changed=self._changed,
                    exception="\n".join(
                        traceback.format_exception(exc_class, exc_value, tb)
                    ),
                )
                return True

    def set_changed(self):
        self._changed = True

    def set_result(self, key, value):
        self._results[key] = value


class PulpEntityAnsibleModule(PulpAnsibleModule):
    def __init__(self, **kwargs):
        argument_spec = dict(state=dict(choices=["present", "absent"],),)
        argument_spec.update(kwargs.pop("argument_spec", {}))
        super(PulpEntityAnsibleModule, self).__init__(
            argument_spec=argument_spec, **kwargs
        )


class PulpEntity(object):
    def __init__(self, module, natural_key=None, desired_attributes=None, uploads=None):
        self.module = module
        self.entity = None
        self.natural_key = natural_key
        self.desired_attributes = desired_attributes or {}
        self.uploads = uploads

    @property
    def href(self):
        return self.entity["pulp_href"]

    @property
    def primary_key(self):
        return {self._href: self.entity["pulp_href"]}

    def find(self):
        if not hasattr(self, "_list_id"):
            raise SqueezerException("This entity is not enumeratable.")
        parameters = {"limit": 1}
        parameters.update(self.natural_key)
        search_result = self.module.pulp_api.call(self._list_id, parameters=parameters)
        if search_result["count"] == 1:
            self.entity = search_result["results"][0]
        else:
            self.entity = None

    def list(self):
        if not hasattr(self, "_list_id"):
            raise SqueezerException("This entity is not enumeratable.")
        entities = []
        offset = 0
        search_result = {"next": True}
        while search_result["next"]:
            search_result = self.module.pulp_api.call(
                self._list_id, parameters={"limit": PAGE_LIMIT, "offset": offset}
            )
            entities.extend(search_result["results"])
            offset += PAGE_LIMIT
        return entities

    def read(self):
        if not hasattr(self, "_read_id"):
            raise SqueezerException("This entity is not readable.")
        self.entity = self.module.pulp_api.call(
            self._read_id, parameters=self.primary_key
        )

    def create(self):
        if not hasattr(self, "_create_id"):
            raise SqueezerException("This entity is not creatable.")
        self.entity = dict()
        self.entity.update(self.natural_key)
        self.entity.update(self.desired_attributes)
        if not self.module.check_mode:
            response = self.module.pulp_api.call(
                self._create_id, body=self.entity, uploads=self.uploads
            )
            if response and "task" in response:
                task = PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()
                self.entity = {"pulp_href": task["created_resources"][0]}
                self.read()
            else:
                self.entity = response
        self.module.set_changed()

    def update(self):
        changed = False
        for key, value in self.desired_attributes.items():
            if self.entity.get(key) != value:
                self.entity[key] = value
                changed = True
        if changed:
            if not hasattr(self, "_update_id"):
                raise SqueezerException("This entity is immutable.")
            if not self.module.check_mode:
                response = self.module.pulp_api.call(
                    self._update_id, parameters=self.primary_key, body=self.entity
                )
                if response and "task" in response:
                    PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()
                    self.read()
                else:
                    self.entity = response
            self.module.set_changed()

    def delete(self):
        if not hasattr(self, "_delete_id"):
            raise SqueezerException("This entity is not deletable.")
        if not self.module.check_mode:
            response = self.module.pulp_api.call(
                self._delete_id, parameters=self.primary_key
            )
            if response and "task" in response:
                PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()
        self.entity = None
        self.module.set_changed()

    def sync(self, remote_href):
        if not hasattr(self, "_sync_id"):
            raise SqueezerException("This entity is not syncable.")
        response = self.module.pulp_api.call(
            self._sync_id, parameters=self.primary_key, body={"remote": remote_href}
        )
        return PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()

    def process_special(self):
        raise SqueezerException(
            "Invalid state ({0}) for entity.".format(self.module.params["state"])
        )

    def process(self):
        if None not in self.natural_key.values():
            self.find()
            if self.module.params["state"] is None:
                pass
            elif self.module.params["state"] == "present":
                if self.entity is None:
                    self.create()
                else:
                    self.update()
            elif self.module.params["state"] == "absent":
                if self.entity is not None:
                    self.delete()
            else:
                self.process_special()

            self.module.set_result(self._name_singular, self.entity)
        else:
            entities = self.list()
            self.module.set_result(self._name_plural, entities)


class PulpArtifact(PulpEntity):
    _href = "artifact_href"
    _list_id = "artifacts_list"
    _read_id = "artifacts_read"
    _create_id = "artifacts_create"
    _delete_id = "artifacts_delete"

    _name_singular = "artifact"
    _name_plural = "artifacts"

    def create(self):
        filename = self.uploads["file"]
        size = os.stat(filename).st_size
        if size > CONTENT_CHUNK_SIZE:
            if not self.module.check_mode:
                artifact_href = PulpUpload.chunked_upload(
                    self.module, filename, self.natural_key["sha256"], size
                )
                self.entity = {"pulp_href": artifact_href}
                self.read()
            else:
                self.entity = self.natural_key
            self.module.set_changed()
            return self.entity
        with open(filename, "rb") as f:
            self.uploads["file"] = f.read()
        return super(PulpArtifact, self).create()


class PulpOrphans(PulpEntity):
    _delete_id = "orphans_delete"

    def delete(self):
        if not self.module.check_mode:
            response = self.module.pulp_api.call(self._delete_id)
            task = PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()
            response = task["progress_reports"]
            response = {
                item["message"].split(" ")[-1].lower(): item["total"]
                for item in response
            }
        else:
            response = {
                "artifacts": 0,
                "content": 0,
            }
        self.module.set_changed()
        return response


class PulpTask(PulpEntity):
    _href = "task_href"
    _list_id = "tasks_list"
    _read_id = "tasks_read"
    _delete_id = "tasks_delete"
    _cancel_id = "tasks_cancel"

    _name_singular = "task"
    _name_plural = "tasks"

    def find(self):
        parameters = {"task_href": self.natural_key["pulp_href"]}
        self.entity = self.module.pulp_api.call(self._read_id, parameters=parameters)

    def process_special(self):
        if self.module.params["state"] in ["canceled", "completed"]:
            if self.entity is None:
                raise SqueezerException("Entity not found.")
            if self.entity["state"] in ["waiting", "running"]:
                self.module.set_changed()
                self.entity["state"] = self.module.params["state"]
                if not self.module.check_mode:
                    if self.module.params["state"] == "canceled":
                        self.module.pulp_api.call(
                            self._cancel_id,
                            parameters=self.primary_key,
                            body=self.entity,
                        )
                    self.wait_for(desired_state=self.module.params["state"])
        else:
            super(PulpTask, self).process_special()

    def wait_for(self, desired_state="completed"):
        self.find()
        while self.entity["state"] not in ["completed", "failed", "canceled"]:
            sleep(2)
            self.read()
        if self.entity["state"] != desired_state:
            if self.entity["state"] == "failed":
                raise Exception(
                    "Task failed to complete. ({0}; {1})".format(
                        self.entity["state"], self.entity["error"]["description"]
                    )
                )
            raise Exception("Task did not reach {0} state".format(desired_state))
        return self.entity


class PulpUpload(PulpEntity):
    _href = "upload_href"
    _create_id = "uploads_create"
    _update_id = "uploads_update"
    _delete_id = "uploads_delete"
    _commit_id = "uploads_commit"

    @classmethod
    def chunked_upload(cls, module, path, sha256, size):
        offset = 0

        upload = cls(module, natural_key={}, desired_attributes={"size": size})
        upload.create()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(CONTENT_CHUNK_SIZE), b""):
                    actual_chunk_size = len(chunk)
                    content_range = "bytes {start}-{end}/{size}".format(
                        start=offset, end=offset + actual_chunk_size - 1, size=size,
                    )
                    parameters = upload.primary_key
                    parameters["Content-Range"] = content_range
                    uploads = {"file": chunk}
                    module.pulp_api.call(
                        cls._update_id, parameters=parameters, uploads=uploads
                    )
                    offset += actual_chunk_size

                response = module.pulp_api.call(
                    cls._commit_id,
                    parameters=upload.primary_key,
                    body={"sha256": sha256},
                )
                task = PulpTask(module, {"pulp_href": response["task"]}).wait_for()
        except Exception:
            module.pulp_api.call(cls._delete_id, parameters=upload.primary_key)
            raise

        artifact_href = task["created_resources"][0]
        return artifact_href


# Content Guards


class PulpContentGuard(PulpEntity):
    # TODO find an endpoint to enumerate all ContentGuards
    _href = "x509_cert_guard_href"
    _list_id = "contentguards_certguard_x509_list"
    _read_id = "contentguards_certguard_x509_read"

    _name_singular = "content_guard"
    _name_plural = "content_guards"


class PulpX509CertGuard(PulpEntity):
    _href = "x509_cert_guard_href"
    _list_id = "contentguards_certguard_x509_list"
    _read_id = "contentguards_certguard_x509_read"
    _create_id = "contentguards_certguard_x509_create"
    _update_id = "contentguards_certguard_x509_update"
    _delete_id = "contentguards_certguard_x509_delete"

    _name_singular = "content_guard"
    _name_plural = "content_guards"


# File entities


class PulpFileContent(PulpEntity):
    _href = "file_content_href"
    _list_id = "content_file_files_list"
    _read_id = "content_file_files_read"
    _create_id = "content_file_files_create"

    _name_singular = "content"
    _name_plural = "contents"

    def create(self):
        sha256_digest = self.natural_key.pop("sha256")
        artifact = PulpArtifact(self.module, {"sha256": sha256_digest})
        artifact.find()
        self.natural_key["artifact"] = artifact.href
        super(PulpFileContent, self).create()

        if self.module.check_mode:
            # Repair the fake result
            self.entity.pop("artifact")
            self.entity["sha256"] = sha256_digest


class PulpFileDistribution(PulpEntity):
    _href = "file_distribution_href"
    _list_id = "distributions_file_file_list"
    _read_id = "distributions_file_file_read"
    _create_id = "distributions_file_file_create"
    _update_id = "distributions_file_file_update"
    _delete_id = "distributions_file_file_delete"

    _name_singular = "distribution"
    _name_plural = "distributions"


class PulpFilePublication(PulpEntity):
    _href = "file_publication_href"
    _list_id = "publications_file_file_list"
    _read_id = "publications_file_file_read"
    _create_id = "publications_file_file_create"
    _update_id = "publications_file_file_update"
    _delete_id = "publications_file_file_delete"

    _name_singular = "publication"
    _name_plural = "publications"


class PulpFileRemote(PulpEntity):
    _href = "file_remote_href"
    _list_id = "remotes_file_file_list"
    _read_id = "remotes_file_file_read"
    _create_id = "remotes_file_file_create"
    _delete_id = "remotes_file_file_delete"
    _update_id = "remotes_file_file_update"
    _partial_update = "remotes_file_file_partial_update"

    _name_singular = "remote"
    _name_plural = "remotes"


class PulpFileRepository(PulpEntity):
    _href = "file_repository_href"
    _list_id = "repositories_file_file_list"
    _read_id = "repositories_file_file_read"
    _create_id = "repositories_file_file_create"
    _update_id = "repositories_file_file_update"
    _delete_id = "repositories_file_file_delete"
    _sync_id = "repositories_file_file_sync"

    _name_singular = "repository"
    _name_plural = "repositories"


class PulpFileRepositoryVersion(PulpEntity):
    _href = "file_repository_version_href"
    _list_id = "repositories_file_file_versions_list"
    _read_id = "repositories_file_file_versions_read"
    _repair_id = "repositories_file_file_versions_repair"

    def repair(self):
        if not self.module.check_mode:
            response = self.module.pulp_api.call(
                self._repair_id, parameters=self.primary_key
            )
            task = PulpTask(self.module, {"pulp_href": response["task"]}).wait_for()
            response = task
            report = {
                "corrupted": next(
                    report["done"]
                    for report in response["progress_reports"]
                    if report["code"] == "repair.corrupted"
                ),
                "repaired": next(
                    report["done"]
                    for report in response["progress_reports"]
                    if report["code"] == "repair.repaired"
                ),
            }
            if report["repaired"]:
                self.module.set_changed()
        else:
            report = {"corrupted": 0, "repaired": 0}
        return report


# Ansible entities


class PulpAnsibleDistribution(PulpEntity):
    _href = "ansible_distribution_href"
    _list_id = "distributions_ansible_ansible_list"
    _read_id = "distributions_ansible_ansible_read"
    _create_id = "distributions_ansible_ansible_create"
    _update_id = "distributions_ansible_ansible_update"
    _delete_id = "distributions_ansible_ansible_delete"

    _name_singular = "distribution"
    _name_plural = "distributions"


class PulpAnsibleRemote(PulpEntity):
    _href = "ansible_remote_href"
    _list_id = "remotes_ansible_ansible_list"
    _read_id = "remotes_ansible_ansible_read"
    _create_id = "remotes_ansible_ansible_create"
    _update_id = "remotes_ansible_ansible_update"
    _delete_id = "remotes_ansible_ansible_delete"

    _name_singular = "remote"
    _name_plural = "remotes"


class PulpAnsibleRepository(PulpEntity):
    _href = "ansible_repository_href"
    _list_id = "repositories_ansible_ansible_list"
    _read_id = "repositories_ansible_ansible_read"
    _create_id = "repositories_ansible_ansible_create"
    _update_id = "repositories_ansible_ansible_update"
    _delete_id = "repositories_ansible_ansible_delete"
    _sync_id = "repositories_ansible_ansible_sync"

    _name_singular = "repository"
    _name_plural = "repositories"


# Python entities


class PulpPythonDistribution(PulpEntity):
    _href = "python_distribution_href"
    _list_id = "distributions_python_pypi_list"
    _read_id = "distributions_python_pypi_read"
    _create_id = "distributions_python_pypi_create"
    _update_id = "distributions_python_pypi_update"
    _delete_id = "distributions_python_pypi_delete"

    _name_singular = "distribution"
    _name_plural = "distributions"


class PulpPythonPublication(PulpEntity):
    _href = "python_publication_href"
    _list_id = "publications_python_pypi_list"
    _read_id = "publications_python_pypi_read"
    _create_id = "publications_python_pypi_create"
    _delete_id = "publications_python_pypi_delete"

    _name_singular = "publication"
    _name_plural = "publications"


class PulpPythonRemote(PulpEntity):
    _href = "python_remote_href"
    _list_id = "remotes_python_python_list"
    _read_id = "remotes_python_python_read"
    _create_id = "remotes_python_python_create"
    _update_id = "remotes_python_python_update"
    _delete_id = "remotes_python_python_delete"

    _name_singular = "remote"
    _name_plural = "remotes"


class PulpPythonRepository(PulpEntity):
    _href = "python_repository_href"
    _list_id = "repositories_python_python_list"
    _read_id = "repositories_python_python_read"
    _create_id = "repositories_python_python_create"
    _update_id = "repositories_python_python_update"
    _delete_id = "repositories_python_python_delete"
    _sync_id = "repositories_python_python_sync"

    _name_singular = "repository"
    _name_plural = "repositories"
