"""
本模块检验最终私有桌面女友的素材清单、透明通道、连续帧数量和统一画布规格。
测试只读取 user_assets/pet 中已经通过人工验收的 PNG，不修改素材、不启动 GUI，
也不访问网络。演示角色已经从项目中移除，因此所有断言都针对当前专属女孩。
"""

import json
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "user_assets" / "pet" / "manifest.json"


def load_manifest() -> dict[str, object]:
    """读取最终私有素材清单。"""

    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def visible_bbox(relative: str) -> tuple[int, int, int, int]:
    """返回指定运行帧的非透明边界。"""

    with Image.open(MANIFEST_PATH.parent / relative) as image:
        bbox = image.getchannel("A").getbbox()
    assert bbox is not None
    return bbox


def test_private_manifest_assets_exist_and_are_transparent() -> None:
    manifest = load_manifest()
    expected_size = tuple(manifest["canvas_size"])
    animations = manifest["animations"]

    assert set(animations) == {
        "idle",
        "wave",
        "walk",
        "happy",
        "sit",
        "sleep",
        "selfie",
        "drag",
        "shy",
        "surprised",
        "annoyed",
        "sleepy",
        "curious",
    }
    assert len(animations["idle"]) == 6
    assert len(animations["walk"]) == 8
    assert len(animations["sit"]) == 5
    assert len(animations["sleep"]) == 5
    assert len(animations["drag"]) == 3
    assert len(animations["selfie"]) == 6
    assert sum(len(paths) for paths in animations.values()) == 40
    assert all(source.startswith("user_assets/") for source in manifest["sources"])

    for relative_paths in animations.values():
        for relative in relative_paths:
            path = MANIFEST_PATH.parent / relative
            assert path.is_file()
            with Image.open(path) as image:
                assert image.mode == "RGBA"
                assert image.size == expected_size
                assert image.getchannel("A").getextrema() == (0, 255)
                assert image.getchannel("A").getbbox() is not None


def test_private_icon_exists_and_is_transparent() -> None:
    manifest = load_manifest()
    icon_path = MANIFEST_PATH.parent / manifest["icon"]

    with Image.open(icon_path) as icon:
        assert icon.mode == "RGBA"
        assert icon.size == (128, 128)
        assert icon.getchannel("A").getextrema() == (0, 255)


def test_standing_frames_use_consistent_character_height() -> None:
    animations = load_manifest()["animations"]
    heights = []
    for state in (
        "idle",
        "wave",
        "happy",
        "shy",
        "surprised",
        "annoyed",
        "sleepy",
        "curious",
        "selfie",
    ):
        for relative in animations[state]:
            left, top, right, bottom = visible_bbox(relative)
            assert right > left
            heights.append(bottom - top)

    assert max(heights) - min(heights) <= 8


def test_walk_cycle_preserves_airborne_height() -> None:
    animations = load_manifest()["animations"]
    bottoms = [visible_bbox(relative)[3] for relative in animations["walk"]]

    assert max(bottoms) - min(bottoms) >= 4


def test_sit_and_sleep_sequences_lower_character_gradually() -> None:
    animations = load_manifest()["animations"]
    sit_heights = [
        visible_bbox(relative)[3] - visible_bbox(relative)[1]
        for relative in animations["sit"]
    ]
    sleep_heights = [
        visible_bbox(relative)[3] - visible_bbox(relative)[1]
        for relative in animations["sleep"]
    ]

    assert sit_heights[0] > sit_heights[-1]
    assert sleep_heights[0] > sleep_heights[2]


def test_drag_and_selfie_use_final_approved_frame_counts() -> None:
    animations = load_manifest()["animations"]

    assert animations["drag"] == [
        "interact/drag_01.png",
        "interact/drag_02.png",
        "interact/drag_03.png",
    ]
    assert animations["selfie"][-1] == "interact/selfie_06.png"
