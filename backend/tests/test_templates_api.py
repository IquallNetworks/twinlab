"""Template library (delta 21): the pure pieces — fragment validation, the
publish-toggle request shape, and the published-lab rendering guards. Route
behavior against a live stack is the blackbox suite's job."""

import pydantic
import pytest

from twinlab_backend.api.templates import (
    fragment_device,
    published_lab_description,
    published_lab_summary,
)
from twinlab_backend.api_errors import ApiError
from twinlab_backend.db.models import Lab
from twinlab_backend.models import LabTemplateSet, NodeTemplateCreate
from twinlab_backend.result import Err, Ok


def test_fragment_device_extracts_the_device() -> None:
    result = fragment_device("device: vyos\nmodule: [ospf, bgp]\nbgp.as: 65001\n")
    assert isinstance(result, Ok)
    assert result.value == "vyos"


def test_fragment_must_be_yaml() -> None:
    result = fragment_device("device: [unclosed\n")
    assert isinstance(result, Err)
    assert "not valid YAML" in result.error


def test_fragment_must_be_a_mapping() -> None:
    # A bare scalar or list is not a node-attribute mapping.
    for content in ("just-a-string\n", "- device: vyos\n"):
        result = fragment_device(content)
        assert isinstance(result, Err)
        assert "mapping" in result.error


def test_fragment_must_name_its_device() -> None:
    # The house rule: a node's device is intentful — no silent default.
    for content in ("module: [ospf]\n", "device: ''\n", "device: [vyos]\n"):
        result = fragment_device(content)
        assert isinstance(result, Err)
        assert "device" in result.error


def test_fragment_size_is_bounded() -> None:
    result = fragment_device("device: vyos\nblob: " + "x" * (64 * 1024))
    assert isinstance(result, Err)
    assert "exceeds" in result.error


def test_publish_requires_a_description() -> None:
    with pytest.raises(pydantic.ValidationError):
        _ = LabTemplateSet(published=True, description=None)
    # Withdrawing needs none; a stray description is accepted and ignored.
    assert LabTemplateSet(published=False, description=None).published is False
    assert LabTemplateSet(published=True, description="a card").description == "a card"


def test_node_template_name_charset() -> None:
    with pytest.raises(pydantic.ValidationError):
        _ = NodeTemplateCreate(name="-bad", description="d", content="device: vyos\n")


def test_published_lab_rendering_and_the_corrupt_row_guard() -> None:
    lab = Lab(name="tmp1", definition="name: tmp1\n", status="deployed")
    lab.template_published = True
    lab.template_description = "the card"
    summary = published_lab_summary(lab)
    assert summary.tier == "user"
    assert summary.source_lab == "tmp1"
    assert summary.description == "the card"

    # A published row without a description is corrupt data — loud, never an
    # empty library card.
    lab.template_description = None
    with pytest.raises(ApiError) as raised:
        _ = published_lab_description(lab)
    assert raised.value.status_code == 500
