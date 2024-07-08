"""
The models file contains a model for each expected response from the Modrinth API, as documented by Labrinth.

See: https://docs.modrinth.com/

Where applicable, error responses are also modelled, however some unexpected errors, like 500s, cannot be modelled.
"""

import enum
import re
from typing import Optional

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ByteSize, Field, NewPath

__all__ = (
    "BaseErrorResponse",
    "PlatformSupportType",
    "ProjectType",
    "MonetizationStatus",
    "ProjectStatus",
    "StagingRootResponse",
    "SearchResultProject",
    "SearchResult",
    "ProjectDonationURL",
    "ProjectLicense",
    "Project",
    "ProjectDependenciesResponse",
    "VersionDependencyType",
    "VersionDependency",
    "VersionType",
    "VersionStatus",
    "VersionFile",
    "Version",
)


class BaseErrorResponse(BaseModel):
    error: str
    """The name of the error"""
    description: str
    """The contents of the error"""


class PlatformSupportType(enum.Enum):
    """
    The options for client or server side support
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProjectType(enum.Enum):
    """The type of project."""

    MOD = "mod"
    MODPACK = "modpack"
    RESOURCE_PACK = "resourcepack"
    SHADER = "shader"


class MonetizationStatus(enum.Enum):
    """The monetization status of a project."""

    MONETIZED = "monetized"
    DEMONETIZED = "demonetized"
    FORCE_DEMONETIZED = "force-demonetized"


class ProjectStatus(enum.Enum):
    APPROVED = "approved"
    ARCHIVED = "archived"
    REJECTED = "rejected"
    DRAFT = "draft"
    UNLISTED = "unlisted"
    PROCESSING = "processing"
    WITHHELD = "withheld"
    SCHEDULED = "scheduled"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class StagingRootResponse(BaseModel):
    """
    The result of GET https://staging-api.modrinth.com/.
    """

    about: str
    """Usually 'Welcome traveler!'."""
    documentation: str
    """A URL to the API documentation."""
    name: str
    """The name of the API."""
    version: str
    """The version of the API."""


class SearchResultProject(BaseModel):
    """
    Represents the result of a search query.
    """

    slug: str = Field(pattern=re.compile(r"^[\w!@$()`.+,\"\-']{3,64}$"))
    """The slug of a project, used for vanity URLs."""
    title: str
    """The title or name of the project"""
    description: str
    """A short description of the project."""
    categories: list[str] = Field([])
    """The categories that the project belongs to."""
    client_side: PlatformSupportType
    """The client side support of the project"""
    server_side: PlatformSupportType
    """The server side support of the project"""
    project_type: ProjectType
    """The project type of the project"""
    downloads: int
    """The number of downloads the project has."""
    icon_url: AnyHttpUrl | str | None = None
    """The URL to the icon of the project. May be None or an empty string."""
    color: Optional[int] = Field(None, ge=0, le=0xFFFFFF)
    """The RGB color of the project, automatically generated from the project icon. May be None."""
    thread_id: Optional[str] = None
    """The ID of the moderation thread associated with this project. May be None."""
    monetization_status: MonetizationStatus | None = None
    project_id: str
    """The ID of the project."""
    author: str
    """The username of the project's author"""
    display_categories: list[str] = Field([])
    """A list of the categories that the project has which are not secondary"""
    versions: list[str]
    """A list of the minecraft versions supported by the project"""
    follows: int
    """The total number of users following the project"""
    date_created: AwareDatetime
    """The date the project was added to search"""
    date_modified: AwareDatetime
    """The date the project was last modified"""
    latest_version: Optional[str] = None
    """The latest version of minecraft that this project supports. May be None."""
    license: str
    """The SPDX license ID of a project"""
    gallery: list[AnyHttpUrl] = Field([])
    """All gallery images attached to the project"""
    featured_gallery: Optional[AnyHttpUrl] = Field(None)
    """The featured gallery image of the project"""


class SearchResult(BaseModel):
    """
    Represents the result of GET /search
    """

    hits: list[SearchResultProject]
    """The list of results"""
    offset: int
    """The number of results that were skipped by the query"""
    limit: int
    """The number of results that were returned by the query"""
    total_hits: int
    """The total number of results that match the query"""


class ProjectDonationURL(BaseModel):
    id: str
    """The ID of the donation platform"""
    platform: str
    """The donation platform this link is to"""
    url: AnyHttpUrl
    """The URL of the donation platform and user"""


class ProjectLicense(BaseModel):
    id: str
    """The SPDX license ID of a project"""
    name: str
    """The name of the license"""
    url: AnyHttpUrl | None
    """The URL to the license"""


class GalleryImage(BaseModel):
    url: AnyHttpUrl
    """The URL of the image"""
    featured: bool
    """Whether the image is featured or not"""
    title: str | None = None
    """The title of the image. May be None."""
    description: str | None = None
    """The description of the image. May be None."""
    created: AwareDatetime
    """The date and time the image was created"""
    ordering: int
    """The order of the gallery image. Gallery images are sorted by this field and then alphabetically by title."""


class Project(BaseModel):
    """
    Represents the result of fetching an individual project.
    """

    # Note to contributors: This cannot inherit from SearchResultProject, unfortunately. The differences are too great.
    slug: str = Field(pattern=re.compile(r"^[\w!@$()`.+,\"\-']{3,64}$"))
    """The slug of a project, used for vanity URLs."""
    title: str
    """The title or name of the project"""
    description: str
    """A short description of the project."""
    categories: list[str]
    """The categories that the project belongs to."""
    client_side: PlatformSupportType
    """The client side support of the project"""
    server_side: PlatformSupportType
    """The server side support of the project"""
    body: str
    """A long form description of the project"""
    status: ProjectStatus
    """The status of the project"""
    requested_status: ProjectStatus | None = None
    """The requested status when submitting for review or scheduling the project for release"""
    additional_categories: list[str] = Field([])
    """A list of categories which are searchable but non-primary"""
    issues_url: AnyHttpUrl | None = None
    """An optional link to where to submit bugs or issues with the project. May be None."""
    source_url: AnyHttpUrl | None = None
    """An optional link to the source code of the project. May be None."""
    wiki_url: AnyHttpUrl | None = None
    """An optional link to the project's wiki page or other relevant information. May be None."""
    discord_url: AnyHttpUrl | None = None
    """An optional invite link to the project's discord. May be None."""
    donation_urls: list[ProjectDonationURL] = Field([])
    """A list of donation links for the project"""
    downloads: int
    """The number of downloads the project has."""
    icon_url: AnyHttpUrl | None = None
    """The URL to the icon of the project. May be None."""
    color: int | None = None
    """The RGB color of the project, automatically generated from the project icon. May be None."""
    thread_id: str | None = None
    """The ID of the moderation thread associated with this project. May be None."""
    monetization_status: MonetizationStatus | None = None
    id: str
    """The ID of the project, encoded as a base62 string"""
    team: str
    """The ID of the team that has ownership of this project"""
    published: AwareDatetime
    """The date the project was published"""
    updated: AwareDatetime
    """The date the project was last updated"""
    approved: AwareDatetime | None = None
    """The date the project's status was set to an approved status. May be None."""
    queued: AwareDatetime | None = None
    """The date the project's status was submitted to moderators for review. May be None."""
    followers: int
    """The total number of users following the project"""
    license: ProjectLicense
    """The license of the project"""
    versions: list[str] = Field([])
    """A list of the version IDs of the project (will never be empty unless `draft` status)"""
    game_versions: list[str] = Field([])
    """A list of all of the game versions supported by the project"""
    loaders: list[str] = Field([])
    """A list of all of the loaders supported by the project"""
    gallery: list[GalleryImage] = Field([])
    """A list of images that have been uploaded to the project's gallery"""


class ProjectDependenciesResponse(BaseModel):
    projects: list[Project]
    versions: list["Version"]


class VersionDependencyType(enum.Enum):
    """The type of dependency."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    INCOMPATIBLE = "incompatible"
    EMBEDDED = "embedded"


class VersionDependency(BaseModel):
    version_id: str | None = None
    """The specific ID of the version that this version depends on"""
    project_id: str | None = None
    """The ID of the project that this version depends on"""
    file_name: str | None = None
    """The file name of the dependency, mostly used for showing external dependencies on modpacks"""
    dependency_type: VersionDependencyType
    """The type of dependency that this version has"""


class VersionType(enum.Enum):
    """The type of version.

    This enum has an integer representation:

    - alpha: 0
    - beta: 1
    - release: 2

    This allows for easy comparison of version types. For example,
    `VersionType.ALPHA < VersionType.RELEASE` will return True, as an alpha release is pre-release."""

    RELEASE = "release"
    BETA = "beta"
    ALPHA = "alpha"

    def __int__(self):
        return ["alpha", "beta", "release"].index(self.value)


class VersionStatus(enum.Enum):
    LISTED = "listed"
    ARCHIVED = "archived"
    DRAFT = "draft"
    UNLISTED = "unlisted"
    SCHEDULED = "scheduled"
    UNKNOWN = "unknown"


class VersionFile(BaseModel):
    """A list of files available for download for this version"""

    class Hashes(BaseModel):
        sha1: str
        """The SHA1 hash of the file"""
        sha512: str
        """The sha512 hash of the file"""

    class Type(enum.Enum):
        REQUIRED_RESOURCE_PACK = "required-resource-pack"
        OPTIONAL_RESOURCE_PACK = "optional-resource-pack"

    hashes: Hashes
    """A map of hashes of the file. The key is the hashing algorithm and the value is the string version of the hash."""
    url: AnyHttpUrl
    """A direct link to the file"""
    filename: NewPath
    """The name of the file"""
    primary: bool
    """
    Whether this file is the primary one for its version.
    
    Only a maximum of one file per version will have this set to true. 
    If there are not any primary files, it can be inferred that the first file is the primary one.
    """
    size: ByteSize
    """The size of the file in bytes"""
    file_type: Type | None = None
    """The type of the additional file, used mainly for adding resource packs to datapacks"""


class Version(BaseModel):
    """Versions contain download links to files with additional metadata."""

    name: str
    """The name of the version"""
    version_number: str
    """
    The version number. Ideally will follow semantic versioning
    
    Note that in *most* cases, mods to not actually follow semantic versioning. To detect "newness",
    its recommended (by modman) to compare the release date and type, rather than the version number.
    """
    changelog: str | None = None
    """A changelog for the version. May be None."""
    dependencies: list[VersionDependency] = Field([])
    """A list of specific versions of projects that this version depends on"""
    game_versions: list[str]
    """A list of versions of Minecraft that this version supports"""
    version_type: VersionType
    """The release channel for this version"""
    loaders: list[str]
    """The mod loaders that this version supports"""
    featured: bool
    """Whether the version is featured or not"""
    status: VersionStatus | None
    requested_status: VersionStatus | None = None
    id: str
    """The ID of the version, encoded as a base62 string"""
    project_id: str
    """The ID of the project this version is for"""
    author_id: str
    """The ID of the author of the version"""
    date_published: AwareDatetime
    downloads: int
    """The number of times this version has been downloaded"""
    files: list[VersionFile]
    """A list of files available for download for this version"""

    @property
    def primary_file(self) -> VersionFile:
        """Returns the primary file for this version.

        If a file is not explicitly marked as primary, the first one is returned."""
        for file in self.files:
            if file.primary:
                return file
        return self.files[0]

    @property
    def is_pre_release(self) -> bool:
        """Returns whether this version is a pre-release (alpha or beta)"""
        return self.version_type != VersionType.RELEASE

    def __gt__(self, other):
        return (self.version_type, self.date_published) > (other.version_type, other.date_published)

    def __ge__(self, other):
        return (self.version_type, self.date_published) >= (other.version_type, other.date_published)

    def __lt__(self, other):
        return (self.version_type, self.date_published) < (other.version_type, other.date_published)

    def __le__(self, other):
        return (self.version_type, self.date_published) <= (other.version_type, other.date_published)

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)
