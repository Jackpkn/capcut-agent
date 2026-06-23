"""Multimodal routing hints."""

from agent.routing_hints import attached_image_wants_answer_only


def test_see_this_image_is_answer_only():
    assert attached_image_wants_answer_only("see this image", 1) is True
    assert attached_image_wants_answer_only("see. this image", 1) is True


def test_analyze_image_is_answer_only():
    assert attached_image_wants_answer_only("analysis this image", 1) is True


def test_edit_with_image_is_not_answer_only():
    assert attached_image_wants_answer_only(
        "add transition like this image",
        1,
    ) is False


def test_no_images_false():
    assert attached_image_wants_answer_only("see this image", 0) is False
