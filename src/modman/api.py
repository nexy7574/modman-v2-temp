import collections
import hashlib
import json
import logging
import os
import typing
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeVar

from appdirs import user_cache_dir
from httpx import Client, HTTPStatusError, Headers, Response

from .errors import Ratelimited
from .models import *

try:
    import h2
except ImportError:
    h2 = None


T = TypeVar("T")
SEARCH_INDEX = typing.Literal["relevance", "downloads", "follows", "newest", "updated"]


class Ratelimiter:
    def __init__(self, limit: int, remaining: int = None, reset: int = None):
        self.limit = limit
        self.remaining = remaining or limit
        self.reset = reset or 0
        self.last_hit = datetime.min if self.reset == 0 else datetime.now()

    def __repr__(self):
        return (
            "<Ratelimiter limit={0.limit} remaining={0.remaining} reset={0.reset} " "last_hit={0.last_hit!r}>"
        ).format(self)

    @property
    def reset_at(self) -> datetime:
        """The datetime at which point this ratelimit would reset."""
        return self.last_hit + timedelta(seconds=self.reset)

    def sync(self: T, *, limit: int, remaining: int, reset: int) -> T:
        """
        Synchronises the ratelimter from the API response.

        :param limit: X-Ratelimit-Limit
        :param remaining: X-Ratelimit-Remaining
        :param reset: X-Ratelimit-Reset
        :return: This instance
        """
        if limit >= 0:
            self.limit = limit
        if remaining >= 0:
            self.remaining = remaining
        if reset >= 0:
            self.reset = reset
        self.last_hit = datetime.now()
        return self

    def are_ratelimited(self) -> bool:
        """Returns True if the ratelimit is exceeded."""
        return self.reset_at >= datetime.now() and self.remaining == 0


class SearchIterator(collections.abc.Iterator):
    """An iterator that fetches search results from the API.

    If you just want to get all results, use `.all()`. To get a specific page, use `.page()`. Otherwise, iterate!

    THIS ITERATOR IS NOT THREAD SAFE!
    """

    def __init__(
        self,
        client: "ModrinthAPI",
        query: str = None,
        facets: list[list[str]] = None,
        index: SEARCH_INDEX = "relevance",
        offset: int = 0,
        limit: int = 100,
    ):
        self.log = logging.getLogger("modman.api.SearchIterator")
        if limit > 100:
            raise ValueError("Limit cannot be greater than 100")
        elif limit <= 0:
            raise ValueError("Limit cannot be less than 1")
        self.client = client
        self.query = query
        self.facets = facets
        self.index = index
        self.offset = offset
        self.limit = limit

        self._page = offset // limit
        self.page_cache: dict[int, SearchResult] = {}

        self.total_hits = 9999

        self.log.debug("Initialised with parameters: %r", self)

    def __str__(self):
        return "<SearchIterator query=%r>" % self.query

    def __repr__(self):
        return (
            "<SearchIterator client={0.client!r} query={0.query!r} facets={0.facets!r} index={0.index!r} "
            "offset={0.offset} limit={0.limit} page={0._page} page_cache={0.page_cache}>"
        ).format(self)

    def construct_params(self) -> dict[str, str | int]:
        params = {"index": self.index, "offset": self.limit * self._page, "limit": self.limit}
        if self.query:
            params["query"] = self.query
        if self.facets:
            params["facets"] = json.dumps(self.facets, separators=(",", ":"), default=str)
        self.log.debug("Constructed parameters: %r", params)
        return params

    def __iter__(self) -> "SearchIterator":
        return self

    def __next__(self) -> SearchResult:
        self.log.debug("Fetching page %d with params: %r", self._page, self.construct_params())
        try:
            response = self.client._get_json("/search", params=self.construct_params())
        except HTTPStatusError as e:
            self.log.debug("Stopping iteration, got HTTP %d", e.response.status_code)
            raise StopIteration

        parsed = SearchResult.model_validate(response)
        if (ph := (parsed.total_hits / self.limit)) > self.client.ratelimiter.limit:  # would get ratelimited iterating
            raise RuntimeError(
                "Search too vague - would exceed %d requests. Narrow your search." % ph
            )
        self.log.debug("Predicted %d hits for entire search iteration", ph)

        if parsed.total_hits != self.total_hits:
            self.total_hits = parsed.total_hits
        self.log.debug("Page %d results (%d hits): %r", self._page, parsed.total_hits, parsed.hits)
        self.page_cache[self._page] = parsed
        self._page += 1
        if not parsed.hits:
            self.log.debug("Stopping iteration, no more results")
            raise StopIteration
        elif len(parsed.hits) < self.limit:
            self.log.debug("Stopping iteration, exhausted results")
            raise StopIteration

        if ph >= 60 and os.getenv("MODMAN_NO_SEARCH_BUDGET") is None:
            self.log.debug("Sleeping for %.2f seconds to avoid ratelimiting during search", ph / 600)
            time.sleep(ph / 600)
        return parsed

    def page(self, number: int) -> SearchResult:
        """Get a specific page of results.

        The page number is zero-indexed, equivalent to `page * limit + offset`
        """
        if isinstance(number, slice):
            raise NotImplementedError("Slicing is not supported")
        if number in self.page_cache:
            self.log.debug("Returning cached page %d", number)
            return self.page_cache[number]

        original_page = self._page
        self._page = number
        try:
            return next(self)
        except StopIteration:
            self._page = original_page
            raise IndexError("Page index out of range")
        finally:
            self._page = original_page

    def __getitem__(self, item: int) -> list[SearchResultProject]:
        if isinstance(item, slice):
            raise NotImplementedError("Slicing is not supported")
        return self.page(item).hits

    def all(self) -> list[SearchResultProject]:
        """Get all results from the search."""
        r = []
        for page in self:
            r.extend(page.hits)
        return r


class ModrinthAPI:
    HEADERS = property(lambda self: Headers({"User-Agent": "ModMan/2.0.0a1 (+https://github.com/nexy7574/modman)"}))

    def __init__(self, client: Client = None):
        self.client = client or Client(
            base_url="https://api.modrinth.com/v2", headers=self.HEADERS, http2=h2 is not None
        )
        self.ratelimiter = Ratelimiter(300)

    @property
    def cache(self) -> Path:
        """Returns the cache dir for this user"""
        return Path(user_cache_dir("modman")).resolve()

    @staticmethod
    def _dump(obj: typing.Any) -> str:
        return json.dumps(obj, separators=(",", ":"))

    def _get(self, url: str, **kwargs) -> Response:
        url = str(url)  # just in case someone passes a pydantic URL object
        if self.ratelimiter.are_ratelimited():
            raise Ratelimited(self.ratelimiter.reset_at)
        response = self.client.get(url, **kwargs)
        self.ratelimiter.sync(
            limit=int(response.headers.get("X-Ratelimit-Limit", -1)),
            remaining=int(response.headers.get("X-Ratelimit-Remaining", -1)),
            reset=int(response.headers.get("X-Ratelimit-Reset", -1)),
        )
        return response

    def _get_json(self, url: str, **kwargs) -> typing.Any:
        """
        Wrapper around _get that returns the json content of the response.

        This function requires that the resulting response code is in the 2XX range.
        """
        response = self._get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def construct_facets(**kwargs: str | int) -> list[list[str]]:
        """
        Converts the input into facets.

        This allows you to perform operation queries, like > and <. For example:

            >>> ModrinthAPI.construct_facets(versions="1.20.1", categories="fabric")
            [['versions:1.20.1', 'categories:fabric']]  # Only things supporting minecraft 1.20.1 and the fabric loader
            >>> ModrinthAPI.construct_facets(downloads__gte=100, follows__lt=10)
            [['downloads>=100', 'follows<10']]  # Less than 10 follows, but more than 100 downloads
            # This is a simple "AND" operation. You can do a more complex query by adding more lists:
            >>> facet1 = ModrinthAPI.construct_facets(versions="1.20.1", categories="fabric")
            >>> facet2 = ModrinthAPI.construct_facets(versions="1.20.1", categories="forge")
            >>> facet1 + facet2
            [['versions:1.20.1', 'categories:fabric'], ['versions:1.20.1', 'categories:forge']]
            # ^ This means "Fabric, 1.20.1" OR "Forge, 1.20.1".
            # You can also merge these to create a more complex AND query:
            >>> [facet1[0] + ModrinthAPI.construct_facets(downloads_gt=0)[0]]
            [['versions:1.20.1', 'categories:fabric', 'downloads>0']]
            # ^ This means "Fabric, 1.20.1" AND "Downloads greater than 0"
        """
        ops = {"gt": ">", "lt": "<", "ne": "!=", "eq": ":", "gte": ">=", "lte": "<="}
        mapping = {}
        for key, value in kwargs.items():
            try:
                field, op = key.rsplit("__", 1)
            except ValueError:
                field, op = key, "eq"
            mapping.setdefault(field, [])
            mapping[field].append((ops[op], value))

        result = []
        for key, values in mapping.items():
            result_key = []
            for value in values:
                result_key.append("".join([key, *value]))
            result.append(result_key)
        return result

    # Section: Projects

    def search_projects(
        self,
        query: str = None,
        facets: list[list[str]] = None,
        index: SEARCH_INDEX = "relevance",
        offset: int = 0,
        limit: int = 20,
    ) -> SearchIterator:
        """
        Returns an iterator to handle searching projects on modrinth.

        You can get facets via the `ModrinthAPI.construct_facets` function.

        :param query: The optional query string to search for
        :param facets: A list of facets to filter with
        :param index: The initial index to sort with, defaults to "relevance"
        :param offset: The initial offset, usually zero.
        :param limit: The limit of results per page, defaults to 20.
        :return: SearchIterator
        """
        return SearchIterator(self, query, facets, index, offset, limit)

    def get_project(self, project_id_or_slug: str) -> Project:
        """Get a project by its ID or slug."""
        return Project.model_validate(self._get_json(f"/project/{project_id_or_slug}"))

    def get_multiple_projects(self, *ids: str) -> list[Project]:
        """
        Get multiple projects by their IDs or slugs.

        :param ids: A list of project IDs or slugs.
        :return: A list of projects. Any not found projects will be omitted, so it's recommended to check the result IDs
        """
        return [Project.model_validate(x) for x in self._get_json("/projects", params={"ids": self._dump(ids)})]

    def get_random_projects(self, count: int) -> list[Project]:
        """Get a list of random projects."""
        if count > 100:
            raise ValueError("Count cannot be greater than 100")
        elif count < 0:
            raise ValueError("Count cannot be less than 0")
        return [Project.model_validate(x) for x in self._get_json("/projects_random", params={"count": count})]

    def check_slug_validity(self, slug: str) -> str:
        """
        Checks if a slug (or project ID) is valid, returning the project ID
        :param slug: The slug (or ID) to check
        :return: The project ID, if valid
        :raises: ValueError if the slug is invalid
        """
        try:
            response = self._get_json(f"/project/{slug}/check")
        except HTTPStatusError:
            raise ValueError("The slug/ID %r is invalid." % slug)
        return response["id"]

    check_id_validity = check_slug_validity
    """Check if a project ID is valid"""

    def get_project_dependencies(self, slug: str | Project) -> ProjectDependenciesResponse:
        """
        Get a list of dependencies for a project.

        :param slug: The slug or project object to get dependencies for
        :return: A list of projects
        """
        if isinstance(slug, Project):
            slug = slug.id

        response = self._get_json(f"/project    /{slug}/dependencies")
        return ProjectDependenciesResponse.model_validate(response)

    # Section: Versions

    def list_project_versions(
        self,
        slug: str | Project,
        loaders: list[str] = None,
        game_versions: list[str] = None,
        featured: bool | None = None,
    ) -> list[Version]:
        """
        List all versions of a project.

        :param slug: The slug or project object to list versions for
        :param loaders: A list of loaders to filter with, such as forge, or fabric
        :param game_versions: A list of game versions to filter with, such as 1.12.2, 21w03a, etc.
        :param featured: Allows to filter for featured or non-featured versions only. None will not filter.
        :return: A list of matching versions. May be empty.
        """
        if isinstance(slug, Project):
            slug = slug.id

        params = {}
        if loaders:
            params["loaders"] = self._dump(loaders)
        if game_versions:
            params["game_versions"] = self._dump(game_versions)
        if featured is not None:
            params["featured"] = self._dump(featured)

        return [Version.model_validate(x) for x in self._get_json(f"/project/{slug}/versions", params=params)]

    def get_version(self, version_id: str) -> Version:
        """Get a version by its ID."""
        return Version.model_validate(self._get_json(f"/version/{version_id}"))

    def get_version_from_number(self, project_id: str | Project, number_or_id: str) -> Version:
        """
        Get a version by its number or ID

        Please note that, if the version number provided matches multiple versions,
        only the **oldest** matching version will be returned.

        :param project_id: The project ID or slug to which the desired version belongs to
        :param number_or_id: The version number or ID to look up
        :return: A matching version
        """
        if isinstance(project_id, Project):
            project_id = project_id.id

        return Version.model_validate(self._get_json(f"/project/{project_id}/version/{number_or_id}"))

    def get_multiple_versions(self, *ids: str) -> list[Version]:
        """
        Fetches multiple versions by their IDs.

        :param ids: The IDs to fetch
        :return: A list of matching Versions. Any not found versions will be omitted.
        """
        try:
            response = self._get_json("/versions", params={"ids": self._dump(ids)})
        except HTTPStatusError as e:
            if e.response.status_code == 414:
                raise ValueError("Too many IDs provided (resulting URL too long)")
            raise
        return [Version.model_validate(x) for x in response]

    # Section: Version Files

    @typing.overload
    def get_version_from_hash(
        self, file_hash: os.PathLike, algorithm: typing.Literal["sha1", "sha512"] = "sha1", multiple: False = False
    ) -> Version:
        """Get a version from its file hash, generating the file hash on the fly."""
        ...

    @typing.overload
    def get_version_from_hash(
        self, file_hash: os.PathLike, algorithm: typing.Literal["sha1", "sha512"] = "sha1", multiple: True = True
    ) -> list[Version]:
        """Get a list of versions from a file hash, generating the file hash on the fly."""
        ...

    @typing.overload
    def get_version_from_hash(
        self, file_hash: str, algorithm: typing.Literal["sha1", "sha512"] = "sha1", multiple: False = False
    ) -> Version:
        """Get a version from a pre-computed hash"""
        ...

    @typing.overload
    def get_version_from_hash(
        self, file_hash: str, algorithm: typing.Literal["sha1", "sha512"] = "sha1", multiple: True = True
    ) -> list[Version]:
        """Get a list of versions a pre-computed hash"""
        ...

    def get_version_from_hash(
        self, file_hash: str | os.PathLike, algorithm: typing.Literal["sha1", "sha512"] = "sha1", multiple: bool = False
    ) -> Version | list[Version]:
        """
        Get a version from a file hash.

        :param file_hash: The file hash to look up
        :param algorithm: The algorithm used to generate the hash
        :param multiple: If True, returns a list of versions. If False, returns the first version found.
        :return: A matching version or a list of versions
        """
        if isinstance(file_hash, os.PathLike):
            with open(file_hash, "rb") as f:
                file_hash = hashlib.new(algorithm, f.read()).hexdigest()

        response = self._get_json(f"/version_file/{file_hash}", params={"algorithm": algorithm, "multiple": multiple})
        if multiple:
            return [Version.model_validate(x) for x in response]
        return Version.model_validate(response)


class FabricAPI:
    HEADERS = property(lambda self: Headers({"User-Agent": "ModMan/2.0.0a1 (+https://github.com/nexy7574/modman)"}))

    def __init__(self, client: Client = None):
        self.client = client or Client(
            base_url="https://meta.fabricmc.net/v2/versions", headers=self.HEADERS, http2=h2 is not None
        )
