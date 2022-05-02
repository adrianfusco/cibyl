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

from cibyl.models.ci.system import JobsSystem, System, ZuulSystem
from cibyl.orchestrator import Orchestrator


class TestAPI(TestCase):
    """Test that the System API reflects the configuration environment."""
    def setUp(self):
        self.config = {
            'environments': {
                'env3': {
                    'system3': {
                        'system_type': 'jenkins'},
                    'system4': {
                        'system_type': 'zuul'}
                }}}
        self.config_reverse = {
            'environments': {
                'env3': {
                    'system4': {
                        'system_type': 'zuul'},
                    'system3': {
                        'system_type': 'jenkins'}
                }}}
        self.config_jenkins = {
            'environments': {
                'env3': {
                    'system3': {
                        'system_type': 'jenkins'}}}}
        self.config_zuul = {
            'environments': {
                'env3': {
                    'system3': {
                        'system_type': 'zuul'}}}}
        self.orchestrator = Orchestrator()

    def test_system_api_zuul_jenkins(self):
        """Checks that the creation of multiple types of systems leads to
        the combined API of all of them.
        """
        self.orchestrator.config.data = self.config
        self.orchestrator.create_ci_environments()
        self.assertEqual(System.API, ZuulSystem.API)

    def test_system_api_zuul_jenkins_reverse_order(self):
        """Checks that the creation of multiple types of systems leads to
        the combined API of all of them.
        """
        self.orchestrator.config.data = self.config_reverse
        self.orchestrator.create_ci_environments()
        self.assertEqual(System.API, ZuulSystem.API)

    def test_system_api_zuul(self):
        """Checks that the creation of multiple types of systems leads to
        the combined API of all of them.
        """
        self.orchestrator.config.data = self.config_zuul
        self.orchestrator.create_ci_environments()
        self.assertEqual(System.API, ZuulSystem.API)

    def test_system_api_jenkins(self):
        """Checks that the creation of multiple types of systems leads to
        the combined API of all of them.
        """
        self.orchestrator.config.data = self.config_jenkins
        self.orchestrator.create_ci_environments()
        self.assertEqual(System.API, JobsSystem.API)