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
class AttributeValue(object):

    def __init__(self, name, value=None, type=None, arguments=None,
                 populate=False):

        self.name = name
        self.value = value
        self.type = type
        # Contains different variants of arguments for the same attribute
        self.arguments = arguments
        # Mark this attribute for population by sources
        self.populate = populate
