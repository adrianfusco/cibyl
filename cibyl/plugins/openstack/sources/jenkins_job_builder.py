"""
#    Copyright 2022 Red Hat
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
import logging
import re
import xml.etree.ElementTree as ET
from io import StringIO
from typing import Iterable, List

from cibyl.models.attribute import AttributeDictValue
from cibyl.models.ci.base.job import Job
from cibyl.plugins.openstack.deployment import Deployment
from cibyl.plugins.openstack.network import Network
from cibyl.plugins.openstack.node import Node
from cibyl.plugins.openstack.storage import Storage
from cibyl.sources.plugins import SourceExtension
from cibyl.sources.source import speed_index

LOG = logging.getLogger(__name__)

TOPOLOGY = r'[a-zA-Z0-9:,]+:[0-9]+'  # controller:3,database:3,compute:2
NODE_NAME_COUNTER = r'[a-zA-Z]+:[0-9]+'
IP_VERSION = r'--network-protocol\s+ipv[4|6]'
IP_VERSION_NUMBER = r'4|6'
RELEASE = r'.*rhos-\d\d.\d-.*patches|.*rhos-\d\d-.*patches|.*send_results_to_umb.*'  # noqa: E501
RELEASE_NUMBER = r'\d\d.\d|\d\d'
CINDER_BACKEND = r'.*--storage-backend.*|.*IR_TRIPLEO_OVERCLOUD_STORAGE_BACKEND_UPD.*'  # noqa: E501
CINDER_BACKEND_NAME = r'ceph|lvm|netapp-iscsi|netapp-nfs|swift|nfs'
DEPLOYMENT = r'--deployment-files \w+\b'


def args_are_in_list(arg_list: List[str], list: Iterable[str]) -> bool:
    """
    Find if elements of 'arg_list' are members of 'list'

    param: list arg_list: e.g. a list of strings from kwargs['release'].value
    param: list list: e.g. a list of strings to match against
    return: True/False
    rtype: Bool
    """
    return (len([el for el in list if " ".join(map(str, arg_list)) in el]) > 0)


def parse_xml(path: str) -> StringIO:
    """
    Parse xml file generated by the jenkins job builder and get all
    groovy script sections found in the file.

    param: str path: the path to the xml file
    return: the StringIO instance (in memory file like instance) containing
            the groovy scripts found in the generated xml file.
    rtype: StringIO
    """
    root = ET.parse(path).getroot()
    result = ""
    for script in root.iter("script"):
        result = result + "\n" + script.text
    for dv in root.iter("defaultValue"):
        result = result + "\n" + str(dv.text)
    return StringIO(result)


class JenkinsJobBuilder(SourceExtension):
    def _get_nodes(self, path, **kwargs):
        """
        extract topology from the JJB xml file and
        represent as a Nodes dictionary

        Note: this function is not used to support filtering

        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: dictionary of Nodes
        """
        topology = self._get_topology(path, **kwargs)
        nodes = {}
        for component in topology.split(","):
            try:
                role, amount = component.split(":")
            except ValueError:
                continue
            for i in range(int(amount)):
                node_name = role + f"-{i}"
                nodes[node_name] = Node(node_name, role=role)
        return nodes

    def _get_topology(self, path, **kwargs):
        """
        extract topology from the JJB xml file and
        represent it in the form of string, e.g
           controller:3,compute:2

        Note: this function is used to support filtering
            e.g. --topology cont, --topology controller:3
        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: topology string
        """
        topology_str = ""
        if "topology" in kwargs:
            in_mem_file = parse_xml(path)
            result = set([])

            lines = [line.rstrip() for line in in_mem_file if
                     "TOPOLOGY=" in line or "TOPOLOGY =" in line]
            for line in lines:
                topology_lst = re.findall(TOPOLOGY, line)
                for el in topology_lst:
                    nodeSet = set(re.findall(NODE_NAME_COUNTER, el))
                    result = result.union(nodeSet)

            topology_str = ",".join(sorted(result))
            # filtering support e.g. --topology cont, --topology controller:3
            if kwargs['topology'].value and len(
                    list(filter(lambda x: len(
                        [el for el in kwargs['topology'].value
                         if el in x]) > 0,
                                result))) == 0:
                return None

        return topology_str

    def _get_ip_version(self, path, **kwargs):
        """
        extract ip_version from the JJB xml file and
        represent it in the form of string, e.g
           4 or 6

        Note: this function is used to support filtering
            e.g. --ip_version 4
        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: ip version string
        """
        ip_version_str = ""
        if "ip_version" in kwargs:
            in_mem_file = parse_xml(path)
            result = set([])

            lines = [line.rstrip() for line in in_mem_file if
                     "--network-protocol" in line]
            for line in lines:
                ip_version_lst = re.findall(IP_VERSION, line)
                for el in ip_version_lst:
                    nodeSet = set(re.findall(IP_VERSION_NUMBER, el))
                    result = result.union(nodeSet)
            ip_version_str = ",".join(result)
            # filtering support e.g. --ip-version 4
            if kwargs['ip_version'].value and len(
                    list(filter(lambda x: len(
                        [el for el in str(kwargs['ip_version'].value) if
                         el in x]) > 0,
                                result))) == 0:
                return None
        return ip_version_str

    def _get_release(self, path, **kwargs):
        """
        extract release from the JJB xml file and
        represent it in the form of string, e.g
           17.0 or 16.2

        Note: this function is used to support filtering
            e.g. --release 17.0
        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: release string
                 None if filtered out
        """
        release_str = ""
        if "release" in kwargs:
            in_mem_file = parse_xml(path)
            result = set([])

            lines = [line.rstrip() for line in in_mem_file if
                     "rhos" in line or "send_results_to_umb" in line]
            for line in lines:
                release_lst = re.findall(RELEASE, line)
                for el in release_lst:
                    releases = set(re.findall(RELEASE_NUMBER, el))
                    result = result.union(releases)
                # avoid outputting 10.0 and 10 as "10.0,10"
                if len(result) > 0:
                    break
            release_str = ",".join(result)
            # filtering support e.g. --release 18
            if kwargs['release'].value:
                if not args_are_in_list(kwargs['release'].value, result):
                    return None
        return release_str

    def _get_cinder_backend(self, path, **kwargs):
        """
        extract cinder_backend from the JJB xml file and
        represent it in the form of string, e.g
           swift or ceph

        Note: this function is used to support filtering
            e.g. --cinder-backend swift
        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: cinder_backend string
                 None if filtered out
        """
        cinder_backends_str = ""
        if "cinder_backend" in kwargs:
            in_mem_file = parse_xml(path)
            result = set([])

            lines = [line.rstrip() for line in in_mem_file]
            for line in lines:
                cinder_backend_lst = re.findall(CINDER_BACKEND, line)
                for el in cinder_backend_lst:
                    cinder_backends = set(re.findall(CINDER_BACKEND_NAME, el))
                    result = result.union(cinder_backends)

            cinder_backends_str = ",".join(result)
            # filtering support e.g. --cinder-backend swift
            if kwargs['cinder_backend'].value:
                if not args_are_in_list(kwargs['cinder_backend'].value,
                                        result):
                    return None
        return cinder_backends_str

    def _get_infra_type(self, path, **kwargs):
        """
        extract infra_type from the JJB xml file and
        represent it in the form of string, e.g
           virt or baremetal

        Note: this function is used to support filtering
            e.g. --infra_type virt
        :param path: to JJB xml file
        :param **kwargs: cibyl command line

        :return: infra type string
        """
        infra_type_str = ""
        if "infra_type" in kwargs:
            in_mem_file = parse_xml(path)
            result = set([])
            lines = [line.rstrip() for line in in_mem_file if
                     "--deployment-files" in line]
            for line in lines:
                infra_lst = re.findall(DEPLOYMENT, line)
                for el in infra_lst:
                    if "virt" in el or "composable_roles" in el:
                        result.add("virt")
                    elif "ovb" in el:
                        result.add("ovb")
                    else:
                        # assume that any deployment that does not use ovb or
                        # virt is a baremetal one
                        result.add("baremetal")
            if not result:
                # if no interesting line was found, return None
                return None
            if "ovb" in result:
                result = ["ovb"]
            elif "baremetal" in result:
                result = ["baremetal"]
            else:
                result = ["virt"]
            infra_type_str = ",".join(result)
            # filtering support e.g. --infra-type ovb
            if kwargs['infra_type'].value:
                if not args_are_in_list(kwargs['infra_type'].value, result):
                    return None
        return infra_type_str

    @speed_index({'base': 3, 'cinder_backend': 1})
    def get_deployment(self, **kwargs):
        """
        extract different aspects of deployment information
        for jobs dictionary generated by calling to  self.get_jobs_from_repo

        some aspects (e.g. topology) facilitate additional filtering
        of the jobs.

        :param **kwargs: cibyl command line

        :return: AttributeDictValue of the resulting (possibly filtered) job
                 list along with the deployment information.
        """
        filterted_out = []
        jobs = {}
        for repo in self.repos:
            # filter according to jobs parameter if specified by kwargs
            jobs.update(
                self.get_jobs_from_repo(repo, **kwargs))

        for job_name in jobs:
            path = self._xml_files[job_name]

            # ------------------------------                  topology
            topology = self._get_topology(path, **kwargs)

            # compute what is filtered out according to topology filter
            if topology is None and kwargs['topology'].value is not None:
                filterted_out += [job_name]
                continue
            # ------------------------------                  ip version
            ipv = self._get_ip_version(path, **kwargs)

            # compute what is filtered out according to ip version filter
            if ipv is None and kwargs['ip_version'].value is not None:
                filterted_out += [job_name]
                continue

            # ------------------------------                  release
            release = self._get_release(path, **kwargs)
            # compute what is filtered out according to release filter
            if release is None and kwargs['release'].value is not None:
                filterted_out += [job_name]
                continue

            # ------------------------------            cinder_backend
            cinder_backend = self._get_cinder_backend(path, **kwargs)
            # compute what is filtered out according to cinder_backend
            if cinder_backend is None and \
                    kwargs['cinder_backend'].value is not None:
                filterted_out += [job_name]
                continue

            infra_type = self._get_infra_type(path, **kwargs)
            if infra_type is None and kwargs['infra_type'].value is not None:
                filterted_out += [job_name]
                continue

            network = Network(ip_version=ipv,
                              ml2_driver="",
                              network_backend="",
                              dvr="",
                              tls_everywhere="",
                              security_group="")

            storage = Storage(cinder_backend=cinder_backend)

            deployment = Deployment(release=release,
                                    infra_type=infra_type,
                                    nodes=self._get_nodes(path, **kwargs),
                                    services={},
                                    topology=topology,
                                    network=network,
                                    storage=storage,
                                    ironic="",
                                    test_collection="",
                                    overcloud_templates="",
                                    stages="")

            jobs[job_name].add_deployment(deployment)

        # filter out jobs
        for el in filterted_out:
            del jobs[el]

        return AttributeDictValue("jobs", attr_type=Job, value=jobs)
