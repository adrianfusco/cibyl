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
from unittest import TestCase
from unittest.mock import Mock

from cibyl.sources.zuul.apis.rest import (ZuulJobRESTClient,
                                          ZuulPipelineRESTClient,
                                          ZuulProjectRESTClient,
                                          ZuulRESTClient, ZuulSession,
                                          ZuulTenantRESTClient)


class TestZuulSession(TestCase):
    """Tests for :class:`ZuulSession`.
    """

    def test_api_url(self):
        """Checks that the session correctly builds the API URL from the
        host's URL."""
        url = 'http://localhost:8080/zuul'

        session = ZuulSession(Mock(), url, None)

        self.assertEqual(f'{url}/api/', session.api)

    def test_happy_query(self):
        """Tests that the JSON from the response is returned if the query
        is successful."""
        url = 'http://localhost:8080/zuul'
        service = 'service'

        json = {
            'param_1': 'val_1',
            'param_2': 'val_2'
        }

        rest = Mock()
        rest.get = Mock()

        request = Mock()
        request.json = Mock()
        request.raise_for_status = Mock()

        rest.get.return_value = request

        request.json.return_value = json

        session = ZuulSession(rest, url, None)

        self.assertEqual(json, session.get(service))

        rest.get.assert_called_with(f'{session.api}{service}')

        request.raise_for_status.assert_called()
        request.json.assert_called()


class TestZuulJobRESTClient(TestCase):
    """Tests for :class:`ZuulJobRESTClient`.
    """

    def test_equality(self):
        """Checks '__eq__'.
        """
        job = {
            'name': 'job'
        }

        session = Mock()
        tenant = Mock()

        client = ZuulJobRESTClient(session, tenant, job)

        # Equality by type
        self.assertNotEqual(Mock(), client)

        # Equality by reference
        self.assertEqual(client, client)

        # Equality by contents
        self.assertEqual(ZuulJobRESTClient(session, tenant, job), client)

    def test_url(self):
        """Checks that the user's url for the job is properly build.
        """
        job = {
            'name': 'job_1'
        }

        session = Mock()
        session.host = 'http://localhost:8080/'

        tenant = Mock()
        tenant.name = 'tenant'

        client = ZuulJobRESTClient(session, tenant, job)

        self.assertEqual(
            'http://localhost:8080/t/tenant/job/job_1',
            client.url
        )

    def test_pipelines(self):
        """Checks call to 'pipelines' end-point.
        """
        job = {
            'name': 'job'
        }

        session = Mock()

        pipeline1 = Mock()
        pipeline1.name = 'pipeline1'
        pipeline1.jobs = Mock()

        pipeline2 = Mock()
        pipeline2.name = 'pipeline2'
        pipeline2.jobs = Mock()

        project = Mock()
        project.pipelines = Mock()
        project.pipelines.return_value = [pipeline1, pipeline2]

        tenant = Mock()
        tenant.name = 'tenant'
        tenant.projects = Mock()
        tenant.projects.return_value = [project]

        pipeline1.jobs.return_value = [ZuulJobRESTClient(session, tenant, job)]
        pipeline2.jobs.return_value = []

        client = ZuulJobRESTClient(session, tenant, job)

        self.assertEqual([pipeline1], client.pipelines())

        pipeline1.jobs.assert_called_once()
        pipeline2.jobs.assert_called_once()
        project.pipelines.assert_called_once()
        tenant.projects.assert_called_once()

    def test_builds(self):
        """Checks that the current steps are taken to get the builds
        of this job.
        """
        job = {
            'name': 'job'
        }

        builds = [
            {
                'name': 'build_1'
            },
            {
                'name': 'build_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        tenant = Mock()

        tenant.name = 'tenant'
        session.get.return_value = builds

        client = ZuulJobRESTClient(session, tenant, job)

        self.assertEqual(builds, client.builds())

        session.get.assert_called_once_with(
            f"tenant/{tenant.name}/builds?job_name={job['name']}"
        )


class TestZuulPipelineRESTClient(TestCase):
    def test_equality(self):
        """Checks '__eq__'.
        """
        pipeline = {
            'name': 'pipeline'
        }

        session = Mock()
        project = Mock()

        client = ZuulPipelineRESTClient(session, project, pipeline)

        # Equality by type
        self.assertNotEqual(Mock(), client)

        # Equality by reference
        self.assertEqual(client, client)

        # Equality by contents
        self.assertEqual(
            ZuulPipelineRESTClient(session, project, pipeline),
            client
        )

    def test_jobs(self):
        """Checks call to 'jobs' end-point.
        """

        def get_job(url):
            if url == f"tenant/{project.tenant.name}/job/{jobs[0]['name']}":
                return jobs[0]

            if url == f"tenant/{project.tenant.name}/job/{jobs[1]['name']}":
                return jobs[1]

        jobs = [
            {
                'name': 'job1'
            },
            {
                'name': 'job2'
            }
        ]

        pipeline = {
            'name': 'pipeline',
            'jobs': jobs
        }

        session = Mock()
        session.get = Mock()
        session.get.side_effect = get_job

        project = Mock()
        project.name = 'project'
        project.tenant = Mock()
        project.tenant.name = 'tenant'

        client = ZuulPipelineRESTClient(session, project, pipeline)

        self.assertEqual(
            [
                ZuulJobRESTClient(session, project.tenant, jobs[0]),
                ZuulJobRESTClient(session, project.tenant, jobs[1])
            ],
            client.jobs()
        )

        session.get.assert_any_call(
            f"tenant/{project.tenant.name}/job/{jobs[0]['name']}"
        )

        session.get.assert_any_call(
            f"tenant/{project.tenant.name}/job/{jobs[1]['name']}"
        )


class TestZuulProjectRESTClient(TestCase):
    def test_equality(self):
        """Checks '__eq__'.
        """
        project = {
            'name': 'project'
        }

        session = Mock()
        tenant = Mock()

        client = ZuulProjectRESTClient(session, tenant, project)

        # Equality by type
        self.assertNotEqual(Mock(), client)

        # Equality by reference
        self.assertEqual(client, client)

        # Equality by contents
        self.assertEqual(
            ZuulProjectRESTClient(session, tenant, project),
            client
        )

    def test_url(self):
        """Checks that the user's url for the job is properly build.
        """
        project = {
            'name': 'project_1'
        }

        session = Mock()
        session.host = 'http://localhost:8080/'

        tenant = Mock()
        tenant.name = 'tenant'

        client = ZuulProjectRESTClient(session, tenant, project)

        self.assertEqual(
            'http://localhost:8080/t/tenant/project/project_1',
            client.url
        )

    def test_pipelines(self):
        """Checks call to 'pipelines' end-point.
        """
        project = {
            'name': 'project'
        }

        pipelines = [
            {
                'name': 'pipeline_1'
            },
            {
                'name': 'pipeline_2'
            }
        ]

        answer = {
            'configs': [
                {
                    'pipelines': pipelines
                }
            ]
        }

        session = Mock()
        session.get = Mock()

        session.get.return_value = answer

        tenant = Mock()
        tenant.name = 'tenant'

        client = ZuulProjectRESTClient(session, tenant, project)

        self.assertEqual(
            [
                ZuulPipelineRESTClient(session, client, pipelines[0]),
                ZuulPipelineRESTClient(session, client, pipelines[1])
            ],
            client.pipelines()
        )

        session.get.assert_called_once_with(
            f"tenant/{tenant.name}/project/{project['name']}"
        )


class TestZuulTenantRESTClient(TestCase):
    """Tests for :class:`ZuulTenantRESTClient`.
    """

    def test_builds(self):
        """Tests call to 'builds' end-point.
        """
        tenant = {
            'name': 'tenant_1'
        }

        builds = [
            {
                'name': 'build_1'
            },
            {
                'name': 'build_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        session.get.return_value = builds

        client = ZuulTenantRESTClient(session, tenant)

        self.assertEqual(builds, client.builds())

        session.get.assert_called_once_with(
            f"tenant/{tenant['name']}/builds"
        )

    def test_buildsets(self):
        """Tests call to 'buildsets' end-point.
        """
        tenant = {
            'name': 'tenant_1'
        }

        buildsets = [
            {
                'name': 'buildset_1'
            },
            {
                'name': 'buildset_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        session.get.return_value = buildsets

        client = ZuulTenantRESTClient(session, tenant)

        self.assertEqual(buildsets, client.buildsets())

        session.get.assert_called_once_with(
            f"tenant/{tenant['name']}/buildsets"
        )

    def test_projects(self):
        """Tests call to 'projects' end-point.
        """
        tenant = {
            'name': 'tenant_1'
        }

        projects = [
            {
                'name': 'project_1'
            },
            {
                'name': 'project_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        session.get.return_value = projects

        client = ZuulTenantRESTClient(session, tenant)

        self.assertEqual(
            [
                ZuulProjectRESTClient(session, client, projects[0]),
                ZuulProjectRESTClient(session, client, projects[1]),
            ],
            client.projects()
        )

        session.get.assert_called_once_with(
            f"tenant/{tenant['name']}/projects"
        )

    def test_jobs(self):
        """Tests call to 'jobs' end-point.
        """
        tenant = {
            'name': 'tenant_1'
        }

        jobs = [
            {
                'name': 'job_1'
            },
            {
                'name': 'job_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        session.get.return_value = jobs

        client = ZuulTenantRESTClient(session, tenant)

        self.assertEqual(
            [
                ZuulJobRESTClient(session, client, jobs[0]),
                ZuulJobRESTClient(session, client, jobs[1])
            ],
            client.jobs()
        )

        session.get.assert_called_once_with(
            f"tenant/{tenant['name']}/jobs"
        )


class TestZuulRestClient(TestCase):
    """Tests for :class:`ZuulRESTClient`
    """

    def test_info(self):
        """Tests call to 'info' end-point.
        """
        info = {
            'hello': 'world'
        }

        session = Mock()
        session.get = Mock()

        session.get.return_value = info

        client = ZuulRESTClient(session)

        self.assertEqual(info, client.info())

        session.get.assert_called_once_with('info')

    def test_tenants(self):
        """Tests call to 'tenants' end-point.
        """
        tenants = [
            {
                'name': 'tenant_1'
            },
            {
                'name': 'tenant_2'
            }
        ]

        session = Mock()
        session.get = Mock()

        session.get.return_value = tenants

        client = ZuulRESTClient(session)

        for idx, tenant in enumerate(client.tenants()):
            self.assertEqual(tenants[idx]['name'], tenant.name)

        session.get.assert_called_once_with('tenants')
