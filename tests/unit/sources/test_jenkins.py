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
# pylint: disable=no-member
import json
from unittest import TestCase
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch

import yaml

from cibyl.cli.argument import Argument
from cibyl.exceptions.jenkins import JenkinsError
from cibyl.plugins import extend_models
from cibyl.plugins.openstack.node import Node
from cibyl.sources.jenkins import (Jenkins, filter_builds, filter_jobs,
                                   safe_request)


def get_yaml_from_topology_string(topology):
    """Transform a topology string into a dictionary of the same format used in
    the infrared provision.yml file.

    :param topology: Topology string in the format node: amount
    :type topology: str

    :returns: yaml representation of a provision.yml file
    :rtype: str
    """
    provision = {'provision': {'topology': {}}}
    if not topology:
        return yaml.dump(provision)
    topology_dict = {}
    for component in topology.split(","):
        name, amount = component.split(":")
        topology_dict[name+".yml"] = int(amount)
    provision['provision']['topology']['nodes'] = topology_dict
    return yaml.dump(provision)


def get_yaml_overcloud(ip, release, storage_backend, network_backend, dvr,
                       tls_everywhere, infra_type):
    """Provide a yaml representation for the paremeters obtained from an
    infrared overcloud-install.yml file.

    :param ip: Ip version used
    :type ip: str
    :param release: Openstack version used
    :type release: str
    :param storage_backend: Storage backend used
    :type storage_backend: str
    :param network_backend: Network backend used
    :type network_backend: str
    :param dvr: Whether dvr is used
    :type dvr: bool
    :param tls_everywhere: Whether tls_everywhere is used
    :type tls_everywhere: bool

    :returns: yaml representation of a overcloud-install.yml file
    :rtype: str
    """
    if ip and ip != "unknown":
        ip = f"ipv{ip}"
    overcloud = {"version": release, }
    overcloud["deployment"] = {"files": infra_type}
    if storage_backend:
        storage = {"backend": storage_backend}
        overcloud["storage"] = storage
    network = {"backend": network_backend, "protocol": ip, "dvr": dvr}
    overcloud["network"] = network
    if tls_everywhere != "":
        tls = {"everywhere": tls_everywhere}
        overcloud["tls"] = tls
    return yaml.dump({"install": overcloud})


class TestSafeRequestJenkinsError(TestCase):
    """Tests for :func:`safe_request`."""

    def test_wraps_errors_jenkins_error(self):
        """Tests that errors coming out of the Jenkins API call
        are wrapped around the JenkinsError type.
        """

        @safe_request
        def request_test():
            raise Exception

        self.assertRaises(JenkinsError, request_test)

    def test_returns_result_when_no_error(self):
        """Tests that the call's output is returned when everything goes right.
        """
        result = {'some_key': 'some_value'}

        @safe_request
        def request_test():
            return result

        self.assertEqual(result, request_test())


class TestJenkinsSource(TestCase):
    """Tests for :class:`Jenkins`."""

    def setUp(self):
        self.jenkins = Jenkins("url", "user", "token")
        # call opentstack plugin to ensure that get_deployment tests can always
        # run
        extend_models("openstack")

    # pylint: disable=protected-access
    def test_with_all_args(self):
        """Checks that the object is built correctly when all arguments are
        provided.
        """
        url = 'url/to/jenkins/'
        username = 'user'
        cert = 'path/to/cert.pem'
        token = 'token'

        jenkins = Jenkins(url, username, token, cert)

        self.assertEqual(cert, jenkins.cert)

    def test_with_no_cert(self):
        """Checks that object is built correctly when the certificate is not
        provided.
        """
        url = 'url/to/jenkins/'
        username = 'user'
        cert = None
        token = 'token'

        jenkins = Jenkins(url, username, token, cert)

        self.assertIsNone(jenkins.cert)

    def test_get_jobs_all(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_jobs` is
            correct.
        """
        self.jenkins.send_request = Mock(return_value={"jobs": []})
        jobs_arg = Mock()
        jobs_arg.value = []

        jobs = self.jenkins.get_jobs(jobs=jobs_arg)
        self.jenkins.send_request.assert_called_with(
                                self.jenkins.jobs_query)
        self.assertEqual(len(jobs), 0)

    def test_get_jobs(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_jobs` is
            correct.
        """
        response = {"jobs": [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1'},
                    {'_class': 'org..job.WorkflowRun', 'name': "job2",
                     'url': 'url2'},
                    {'_class': 'folder', 'name': 'ansible-empty'}]}
        self.jenkins.send_request = Mock(return_value=response)
        jobs_arg = Mock()
        jobs_arg.value = ["ansible"]

        jobs = self.jenkins.get_jobs(jobs=jobs_arg)
        self.assertEqual(len(jobs), 1)
        self.assertTrue("ansible" in jobs)
        self.assertEqual(jobs["ansible"].name.value, "ansible")
        self.assertEqual(jobs["ansible"].url.value, "url1")

    def test_get_builds(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_builds` is
            correct.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1'}]}
        builds = {'_class': '_empty',
                  'allBuilds': [{'number': 1, 'result': "SUCCESS"},
                                {'number': 2, 'result': "FAILURE"}]}
        self.jenkins.send_request = Mock(side_effect=[response, builds])

        jobs = self.jenkins.get_builds()
        self.assertEqual(len(jobs), 1)
        job = jobs["ansible"]
        self.assertEqual(job.name.value, "ansible")
        self.assertEqual(job.url.value, "url1")
        builds_found = job.builds.value
        self.assertEqual(len(builds_found), 2)
        self.assertEqual(builds_found["1"].build_id.value, "1")
        self.assertEqual(builds_found["1"].status.value, "SUCCESS")
        self.assertEqual(builds_found["2"].build_id.value, "2")
        self.assertEqual(builds_found["2"].status.value, "FAILURE")

    def test_get_last_build(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_last_build`
        is correct.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1',
                              'lastBuild': {'number': 1, 'result': "SUCCESS"}
                              }]}
        self.jenkins.send_request = Mock(side_effect=[response])

        jobs = self.jenkins.get_last_build()
        self.assertEqual(len(jobs), 1)
        job = jobs["ansible"]
        self.assertEqual(job.name.value, "ansible")
        self.assertEqual(job.url.value, "url1")
        self.assertEqual(len(job.builds.value), 1)
        build = job.builds.value["1"]
        self.assertEqual(build.build_id.value, "1")
        self.assertEqual(build.status.value, "SUCCESS")

    def test_get_last_build_from_get_builds(self):
        """
        Test that get_last_build is called when calling get_builds with
        --last-build option.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1',
                              'lastBuild': {'number': 1, 'result': "SUCCESS"}
                              }]}
        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = []

        jobs = self.jenkins.get_builds(last_build=arg)
        self.assertEqual(len(jobs), 1)
        job = jobs["ansible"]
        self.assertEqual(job.name.value, "ansible")
        self.assertEqual(job.url.value, "url1")
        self.assertEqual(len(job.builds.value), 1)
        build = job.builds.value["1"]
        self.assertEqual(build.build_id.value, "1")
        self.assertEqual(build.status.value, "SUCCESS")

    def test_get_last_build_job_no_builds(self):
        """Test that get_last_build handles properly a job has no builds."""

        response = {'jobs': [{'_class': 'org.job.WorkflowJob',
                              'name': 'ansible-nfv-branch', 'url': 'url',
                              'lastBuild': None},
                             {'_class': 'folder'}]}

        self.jenkins.send_request = Mock(side_effect=[response])

        jobs = self.jenkins.get_last_build()
        self.assertEqual(len(jobs), 1)
        job = jobs["ansible-nfv-branch"]
        self.assertEqual(job.name.value, "ansible-nfv-branch")
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)

    def test_get_tests(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_tests` is
            correct.
        """

        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': 'ansible', 'url': 'url1'}]}

        builds = {'_class': '_empty',
                  'allBuilds': [{'number': 1, 'result': 'SUCCESS'},
                                {'number': 2, 'result': 'SUCCESS'}]}

        tests = {'_class': '_empty',
                 'suites': [
                    {'cases': [
                        {'className': '', 'name': 'setUpClass (class1)'},
                        {'className': 'class1', 'duration': 1,
                         'name': 'test1', 'status': 'PASSED'},
                        {'className': 'class2', 'duration': 0,
                         'name': 'test2', 'status': 'SKIPPED'},
                        {'className': 'class2', 'duration': 2.4,
                         'name': 'test3', 'status': 'FAILED'}]}]}

        # Mock the --builds command line argument
        build_kwargs = MagicMock()
        type(build_kwargs).value = PropertyMock(return_value=['1'])

        self.jenkins.send_request = Mock(side_effect=[response, builds, tests])

        jobs = self.jenkins.get_tests(builds=build_kwargs)
        self.assertEqual(len(jobs), 1)
        job = jobs['ansible']
        self.assertEqual(job.name.value, 'ansible')
        self.assertEqual(job.url.value, 'url1')

        builds_found = job.builds.value
        self.assertEqual(len(builds_found), 1)
        self.assertEqual(builds_found['1'].build_id.value, '1')
        self.assertEqual(builds_found['1'].status.value, 'SUCCESS')

        tests_found = job.builds.value['1'].tests
        self.assertEqual(len(tests_found), 3)
        self.assertEqual(tests_found['test1'].result.value, 'PASSED')
        self.assertEqual(tests_found['test1'].class_name.value, 'class1')
        self.assertEqual(tests_found['test1'].duration.value, 1000)
        self.assertEqual(tests_found['test2'].result.value, 'SKIPPED')
        self.assertEqual(tests_found['test2'].class_name.value, 'class2')
        self.assertEqual(tests_found['test2'].duration.value, 0)
        self.assertEqual(tests_found['test3'].result.value, 'FAILED')
        self.assertEqual(tests_found['test3'].class_name.value, 'class2')
        self.assertEqual(tests_found['test3'].duration.value, 2400)

    def test_get_tests_no_completed_build(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_tests` is
            correct when there is no completed build.
        """

        response = {'jobs': [{'_class': 'org.job.WorkflowRun',
                              'name': 'ansible', 'url': 'url1'}]}

        builds = {'_class': '_empty', 'allBuilds': []}

        # Mock the --builds command line argument
        build_kwargs = MagicMock()
        type(build_kwargs).value = PropertyMock(return_value=[])

        self.jenkins.send_request = Mock(side_effect=[response, builds])

        jobs = self.jenkins.get_tests(builds=build_kwargs)
        self.assertEqual(len(jobs), 1)
        builds_found = jobs['ansible'].builds.value
        self.assertEqual(len(builds_found), 0)

    def test_get_tests_for_specific_build(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_tests` is
            correct when a specific build is set.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': 'ansible', 'url': 'url1'}]}
        builds = {'_class': '_empty',
                  'allBuilds': [{'number': 1, 'result': 'SUCCESS'},
                                {'number': 2, 'result': 'SUCCESS'}]}
        tests = {'_class': '_empty',
                 'suites': [
                    {'cases': [
                        {'className': 'class1', 'duration': 1.1,
                         'name': 'test1', 'status': 'PASSED'},
                        {'className': 'class2', 'duration': 7.2,
                         'name': 'test2', 'status': 'PASSED'}]}]}

        self.jenkins.send_request = Mock(side_effect=[response, builds, tests])

        # Mock the --build command line argument
        build_kwargs = MagicMock()
        type(build_kwargs).value = PropertyMock(return_value=['1'])

        jobs = self.jenkins.get_tests(builds=build_kwargs)
        self.assertEqual(len(jobs), 1)
        job = jobs['ansible']
        self.assertEqual(job.name.value, 'ansible')
        self.assertEqual(job.url.value, 'url1')

        builds_found = job.builds.value
        self.assertEqual(len(builds_found), 1)
        self.assertEqual(builds_found['1'].build_id.value, '1')
        self.assertEqual(builds_found['1'].status.value, 'SUCCESS')

        tests_found = job.builds.value['1'].tests
        self.assertEqual(len(tests_found), 2)
        self.assertEqual(tests_found['test1'].result.value, 'PASSED')
        self.assertEqual(tests_found['test1'].class_name.value, 'class1')
        self.assertEqual(tests_found['test1'].duration.value, 1100)
        self.assertEqual(tests_found['test2'].result.value, 'PASSED')
        self.assertEqual(tests_found['test2'].class_name.value, 'class2')
        self.assertEqual(tests_found['test2'].duration.value, 7200)

    def test_get_tests_multiple_jobs(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_tests` is
            correct when multiple jobs match.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': 'ansible', 'url': 'url1',
                              'lastBuild': {'number': 1, 'result': 'SUCCESS'}},
                             {'_class': 'org..job.WorkflowRun',
                              'name': 'ansible-two', 'url': 'url2',
                              'lastBuild': {'number': 27,
                                            'result': 'SUCCESS'}}]}
        tests1 = {'_class': '_empty',
                  'suites': [
                    {'cases': [
                        {'className': 'class1', 'duration': 1,
                         'name': 'test1', 'status': 'PASSED'},
                        {'className': 'class2', 'duration': 0,
                         'name': 'test2', 'status': 'SKIPPED'},
                        {'className': 'class2', 'duration': 2.4,
                         'name': 'test3', 'status': 'FAILED'}]}]}
        tests27 = {'_class': '_empty',
                   'suites': [
                    {'cases': [
                        {'className': 'class271', 'duration': 11.1,
                         'name': 'test1', 'status': 'PASSED'},
                        {'className': 'class272', 'duration': 5.1,
                         'name': 'test2', 'status': 'PASSED'}]}]}

        self.jenkins.send_request = Mock(side_effect=[response, tests1,
                                                      tests27])

        # Mock the --build command line argument
        build_kwargs = MagicMock()
        type(build_kwargs).value = PropertyMock(return_value=[])

        jobs = self.jenkins.get_tests(last_build=build_kwargs)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs['ansible'].name.value, 'ansible')
        self.assertEqual(jobs['ansible'].url.value, 'url1')
        self.assertEqual(jobs['ansible-two'].name.value, 'ansible-two')
        self.assertEqual(jobs['ansible-two'].url.value, 'url2')

        builds_found1 = jobs['ansible'].builds.value
        self.assertEqual(len(builds_found1), 1)
        self.assertEqual(builds_found1['1'].build_id.value, '1')
        self.assertEqual(builds_found1['1'].status.value, 'SUCCESS')
        builds_found2 = jobs['ansible-two'].builds.value
        self.assertEqual(len(builds_found2), 1)
        self.assertEqual(builds_found2['27'].build_id.value, '27')
        self.assertEqual(builds_found2['27'].status.value, 'SUCCESS')

        tests_found1 = jobs['ansible'].builds.value['1'].tests
        self.assertEqual(len(tests_found1), 3)
        self.assertEqual(tests_found1['test1'].result.value, 'PASSED')
        self.assertEqual(tests_found1['test1'].class_name.value, 'class1')
        self.assertEqual(tests_found1['test1'].duration.value, 1000)
        self.assertEqual(tests_found1['test2'].result.value, 'SKIPPED')
        self.assertEqual(tests_found1['test2'].class_name.value, 'class2')
        self.assertEqual(tests_found1['test2'].duration.value, 0)
        self.assertEqual(tests_found1['test3'].result.value, 'FAILED')
        self.assertEqual(tests_found1['test3'].class_name.value, 'class2')
        self.assertEqual(tests_found1['test3'].duration.value, 2400)
        tests_found27 = jobs['ansible-two'].builds.value['27'].tests
        self.assertEqual(len(tests_found27), 2)
        self.assertEqual(tests_found27['test1'].result.value, 'PASSED')
        self.assertEqual(tests_found27['test1'].class_name.value, 'class271')
        self.assertEqual(tests_found27['test1'].duration.value, 11100)
        self.assertEqual(tests_found27['test2'].result.value, 'PASSED')
        self.assertEqual(tests_found27['test2'].class_name.value, 'class272')
        self.assertEqual(tests_found27['test2'].duration.value, 5100)

    def test_get_tests_child(self):
        """
            Tests that the internal logic from :meth:`Jenkins.get_tests` is
            correct when tests are located inside `childReports`.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': 'ansible', 'url': 'url1',
                              'lastBuild': {
                                  'number': 1, 'result': 'UNSTABLE',
                                  'duration': 3.5
                              }}]}
        tests = {'_class': '_empty',
                 'childReports': [
                     {
                         'result': {
                             'suites': [
                                {
                                    'cases': [
                                        {'className': 'class1',
                                         'duration': 1, 'name': 'test1',
                                         'status': 'PASSED'},
                                        {'className': 'class2',
                                         'duration': 0, 'name': 'test2',
                                         'status': 'SKIPPED'},
                                        {'className': 'class2',
                                         'duration': 2.4, 'name': 'test3',
                                         'status': 'FAILED'},
                                        {'className': 'class2',
                                         'duration': 120.0, 'name': 'test4',
                                         'status': 'REGRESSION'}
                                    ]
                                }
                             ]
                         }
                     }
                 ]}

        self.jenkins.send_request = Mock(side_effect=[response, tests])

        # Mock the --build command line argument
        build_kwargs = MagicMock()
        type(build_kwargs).value = PropertyMock(return_value=[])

        jobs = self.jenkins.get_tests(last_build=build_kwargs)
        self.assertEqual(len(jobs), 1)
        job = jobs['ansible']
        self.assertEqual(job.name.value, 'ansible')
        self.assertEqual(job.url.value, 'url1')

        builds_found = job.builds.value
        self.assertEqual(len(builds_found), 1)
        self.assertEqual(builds_found['1'].build_id.value, '1')
        self.assertEqual(builds_found['1'].status.value, 'UNSTABLE')

        tests_found = job.builds.value['1'].tests
        self.assertEqual(len(tests_found), 4)
        self.assertEqual(tests_found['test1'].result.value, 'PASSED')
        self.assertEqual(tests_found['test1'].class_name.value, 'class1')
        self.assertEqual(tests_found['test1'].duration.value, 1000)
        self.assertEqual(tests_found['test2'].result.value, 'SKIPPED')
        self.assertEqual(tests_found['test2'].class_name.value, 'class2')
        self.assertEqual(tests_found['test2'].duration.value, 0)
        self.assertEqual(tests_found['test3'].result.value, 'FAILED')
        self.assertEqual(tests_found['test3'].class_name.value, 'class2')
        self.assertEqual(tests_found['test3'].duration.value, 2400)
        self.assertEqual(tests_found['test4'].result.value, 'REGRESSION')
        self.assertEqual(tests_found['test4'].class_name.value, 'class2')
        self.assertEqual(tests_found['test4'].duration.value, 120000)

    @patch("requests.get")
    def test_send_request(self, patched_get):
        """
            Test that send_request method parses the response correctly.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1'}]}
        patched_get.return_value = Mock(text=json.dumps(response))
        self.assertEqual(response, self.jenkins.send_request("test"))
        patched_get.assert_called_with(
            f'://{self.jenkins.username}:{self.jenkins.token}@/api/jsontest',
            verify=self.jenkins.cert, timeout=None
        )

    @patch("requests.get")
    def test_send_request_with_item(self, patched_get):
        """
            Test that send_request method parses the response correctly.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1'}]}
        patched_get.return_value = Mock(text=json.dumps(response))
        self.assertEqual(response, self.jenkins.send_request("test",
                                                             item="item"))
        api_part = "item/api/jsontest"
        patched_get.assert_called_with(
            f'://{self.jenkins.username}:{self.jenkins.token}@/{api_part}',
            verify=self.jenkins.cert, timeout=None
        )

    @patch("requests.get")
    def test_send_request_with_raw_response(self, patched_get):
        """
            Test that send_request returns the raw response.
        """
        response = {'jobs': [{'_class': 'org..job.WorkflowRun',
                              'name': "ansible", 'url': 'url1'}]}
        response = json.dumps(response)
        patched_get.return_value = Mock(text=response)
        self.assertEqual(response,
                         self.jenkins.send_request("test", raw_response=True))

        api_part = "api/jsontest"
        patched_get.assert_called_with(
            f'://{self.jenkins.username}:{self.jenkins.token}@/{api_part}',
            verify=self.jenkins.cert, timeout=None
        )

    def test_get_deployment(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins.
        """
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["compute:2,controller:1", "compute:1,controller:2", ""]
        nodes = [["compute-0", "compute-1", "controller-0"],
                 ["compute-0", "controller-0", "controller-1"]]

        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = []

        jobs = self.jenkins.get_deployment(ip_version=arg)
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology, node_list in zip(job_names,
                                                              ip_versions,
                                                              releases,
                                                              topologies,
                                                              nodes):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)
            for node_name, node_expected in zip(deployment.nodes, node_list):
                node = deployment.nodes[node_name]
                self.assertEqual(node.name.value, node_expected)
                self.assertEqual(node.role.value, node_expected.split("-")[0])

    def test_get_deployment_many_jobs(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins.
        """
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["compute:2,controller:1", "compute:1,controller:2", ""]

        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})
        for _ in range(12):
            # ensure that there are more than 12 jobs and jenkins source gets
            # deployment information from job name
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': 'test_job', 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = []

        jobs = self.jenkins.get_deployment(ip_version=arg)
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology in zip(job_names, ip_versions,
                                                   releases, topologies):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)

    def test_get_deployment_artifacts_fallback(self):
        """ Test that get_deployment falls back to reading job_names after
        failing to find artifacts.
        """
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["compute:2,controller:1", "compute:1,controller:2", ""]

        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {}})
        # each job triggers 2 artifacts requests, if both fail, fallback to
        # search the name
        artifacts_fail = [JenkinsError for _ in range(3*len(job_names))]
        self.jenkins.send_request = Mock(side_effect=[response]+artifacts_fail)
        self.jenkins.add_job_info_from_name = Mock(
                side_effect=self.jenkins.add_job_info_from_name)

        jobs = self.jenkins.get_deployment()
        self.jenkins.add_job_info_from_name.assert_called()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology in zip(job_names, ip_versions,
                                                   releases, topologies):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)

    def test_get_deployment_artifacts_fallback_no_logs_link(self):
        """ Test that get_deployment falls back to reading job_names after
        failing to find artifacts.
        """
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["compute:2,controller:1", "compute:1,controller:2", ""]

        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {'description':
                                                            "link"}})
        # each job triggers 2 artifacts requests, if both fail, fallback to
        # search the name
        artifacts_fail = [JenkinsError for _ in range(3*len(job_names))]
        self.jenkins.send_request = Mock(side_effect=[response]+artifacts_fail)
        self.jenkins.add_job_info_from_name = Mock(
                side_effect=self.jenkins.add_job_info_from_name)

        jobs = self.jenkins.get_deployment()
        self.jenkins.add_job_info_from_name.assert_called()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology in zip(job_names, ip_versions,
                                                   releases, topologies):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)

    def test_get_deployment_artifacts(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins using artifacts.
        """
        job_names = ['test_17.3_ipv4_job', 'test_16_ipv6_job', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["compute:2,controller:3", "compute:1,controller:2",
                      "compute:2,controller:2"]

        response = {'jobs': [{'_class': 'folder'}]}
        logs_url = 'href="link">Browse logs'
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {'description':
                                                            logs_url}})
        services = """
tripleo_heat_api_cron.service loaded    active     running
tripleo_heat_engine.service loaded    active     running
tripleo_ironic_api.service loaded    active     running
tripleo_ironic_conductor.service loaded    active     running
        """
        # ensure that all deployment properties are found in the artifact so
        # that it does not fallback to reading values from job name
        artifacts = [
                get_yaml_from_topology_string(topologies[0]),
                get_yaml_overcloud(ip_versions[0], releases[0],
                                   "ceph", "geneve", False,
                                   False, "path/to/ovb")]
        # one call to get_packages_node and get_containers_node per node
        artifacts.extend([JenkinsError()]*(5*2))
        artifacts.extend([services])
        artifacts.extend([
                get_yaml_from_topology_string(topologies[1]),
                get_yaml_overcloud(ip_versions[1], releases[1],
                                   "ceph", "geneve", False,
                                   False, "path/to/ovb")])
        # one call to get_packages_node and get_containers_node per node
        artifacts.extend([JenkinsError()]*(3*2))
        artifacts.extend([services])

        artifacts.extend([
                get_yaml_from_topology_string(topologies[2]),
                get_yaml_overcloud(ip_versions[2], releases[2],
                                   "ceph", "geneve", False,
                                   False, "path/to/ovb")])
        # one call to get_packages_node and get_containers_node per node
        artifacts.extend([JenkinsError()]*(4*2))
        artifacts.extend([services])

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        jobs = self.jenkins.get_deployment()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology in zip(job_names, ip_versions,
                                                   releases, topologies):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)
            self.assertEqual(deployment.storage_backend.value, "ceph")
            self.assertEqual(deployment.network_backend.value, "geneve")
            self.assertEqual(deployment.dvr.value, "False")
            self.assertEqual(deployment.tls_everywhere.value, "False")
            self.assertEqual(deployment.infra_type.value, "ovb")
            for component in topology.split(","):
                role, amount = component.split(":")
                for i in range(int(amount)):
                    node_name = role+f"-{i}"
                    node = Node(node_name, role)
                    node_found = deployment.nodes[node_name]
                    self.assertEqual(node_found.name, node.name)
                    self.assertEqual(node_found.role, node.role)
            services = deployment.services
            self.assertTrue("tripleo_heat_api_cron" in services.value)
            self.assertTrue("tripleo_heat_engine" in services.value)
            self.assertTrue("tripleo_ironic_api" in services.value)
            self.assertTrue("tripleo_ironic_conductor" in services.value)

    def test_get_deployment_artifacts_missing_property(self):
        """ Test that get_deployment detects missing information from
        jenkins artifacts.
        """
        job_names = ['test_17.3_ipv4_job', 'test_16_ipv6_job', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        topologies = ["", "", ""]
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': {}})
        artifacts = [
           f"bla\nJP_TOPOLOGY='{topologies[0]}'\nPRODUCT_VERSION=17.3",
           f"bla\nJP_TOPOLOGY='{topologies[1]}'\nPRODUCT_VERSION=16",
           f"bla\nJP_TOPOLOGY='{topologies[2]}'\nPRODUCT_VERSION=",
            ]

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        jobs = self.jenkins.get_deployment()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology in zip(job_names, ip_versions,
                                                   releases, topologies):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)

    def test_get_deployment_filter_ipv(self):
        """Test that get_deployment filters by ip_version."""
        job_names = ['test_17.3_ipv4_job', 'test_16_ipv6_job', 'test_job']

        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = ["4"]

        jobs = self.jenkins.get_deployment(ip_version=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, "")

    def test_get_deployment_filter_topology(self):
        """Test that get_deployment filters by topology."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = [topology_value]

        jobs = self.jenkins.get_deployment(topology=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)

    def test_get_deployment_filter_release(self):
        """Test that get_deployment filters by release."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        response = {'jobs': [{'_class': 'folder'}]}
        topology_value = "compute:2,controller:1"
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = ["17.3"]

        jobs = self.jenkins.get_deployment(release=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)

    def test_get_deployment_filter_topology_ip_version(self):
        """Test that get_deployment filters by topology and ip version."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = [topology_value]
        arg_ip = Mock()
        arg_ip.value = ["6"]

        jobs = self.jenkins.get_deployment(topology=arg, ip_version=arg_ip)
        self.assertEqual(len(jobs), 0)

    def test_get_deployment_filter_network_backend(self):
        """Test that get_deployment filters by network backend."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont_geneve',
                     'test_16_ipv6_job_1comp_2cont_vxlan', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = ["geneve"]

        jobs = self.jenkins.get_deployment(network_backend=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont_geneve'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)
        self.assertEqual(deployment.network_backend.value, "geneve")

    def test_get_deployment_filter_storage_backend(self):
        """Test that get_deployment filters by storage backend."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont_geneve_swift',
                     'test_16_ipv6_job_1comp_2cont_lvm', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Mock()
        arg.value = ["swift"]

        jobs = self.jenkins.get_deployment(storage_backend=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont_geneve_swift'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)
        self.assertEqual(deployment.storage_backend.value, "swift")
        self.assertEqual(deployment.network_backend.value, "geneve")

    def test_get_deployment_filter_controller(self):
        """Test that get_deployment filters by controller."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Argument("compute", arg_type=str, description="", value=["<2"],
                       ranged=True)

        jobs = self.jenkins.get_deployment(controllers=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)

    def test_get_deployment_filter_computes(self):
        """Test that get_deployment filters by computes."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Argument("compute", arg_type=str, description="", value=["2"],
                       ranged=True)

        jobs = self.jenkins.get_deployment(computes=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)

    def test_get_deployment_filter_infra_type(self):
        """Test that get_deployment filters by infra type."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont_ovb',
                     'test_16_ipv6_job_1comp_2cont_virt', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Argument("infra_type", arg_type=str, description="",
                       value=["ovb"])

        jobs = self.jenkins.get_deployment(infra_type=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont_ovb'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)
        self.assertEqual(deployment.infra_type.value, "ovb")

    def test_get_deployment_filter_dvr(self):
        """Test that get_deployment filters by dvr."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont_no_dvr',
                     'test_16_ipv6_job_1comp_2cont_dvr', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Argument("dvr", arg_type=str, description="",
                       value=["False"])

        jobs = self.jenkins.get_deployment(dvr=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont_no_dvr'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)
        self.assertEqual(deployment.dvr.value, "False")

    def test_get_deployment_artifacts_dvr(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins using artifacts.
        """
        job_names = ['test_17.3_ipv4_job', 'test_16_ipv6_job', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        dvr_status = ['True', 'True', '']
        topologies = ["compute:2,controller:3", "compute:1,controller:2",
                      "compute:2,controller:2"]

        response = {'jobs': [{'_class': 'folder'}]}
        logs_url = 'href="link">Browse logs'
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {'description':
                                                            logs_url}})
        artifacts = [
                get_yaml_from_topology_string(topologies[0]),
                get_yaml_overcloud(ip_versions[0], releases[0],
                                   "ceph", "geneve", dvr_status[0], False, "")]
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(5*2+1))
        artifacts.extend([
                get_yaml_from_topology_string(topologies[1]),
                get_yaml_overcloud(ip_versions[1], releases[1],
                                   "ceph", "geneve", dvr_status[1],
                                   False, "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(3*2+1))

        artifacts.extend([
                get_yaml_from_topology_string(topologies[2]),
                get_yaml_overcloud(ip_versions[2], releases[2],
                                   "ceph", "geneve", dvr_status[2],
                                   False, "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(4*2+1))

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        jobs = self.jenkins.get_deployment()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology, dvr in zip(job_names, ip_versions,
                                                        releases, topologies,
                                                        dvr_status):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)
            self.assertEqual(deployment.dvr.value, dvr)

    def test_get_deployment_filter_tls(self):
        """Test that get_deployment filters by tls_everywhere."""
        job_names = ['test_17.3_ipv4_job_2comp_1cont_tls',
                     'test_16_ipv6_job_1comp_2cont', 'test_job']
        topology_value = "compute:2,controller:1"
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastBuild': None})

        self.jenkins.send_request = Mock(side_effect=[response])
        arg = Argument("tls-everywhere", arg_type=str, description="",
                       value=["True"])

        jobs = self.jenkins.get_deployment(tls_everywhere=arg)
        self.assertEqual(len(jobs), 1)
        job_name = 'test_17.3_ipv4_job_2comp_1cont_tls'
        job = jobs[job_name]
        deployment = job.deployment.value
        self.assertEqual(job.name.value, job_name)
        self.assertEqual(job.url.value, "url")
        self.assertEqual(len(job.builds.value), 0)
        self.assertEqual(deployment.release.value, "17.3")
        self.assertEqual(deployment.ip_version.value, "4")
        self.assertEqual(deployment.topology.value, topology_value)
        self.assertEqual(deployment.tls_everywhere.value, "True")

    def test_get_deployment_artifacts_tls(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins using artifacts.
        """
        job_names = ['test_17.3_ipv4_job', 'test_16_ipv6_job', 'test_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        tls_status = ['True', 'True', '']
        topologies = ["compute:2,controller:3", "compute:1,controller:2",
                      "compute:2,controller:2"]

        logs_url = 'href="link">Browse logs'
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {'description':
                                                            logs_url}})
        artifacts = [
                get_yaml_from_topology_string(topologies[0]),
                get_yaml_overcloud(ip_versions[0], releases[0],
                                   "ceph", "geneve", False, tls_status[0], "")]
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(5*2+1))
        artifacts.extend([
                get_yaml_from_topology_string(topologies[1]),
                get_yaml_overcloud(ip_versions[1], releases[1],
                                   "ceph", "geneve", False,
                                   tls_status[1], "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(3*2+1))

        artifacts.extend([
                get_yaml_from_topology_string(topologies[2]),
                get_yaml_overcloud(ip_versions[2], releases[2],
                                   "ceph", "geneve", False,
                                   tls_status[2], "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(4*2+1))

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        jobs = self.jenkins.get_deployment()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology, tls in zip(job_names, ip_versions,
                                                        releases, topologies,
                                                        tls_status):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)
            self.assertEqual(deployment.tls_everywhere.value, tls)

    def test_get_deployment_artifacts_missing_topology(self):
        """ Test that get_deployment reads properly the information obtained
        from jenkins using artifacts.
        """
        job_names = ['test_17.3_ipv4_2comp_3cont_job',
                     'test_16_ipv6_1comp_2cont_job', 'test_2comp_2cont_job']
        ip_versions = ['4', '6', 'unknown']
        releases = ['17.3', '16', '']
        tls_status = ['True', 'True', '']
        topologies = ["compute:2,controller:3", "compute:1,controller:2",
                      "compute:2,controller:2"]

        logs_url = 'href="link">Browse logs'
        response = {'jobs': [{'_class': 'folder'}]}
        for job_name in job_names:
            response['jobs'].append({'_class': 'org.job.WorkflowJob',
                                     'name': job_name, 'url': 'url',
                                     'lastCompletedBuild': {'description':
                                                            logs_url}})
        artifacts = [
                get_yaml_from_topology_string(""),
                get_yaml_overcloud(ip_versions[0], releases[0],
                                   "ceph", "geneve", False, tls_status[0], "")]
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(5*2+1))
        artifacts.extend([
                get_yaml_from_topology_string(""),
                get_yaml_overcloud(ip_versions[1], releases[1],
                                   "ceph", "geneve", False,
                                   tls_status[1], "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(3*2+1))

        artifacts.extend([
                get_yaml_from_topology_string(""),
                get_yaml_overcloud(ip_versions[2], releases[2],
                                   "ceph", "geneve", False,
                                   tls_status[2], "")])
        # one call to get_packages_node and get_containers_node per node, plus
        # one to get_services
        artifacts.extend([JenkinsError()]*(4*2+1))

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        self.jenkins.send_request = Mock(side_effect=[response]+artifacts)

        jobs = self.jenkins.get_deployment()
        self.assertEqual(len(jobs), 3)
        for job_name, ip, release, topology, tls in zip(job_names, ip_versions,
                                                        releases, topologies,
                                                        tls_status):
            job = jobs[job_name]
            deployment = job.deployment.value
            self.assertEqual(job.name.value, job_name)
            self.assertEqual(job.url.value, "url")
            self.assertEqual(len(job.builds.value), 0)
            self.assertEqual(deployment.release.value, release)
            self.assertEqual(deployment.ip_version.value, ip)
            self.assertEqual(deployment.topology.value, topology)
            self.assertEqual(deployment.tls_everywhere.value, tls)

    def test_get_packages_node(self):
        """ Test that get_packages_node reads properly the information obtained
        from jenkins using artifacts.
        """
        response = """
acl-2.2.53-1.el8.x86_64
aide-0.16-14.el8_4.1.x86_64
ansible-2.9.27-1.el8ae.noarch
ansible-pacemaker-1.0.4-2.20210623224811.666f706.el8ost.noarch
audit-3.0-0.17.20191104git1c2f876.el8.x86_64
audit-libs-3.0-0.17.20191104git1c2f876.el8.x86_64
augeas-libs-1.12.0-6.el8.x86_64
authselect-1.2.2-2.el8.x86_64
authselect-compat-1.2.2-2.el8.x86_64
authselect-libs-1.2.2-2.el8.x86_64
autofs-5.1.4-48.el8_4.1.x86_64
autogen-libopts-5.18.12-8.el8.x86_64
avahi-libs-0.7-20.el8.x86_64
basesystem-11-5.el8.noarch"""
        packages_expected = response.split("\n")

        self.jenkins.send_request = Mock(side_effect=[response])

        url = "url/node/var/log/extra/rpm-list.txt.gz"
        packages = self.jenkins.get_packages_node("node", "url", "job-name")
        self.jenkins.send_request.assert_called_with(query="", item="",
                                                     raw_response=True,
                                                     url=url)
        self.assertEqual(len(packages), len(packages_expected))
        for package, package_name in zip(packages.values(), packages_expected):
            self.assertEqual(package.name.value, package_name)

    def test_get_packages_container(self):
        """ Test that get_packages_container reads properly the information
        obtained from jenkins using artifacts.
        """
        response = """
2022-03-28T14:27:24+00 SUBDEBUG Installed: crudini-0.9-11.el8ost.1
2022-03-28T14:27:30+00 INFO --- logging initialized ---
2022-03-28T14:28:32+00 INFO warning: /etc/sudoers created as /etc/sudoers.rw
2022-03-28T14:31:28+00 SUBDEBUG Upgrade: openssl-libs-1:1.1.1g-16.el8_4
2022-03-28T14:31:28+00 SUBDEBUG Upgraded: python3-dateutil-1:2.6.1-6.el8"""

        packages_expected = ["crudini-0.9-11.el8ost.1",
                             "openssl-libs-1:1.1.1g-16.el8_4",
                             "python3-dateutil-1:2.6.1-6.el8"]

        self.jenkins.send_request = Mock(side_effect=[response])

        url = "url/container/log/dnf.rpm.log.gz"
        packages = self.jenkins.get_packages_container("container", "url",
                                                       "job-name")
        self.jenkins.send_request.assert_called_with(query="", item="",
                                                     raw_response=True,
                                                     url=url)
        self.assertEqual(len(packages), len(packages_expected))
        for package, package_name in zip(packages.values(), packages_expected):
            self.assertEqual(package.name.value, package_name)

    def test_get_packages_container_raises(self):
        """ Test that get_packages_container returns an empty dictionary after
        an error is raised by send_request."""
        self.jenkins.send_request = Mock(side_effect=JenkinsError)

        packages = self.jenkins.get_packages_container("container", "", "")
        self.assertEqual(packages, {})

    def test_get_containers_node(self):
        """ Test that get_containers_node reads properly the information
        obtained from jenkins using artifacts.
        """
        response = """
<a href="./nova_libvirt/">nova_libvirt/</a>
<a href="./nova_libvirt/">nova/</a>
<a href="./nova_migration_target/">nova_migration_target/</a>
"""

        containers_expected = ["nova_libvirt", "nova_migration_target"]

        self.jenkins.send_request = Mock(side_effect=[response, JenkinsError(),
                                                      JenkinsError])
        base_url = "url/node/var/log/extra/podman/containers"
        urls = [base_url,
                f"{base_url}/nova_libvirt/log/dnf.rpm.log.gz",
                f"{base_url}/nova_migration_target/log/dnf.rpm.log.gz"]

        containers = self.jenkins.get_containers_node("node", "url",
                                                      "job-name")
        calls = [call(item="", query="", url=url,
                      raw_response=True) for url in urls]

        self.jenkins.send_request.assert_has_calls(calls)
        self.assertEqual(len(containers), len(containers_expected))
        for container, container_name in zip(containers.values(),
                                             containers_expected):
            self.assertEqual(container.name.value, container_name)
            self.assertEqual(container.packages.value, {})


class TestFilters(TestCase):
    """Tests for filter functions in jenkins source module."""
    def test_filter_jobs(self):
        """
            Test that filter_jobs filters the jobs given the user input.
        """
        response = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}}]
        args = Mock()
        args.value = ["ans"]
        jobs_filtered = filter_jobs(response, jobs=args)
        expected = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}},
                    ]
        self.assertEqual(jobs_filtered, expected)

    def test_filter_jobs_class(self):
        """
            Test that filter_jobs filters the jobs given the job _class.
        """
        response = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'jenkins.branch.OrganizationFolder',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}},
                    {'_class': 'com.cloudbees.hudson.plugins.folder.Folder',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}},
                    {'_class': 'hudson.model.FreeStyleProject',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}}]
        jobs_filtered = filter_jobs(response)
        expected = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'hudson.model.FreeStyleProject',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}},
                    ]
        self.assertEqual(jobs_filtered, expected)

    def test_filter_jobs_job_url(self):
        """
            Test that filter_jobs filters the jobs given the user input.
        """
        response = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}}]
        jobs = Mock()
        jobs.value = ["ans2"]
        job_url = Mock()
        job_url.value = ["url3"]
        jobs_filtered = filter_jobs(response, jobs=jobs,
                                    job_url=job_url)
        expected = [{'_class': 'org..job.WorkflowRun',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}}]
        self.assertEqual(jobs_filtered, expected)

    def test_filter_job_url(self):
        """
            Test that filter_jobs filters the jobs given the user input.
        """
        response = [{'_class': 'org..job.WorkflowRun',
                     'name': "ansible", 'url': 'url1',
                     'lastBuild': {'number': 1, 'result': "SUCCESS"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}},
                    {'_class': 'org..job.WorkflowRun',
                     'name': "ans2", 'url': 'url3',
                     'lastBuild': {'number': 0, 'result': "FAILURE"}}
                    ]
        job_url = Mock()
        job_url.value = ["url2"]
        jobs_filtered = filter_jobs(response, job_url=job_url)
        expected = [{'_class': 'org..job.WorkflowRun',
                     'name': "test_jobs", 'url': 'url2',
                     'lastBuild': {'number': 2, 'result': "FAILURE"}}]
        self.assertEqual(jobs_filtered, expected)

    def test_filter_builds_builds_build_id_build_status(self):
        """Test that filter builds filters the builds given the user input."""
        response = [{'_class': 'org..job.WorkflowRun', 'number': 3,
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': 4,
                     'result': 'FAILURE'},
                    {'_class': 'org..job.WorkflowRun', 'number': 5,
                     'result': 'success'}]
        builds = Mock()
        builds.value = ["3"]
        build_status = Mock()
        build_status.value = ["success"]
        builds_filtered = filter_builds(response, builds=builds,
                                        build_status=build_status)
        expected = [{'_class': 'org..job.WorkflowRun', 'number': "3",
                     'result': 'SUCCESS'}]
        self.assertEqual(builds_filtered, expected)

    def test_filter_builds_builds_build_status(self):
        """Test that filter builds filters the builds given the user input."""
        response = [{'_class': 'org..job.WorkflowRun', 'number': 3,
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': 4,
                     'result': 'FAILURE'},
                    {'_class': 'org..job.WorkflowRun', 'number': 5,
                     'result': 'success'}]
        builds = Mock()
        builds.value = []
        build_status = Mock()
        build_status.value = ["success"]
        builds_filtered = filter_builds(response, builds=builds,
                                        build_status=build_status)
        expected = [{'_class': 'org..job.WorkflowRun', 'number': "3",
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': "5",
                     'result': 'success'}]
        self.assertEqual(builds_filtered, expected)

    def test_filter_builds_builds(self):
        """Test that filter builds filters the builds given the user input."""
        response = [{'_class': 'org..job.WorkflowRun', 'number': 3,
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': 4,
                     'result': 'FAILURE'},
                    {'_class': 'org..job.WorkflowRun', 'number': 5,
                     'result': 'success'}]
        builds = Mock()
        builds.value = ["3", "5"]
        builds_filtered = filter_builds(response, builds=builds)
        expected = [{'_class': 'org..job.WorkflowRun', 'number': "3",
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': "5",
                     'result': 'success'}]
        self.assertEqual(builds_filtered, expected)

    def test_filter_builds_build_status(self):
        """Test that filter builds filters the builds given the user input."""
        response = [{'_class': 'org..job.WorkflowRun', 'number': 3,
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': 4,
                     'result': 'FAILURE'},
                    {'_class': 'org..job.WorkflowRun', 'number': 5,
                     'result': 'success'}]
        build_status = Mock()
        build_status.value = ["success"]
        builds_filtered = filter_builds(response,
                                        build_status=build_status)
        expected = [{'_class': 'org..job.WorkflowRun', 'number': "3",
                     'result': 'SUCCESS'},
                    {'_class': 'org..job.WorkflowRun', 'number': "5",
                     'result': 'success'}]
        self.assertEqual(builds_filtered, expected)
