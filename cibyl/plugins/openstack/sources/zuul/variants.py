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
from typing import Any, Iterable, Optional

from overrides import overrides

from cibyl.sources.zuul.transactions import VariantResponse

LOG = logging.getLogger(__name__)


class VariableSearch:
    """Utility meant to make finding a variable in a Zuul job easier.
    """

    def __init__(self, search_terms: Iterable[str]):
        """Constructor.

        :param search_terms: List containing the possible names of the job
            variable to be searched. The list will be iterated following the
            containers iterator, giving priority to terms that appear first.
            As an example, given a list of two names for a variable: ['val1',
            'val2'], 'val1' will always be preferred over 'val2', falling back
            to the later one only if the first does not exist.
        """
        self._search_terms = search_terms

    @property
    def search_terms(self) -> Iterable[str]:
        """
        :return: Possible names of the desired variable that this will
            search for.
        """
        return self._search_terms

    def search(self, variant: VariantResponse) -> Optional[Any]:
        """Search this target's variable among the ones defined in the
        provided variant.

        :param variant: The variant to search.
        :return: Value of the variable if it is found, None if not.
        """
        variables = variant.variables(recursive=True)

        for search_term in self.search_terms:
            if search_term in variables:
                return variables[search_term]

        return None


class ReleaseSearch(VariableSearch):
    """Utility designed to make finding the release variable of a job easier.
    """
    DEFAULT_SEARCH_TERMS = (
        'rhos_release_version',
        'osp_release',
        'release'
    )
    """Default variables known to hold the job's release."""

    def __init__(self, search_terms: Iterable[str] = DEFAULT_SEARCH_TERMS):
        """Constructor. See parent for more information.
        """
        super().__init__(search_terms)

    @overrides
    def search(self, variant: VariantResponse) -> Optional[str]:
        LOG.debug("Searching for release on variant: '%s'.", variant.name)

        result = super().search(variant)

        # The release was not found
        if not result:
            return None

        return str(result)


class FeatureSetSearch(VariableSearch):
    """Utility designed to make finding the featureset variable of a job
    easier.
    """

    DEFAULT_SEARCH_TERMS = ('featureset',)
    """Default variables known to hold the job's featureset."""

    def __init__(self, search_terms: Iterable[str] = DEFAULT_SEARCH_TERMS):
        """Constructor. See parent for more information.
        """
        super().__init__(search_terms)

    @overrides
    def search(self, variant: VariantResponse) -> Optional[str]:
        LOG.debug("Searching for featureset on variant: '%s'.", variant.name)

        return super().search(variant)


class FeatureSetOverridesSearch(VariableSearch):
    """Utility designed to make finding the featureset overrides of a job
    easier.
    """
    DEFAULT_SEARCH_TERMS = ('featureset_override',)
    """Default variables known to hold the job's featureset overrides."""

    def __init__(self, search_terms: Iterable[str] = DEFAULT_SEARCH_TERMS):
        """Constructor. See parent for more information.
        """
        super().__init__(search_terms)

    @overrides
    def search(self, variant: VariantResponse) -> Optional[dict]:
        LOG.debug("Searching for overrides on variant: '%s'.", variant.name)

        return super().search(variant)