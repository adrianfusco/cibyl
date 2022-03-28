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


def apply_filters(iterable, *filters):
    """Applies a set of filters to a collection.

    :param iterable: The collection to filter.
    :param filters: List of filters to apply.
    :return: The collection post-filtering.
    :rtype: list
    """
    result = list(iterable)

    for check in filters:
        result = list(filter(check, result))

    return result