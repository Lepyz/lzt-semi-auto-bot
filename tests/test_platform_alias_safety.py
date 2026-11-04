import pytest

from bot.links import normalize_panel_link, target_key, valid_link
from conftest import receive_and_run


@pytest.mark.parametrize("platform,left,right", [
    ("facebook", "https://www.facebook.com/sampleuser", "https://mbasic.facebook.com/sampleuser"),
    ("facebook", "https://www.facebook.com/watch/?v=123", "https://web.facebook.com/watch/?v=123"),
    ("kick", "https://kick.com/sampleuser", "https://player.kick.com/sampleuser?autoplay=true"),
    ("kick", "https://kick.com/sampleuser?clip_id=ABC", "https://player.kick.com/sampleuser?clip_id=ABC&autoplay=true"),
    ("twitch", "https://www.twitch.tv/sampleuser", "https://player.twitch.tv/?channel=sampleuser&parent=example.com"),
    ("twitch", "https://www.twitch.tv/videos/123", "https://player.twitch.tv/?video=v123&parent=example.com"),
    ("twitch", "https://clips.twitch.tv/AmusedClip", "https://clips.twitch.tv/embed?clip=AmusedClip&parent=example.com"),
    ("twitch", "https://clips.twitch.tv/AmusedClip", "https://www.twitch.tv/sampleuser/clip/AmusedClip?filter=clips"),
])
def test_official_host_and_player_aliases_identify_the_same_target(platform, left, right):
    assert valid_link(left, platform) and valid_link(right, platform)
    assert target_key(left, platform) == target_key(right, platform)
    assert normalize_panel_link(right, platform) == right


@pytest.mark.parametrize("url", ["https://kick.com/sampleuser/videos", "https://kick.com/sampleuser/clips",
                                  "https://kick.com/videos", "https://kick.com/clip"])
def test_kick_requires_an_actual_target_identifier(url):
    assert not valid_link(url, "kick")


@pytest.mark.parametrize("platform,raw,expected", [
    ("youtube", "shorts/AbC123?t=12#share", "https://www.youtube.com/shorts/AbC123?t=12#share"),
    ("tiktok", "@sampleuser/video/123/?lang=tr#share", "https://www.tiktok.com/@sampleuser/video/123/?lang=tr#share"),
    ("telegram", "sampleuser/123?single#share", "https://t.me/sampleuser/123?single#share"),
    ("kick", "sampleuser/videos/01234567-abcd-1234/?ref=share#t=3", "https://kick.com/sampleuser/videos/01234567-abcd-1234/?ref=share#t=3"),
    ("x", "i/web/status/123?s=20#share", "https://x.com/i/web/status/123?s=20#share"),
    ("tiktok", "@sampleuser/photo/123/?lang=tr#share", "https://www.tiktok.com/@sampleuser/photo/123/?lang=tr#share"),
])
def test_partial_content_urls_keep_their_query_and_fragment(platform, raw, expected):
    assert normalize_panel_link(raw, platform) == expected
    assert valid_link(expected, platform, "content")


@pytest.mark.parametrize("platform,left,right", [
    ("facebook", "https://www.facebook.com/sampleuser", "https://mbasic.facebook.com/sampleuser"),
    ("kick", "https://kick.com/sampleuser", "https://player.kick.com/sampleuser?autoplay=true"),
    ("twitch", "https://www.twitch.tv/sampleuser", "https://player.twitch.tv/?channel=sampleuser&parent=example.com"),
])
def test_new_alias_cannot_bypass_an_existing_active_order(rig, platform, left, right):
    binding = rig.store.setting("binding:10")
    binding["components"][0].update(platform=platform, target_type="profile")
    rig.store.set_setting("binding:10", binding)
    first = receive_and_run(rig, 1, left)
    second = receive_and_run(rig, 2, right)
    assert first["state"] == "submitted" and second["state"] == "waiting"
    assert len(rig.panels.adds) == 1 and rig.store.owner(first["target"]) == first["id"]


@pytest.mark.parametrize("legacy_state", ["submitted", "review"])
def test_legacy_twitch_clip_lock_and_fifo_survive_new_url_form(rig, legacy_state):
    from conftest import payload
    binding = rig.store.setting("binding:10")
    binding["components"][0].update(platform="twitch", target_type="content")
    rig.store.set_setting("binding:10", binding)
    url = "https://www.twitch.tv/sampleuser/clip/Amused_Clip?filter=clips"
    old, _ = rig.engine.receive(payload(1, url))
    rig.engine.prepare(old)
    old.update(target="twitch.tv/sampleuser/clip/Amused_Clip?filter=clips", state=legacy_state)
    if legacy_state == "submitted":
        old["parts"][0].update(state="submitted", smm_id="9001")
    rig.store.save(old)
    if legacy_state == "submitted":
        rig.store.acquire_target(old["target"], old["id"])
    newer = receive_and_run(rig, 2, "https://clips.twitch.tv/Amused_Clip")
    assert newer["state"] == "waiting" and not rig.panels.adds
    if legacy_state == "submitted":
        rig.panels.current = {"status": "Completed", "terminal": True}
        rig.engine.refresh(old["id"])
    else:
        rig.engine.close_unsubmitted(old["id"], old["revision"])
    assert rig.store.get(newer["id"])["state"] == "ready" and not rig.panels.adds


def test_prepared_old_order_restores_the_same_targets_complete_buyer_url(rig):
    from conftest import payload
    url = "https://www.youtube.com/watch?v=AbC123&list=PLExample#t=12"
    binding = rig.store.setting("binding:10")
    binding["components"][0].update(platform="youtube", target_type="content")
    rig.store.set_setting("binding:10", binding)
    old, _ = rig.engine.receive(payload(1, url))
    rig.engine.prepare(old)
    old["parts"][0]["link"] = "https://youtube.com/watch?v=AbC123&list=PLExample"
    rig.store.save(old)
    rig.engine.execute(old["id"])
    assert rig.panels.adds[0][1] == url
    assert rig.store.get(old["id"])["parts"][0]["link"] == url


@pytest.mark.parametrize("url", [
    "https://player.twitch.tv/?video=not-a-video&channel=sampleuser",
    "https://player.twitch.tv/?video=123&channel=sampleuser",
    "https://player.twitch.tv/?video=123&video=456&channel=sampleuser",
])
def test_conflicting_twitch_player_targets_are_not_guessed(url):
    assert not valid_link(url, "twitch") and not target_key(url, "twitch")


@pytest.mark.parametrize("platform,url", [
    ("instagram", "https://www.instagram.com/sample.jpg"),
    ("tiktok", "https://www.tiktok.com/@sample.png"),
    ("youtube", "https://www.youtube.com/@sample.jpg"),
])
def test_dots_in_a_valid_username_are_not_mistaken_for_an_image(platform, url):
    assert valid_link(url, platform, "profile") and normalize_panel_link(url, platform) == url
