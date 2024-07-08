import os
import pytest
from modman.api import ModrinthAPI


instance = ModrinthAPI()


def test_search():
    result = instance.search_projects("fabric-api")
    assert result[0]
    assert result.page(1)
    assert result.all()


def test_get_project():
    result = instance.get_project("fabric-api")
    assert result
    assert result.id == "fabric-api"
    assert result.name == "Fabric API"
    assert result.slug == "fabric-api"
