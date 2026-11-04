"""Platform-specific completion must preserve the URL actually sent to the panel."""
import pytest

from bot.links import link_issue, normalize_panel_link, target_key, valid_link
from bot.payloads import extract_links
from conftest import payload, receive_and_run


FULL_TARGETS = [
    ("instagram", "profile", "https://www.instagram.com/sampleuser/?igsh=Example#share"),
    ("tiktok", "profile", "https://www.tiktok.com/@sampleuser/?lang=tr#share"),
    ("tiktok", "content", "https://www.tiktok.com/@sampleuser/video/1234567890123456789/?share_item_id=1234567890123456789#share"),
    ("youtube", "profile", "https://www.youtube.com/@SampleUser/?sub_confirmation=1#about"),
    ("youtube", "content", "https://www.youtube.com/watch?v=AbC123_xYz0&list=PLExample#t=12"),
    ("youtube", "content", "https://youtu.be/AbC123_xYz0?t=12#share"),
    ("x", "profile", "https://www.x.com/sampleuser/?s=21#share"),
    ("twitter", "content", "https://mobile.twitter.com/sampleuser/status/123456789/video/1?s=21#share"),
    ("twitch", "profile", "https://www.twitch.tv/sampleuser/?referrer=share#about"),
    ("twitch", "content", "https://clips.twitch.tv/AmusedSlugExample/?tt_content=url#share"),
    ("twitch", "content", "https://www.twitch.tv/sampleuser/clip/AmusedSlugExample?filter=clips#share"),
    ("twitch", "content", "https://www.twitch.tv/videos/123456789?t=1h2m#share"),
    ("kick", "profile", "https://kick.com/sampleuser/?ref=share#about"),
    ("facebook", "profile", "https://www.facebook.com/profile.php?id=123456789&ref=share#about"),
    ("facebook", "content", "https://www.facebook.com/watch/?v=123456789&ref=sharing#share"),
    ("facebook", "content", "https://m.facebook.com/reel/123456789/?mibextid=Example#share"),
    ("facebook", "content", "https://www.facebook.com/story.php?story_fbid=123456789&id=987654321#share"),
    ("telegram", "profile", "https://t.me/sampleuser/?boost#share"),
    ("telegram", "profile", "https://telegram.me/+InviteAbC123?start=Example#share"),
    ("telegram", "content", "https://t.me/sampleuser/123?single#share"),
    ("telegram", "content", "https://t.me/c/123456789/456?thread=12#share"),
]


@pytest.mark.parametrize("platform,kind,url", FULL_TARGETS)
def test_complete_urls_keep_host_path_query_fragment_and_id_case(platform, kind, url):
    assert normalize_panel_link(url, platform) == url
    assert normalize_panel_link(normalize_panel_link(url, platform), platform) == url
    assert valid_link(url, platform, kind)
    assert extract_links({"post_datas": {"Link": url}})[platform] == url


HANDLE_TARGETS = [
    ("instagram", "https://www.instagram.com/sampleuser"),
    ("tiktok", "https://www.tiktok.com/@sampleuser"),
    ("youtube", "https://www.youtube.com/@sampleuser"),
    ("x", "https://x.com/sampleuser"),
    ("twitter", "https://x.com/sampleuser"),
    ("twitch", "https://www.twitch.tv/sampleuser"),
    ("kick", "https://kick.com/sampleuser"),
    ("facebook", "https://www.facebook.com/sampleuser"),
    ("telegram", "https://t.me/sampleuser"),
]


@pytest.mark.parametrize("platform,expected", HANDLE_TARGETS)
@pytest.mark.parametrize("raw", ["sampleuser", "@sampleuser"])
def test_known_platform_usernames_are_completed(platform, expected, raw):
    assert normalize_panel_link(raw, platform) == expected
    assert valid_link(raw, platform, "profile")


@pytest.mark.parametrize("platform,url", [
    ("tiktok", "www.tiktok.com/@sampleuser/video/1234567890123456789/?lang=tr#share"),
    ("youtube", "www.youtube.com/watch?v=AbC123_xYz0&list=PLExample#share"),
    ("x", "x.com/sampleuser/status/123456789?s=21#share"),
    ("twitch", "clips.twitch.tv/AmusedSlugExample?tt_content=url#share"),
    ("kick", "kick.com/sampleuser/?ref=share#about"),
    ("facebook", "www.facebook.com/watch/?v=123456789&ref=sharing#share"),
    ("telegram", "t.me/sampleuser/123?single#share"),
])
def test_missing_protocol_is_completed_without_removing_url_parts(platform, url):
    assert normalize_panel_link(url, platform) == "https://" + url


@pytest.mark.parametrize("platform,raw,expected", [
    ("tiktok", "@sampleuser/video/1234567890123456789", "https://www.tiktok.com/@sampleuser/video/1234567890123456789"),
    ("youtube", "watch?v=AbC123_xYz0", "https://www.youtube.com/watch?v=AbC123_xYz0"),
    ("youtube", "shorts/AbC123_xYz0", "https://www.youtube.com/shorts/AbC123_xYz0"),
    ("x", "sampleuser/status/123456789", "https://x.com/sampleuser/status/123456789"),
    ("twitch", "videos/123456789", "https://www.twitch.tv/videos/123456789"),
    ("facebook", "watch/?v=123456789", "https://www.facebook.com/watch/?v=123456789"),
    ("telegram", "sampleuser/123", "https://t.me/sampleuser/123"),
])
def test_known_content_paths_are_completed_without_guessing_identifiers(platform, raw, expected):
    assert normalize_panel_link(raw, platform) == expected
    assert valid_link(raw, platform, "content")


@pytest.mark.parametrize("field,platform,expected", [
    ("twitter_link", "twitter", "https://x.com/sampleuser"),
    ("x_link", "x", "https://x.com/sampleuser"),
    ("twitch_link", "twitch", "https://www.twitch.tv/sampleuser"),
    ("kick_link", "kick", "https://kick.com/sampleuser"),
    ("facebook_link", "facebook", "https://www.facebook.com/sampleuser"),
    ("telegram", "telegram", "https://t.me/sampleuser"),
])
def test_platform_buyer_fields_are_read_without_inventing_other_platform_targets(field, platform, expected):
    links = extract_links({field: "@sampleuser"})
    assert links[platform] == expected
    assert "instagram" not in links and "tiktok" not in links


@pytest.mark.parametrize("label,platform,expected", [
    ("Twitch", "twitch", "https://www.twitch.tv/sampleuser"),
    ("Telegram", "telegram", "https://t.me/sampleuser"),
    ("YouTube Kanalı", "youtube", "https://www.youtube.com/@sampleuser"),
])
def test_platform_names_in_customer_form_labels_are_respected(label, platform, expected):
    links = extract_links({"post_datas": {label: "@sampleuser"}})
    assert links[platform] == expected and "instagram" not in links


@pytest.mark.parametrize("platform,left,right", [
    ("youtube", "https://www.youtube.com/watch?v=AbC123_xYz0", "https://www.youtube.com/watch?v=abC123_xYz0"),
    ("facebook", "https://www.facebook.com/profile.php?id=123", "https://www.facebook.com/profile.php?id=456"),
    ("facebook", "https://www.facebook.com/watch/?v=123", "https://www.facebook.com/watch/?v=456"),
    ("facebook", "https://www.facebook.com/story.php?story_fbid=123&id=987", "https://www.facebook.com/story.php?story_fbid=456&id=987"),
    ("twitch", "https://clips.twitch.tv/embed?clip=AmusedSlugOne", "https://clips.twitch.tv/embed?clip=AmusedSlugTwo"),
    ("twitch", "https://player.twitch.tv/?video=123", "https://player.twitch.tv/?video=456"),
])
def test_required_query_identifiers_are_retained_in_same_target_checks(platform, left, right):
    assert valid_link(left, platform, "profile" if "profile.php" in left else "content")
    assert valid_link(right, platform, "profile" if "profile.php" in right else "content")
    assert target_key(left, platform) != target_key(right, platform)


@pytest.mark.parametrize("platform,url", [
    ("tiktok", "https://www.tiktok.com/@sampleuser/video/1234567890123456789/"),
    ("youtube", "https://www.youtube.com/watch?v=AbC123_xYz0"),
    ("x", "https://www.x.com/sampleuser/status/123456789"),
    ("twitch", "https://www.twitch.tv/videos/123456789"),
    ("kick", "https://kick.com/sampleuser/"),
    ("facebook", "https://www.facebook.com/watch/?v=123456789"),
    ("telegram", "https://t.me/sampleuser/123"),
])
def test_tracking_and_fragments_do_not_create_a_second_target(platform, url):
    separator = "&" if "?" in url else "?"
    shared = url + separator + "utm_source=share#share"
    assert normalize_panel_link(shared, platform) == shared
    assert target_key(shared, platform) == target_key(url, platform)


@pytest.mark.parametrize("platform,url", [
    ("tiktok", "https://vm.tiktok.com/Example/?share=1#share"),
    ("tiktok", "https://vt.tiktok.com/Example/?share=1#share"),
])
def test_unresolved_short_urls_are_preserved_but_not_submitted(platform, url):
    assert normalize_panel_link(url, platform) == url
    assert link_issue(url, platform) == "link_short"
    assert not valid_link(url, platform)


@pytest.mark.parametrize("platform,kind,url", [
    ("tiktok", "content", "https://www.tiktok.com/@sampleuser/video/1234567890123456789/?lang=tr#share"),
    ("youtube", "content", "https://www.youtube.com/watch?v=AbC123_xYz0&list=PLExample#t=12"),
    ("x", "content", "https://mobile.twitter.com/sampleuser/status/123456789/video/1?s=21#share"),
    ("twitch", "content", "https://clips.twitch.tv/AmusedSlugExample/?tt_content=url#share"),
    ("kick", "profile", "https://kick.com/sampleuser/?ref=share#about"),
    ("facebook", "content", "https://www.facebook.com/watch/?v=123456789&ref=sharing#share"),
    ("telegram", "content", "https://t.me/sampleuser/123?single#share"),
])
def test_panel_receives_the_complete_customer_url_for_every_platform(rig, platform, kind, url):
    binding = rig.store.setting("binding:10")
    binding["components"][0].update(platform=platform, target_type=kind)
    rig.store.set_setting("binding:10", binding)
    order = receive_and_run(rig, 1, url)
    assert order["state"] == "submitted"
    assert order["parts"][0]["link"] == order["link"] == url
    assert len(rig.panels.adds) == 1 and rig.panels.adds[0][1] == url


@pytest.mark.parametrize("platform,url", [
    ("youtube", "https://www.youtube.com/watch?v=AbC123_xYz0"),
    ("x", "https://x.com/sampleuser/status/123456789"),
    ("twitch", "https://www.twitch.tv/videos/123456789"),
    ("kick", "https://kick.com/sampleuser/"),
    ("facebook", "https://www.facebook.com/watch/?v=123456789"),
    ("telegram", "https://t.me/sampleuser/123"),
])
def test_preserving_share_parameters_does_not_bypass_the_active_order(rig, platform, url):
    binding = rig.store.setting("binding:10")
    binding["name"] = "Örnek hedef"
    binding["components"][0].update(platform=platform, target_type="auto")
    rig.store.set_setting("binding:10", binding)
    first = receive_and_run(rig, 1, url)
    shared = url + ("&" if "?" in url else "?") + "utm_source=share#share"
    second = receive_and_run(rig, 2, shared)
    assert first["state"] == "submitted" and second["state"] == "waiting"
    assert len(rig.panels.adds) == 1 and first["target"] == second["target"]


def test_youtube_only_buyer_field_cannot_start_an_instagram_purchase(rig):
    data = payload(1)
    data.pop("post_datas")
    data["youtube_link"] = "@sampleuser"
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    saved = rig.store.get(order["id"])
    assert saved["state"] == "review" and saved["reason_code"] == "link_missing"
    assert saved["customer_inputs"] == ["@sampleuser"]
    assert saved["input_platforms"] == {"@sampleuser": ["youtube"]}
    assert not rig.panels.adds and not rig.panels.rate_calls


def test_youtube_mapping_submits_the_scoped_buyer_field(rig):
    binding = rig.store.setting("binding:10")
    binding["components"][0].update(platform="youtube", target_type="profile")
    rig.store.set_setting("binding:10", binding)
    data = payload(1)
    data.pop("post_datas")
    data["youtube_link"] = "@sampleuser"
    order, _ = rig.engine.receive(data)
    rig.engine.execute(order["id"])
    saved = rig.store.get(order["id"])
    assert saved["state"] == "submitted"
    assert len(rig.panels.adds) == 1
    assert rig.panels.adds[0][1] == "https://www.youtube.com/@sampleuser"


@pytest.mark.parametrize("platform,url,persisted_key", [
    ("tiktok", "https://www.tiktok.com/@SampleUser/?lang=tr#share", "tiktok.com/@sampleuser"),
    ("youtube", "https://m.youtube.com/watch?v=AbC123_xYz0&feature=share", "youtube.com/watch?v=AbC123_xYz0"),
    ("x", "https://mobile.twitter.com/SampleUser/?s=21#share", "x.com/sampleuser?s=21"),
    ("twitch", "https://www.twitch.tv/SampleUser/?utm_source=share#about", "twitch.tv/SampleUser"),
    ("kick", "https://www.kick.com/SampleUser/?ref=share#about", "kick.com/SampleUser?ref=share"),
    ("facebook", "https://m.facebook.com/profile.php?id=123&ref=share#about", "facebook.com/profile.php?id=123&ref=share"),
    ("telegram", "https://telegram.me/SampleUser/?start=Example#share", "t.me/SampleUser?start=Example"),
])
def test_mobile_www_and_alias_urls_keep_previously_persisted_comparison_keys(platform, url, persisted_key):
    assert target_key(url, platform) == persisted_key
