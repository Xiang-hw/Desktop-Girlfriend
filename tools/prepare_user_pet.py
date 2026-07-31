"""
本模块将用户私有的姿态、走路、拖拽和摸头图集转换为桌宠运行素材。

职责范围：
- 按四列两行拆分站立、挥手、跑动、自拍、开心、坐下、睡眠和惊讶姿态；
- 将姿态统一到 560×500 透明画布，并保持站姿高度与脚底锚点一致；
- 通过轻微位移和缩放建立可运行的待机、走动、坐下、睡眠和自拍序列；
- 使用独立六帧拖拽图集和两帧害羞摸头图集，避免复用普通站姿；
- 将结果写入本机私有的 user_assets/pet，并保留原始生成图集。
- 只有首张标准角色形象得到用户确认后才允许批量生成动作；走路生成后仍需单独预览确认。

输入图集必须是 RGBA PNG，姿态顺序固定为从左到右、从上到下八格。
本模块不会修改输入图片、不访问网络，也不会把私人素材复制到其他目录。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from onepic_desktop_pet.workflow import WorkflowError, require_character_approved


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "user_assets"
    / "generated"
    / "user_pet_v2"
    / "poses-alpha.png"
)
DEFAULT_WALK_INPUT = (
    PROJECT_ROOT
    / "user_assets"
    / "generated"
    / "user_pet_v2"
    / "walk-physical-v3-fixed-alpha.png"
)
DEFAULT_DRAG_INPUT = (
    PROJECT_ROOT
    / "user_assets"
    / "generated"
    / "user_pet_v3"
    / "drag-alpha-v2.png"
)
DEFAULT_SHY_INPUT = (
    PROJECT_ROOT
    / "user_assets"
    / "generated"
    / "user_pet_v3"
    / "shy-alpha.png"
)
DEFAULT_DRAG_TRANSITION_INPUT = (
    PROJECT_ROOT
    / "user_assets"
    / "generated"
    / "user_pet_v3"
    / "drag-transition-alpha.png"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "user_assets" / "pet"
V4_ROOT = PROJECT_ROOT / "user_assets" / "generated" / "user_pet_v4"
DEFAULT_V4_BASE_INPUT = V4_ROOT / "base-interactions-final-alpha.png"
DEFAULT_V4_IDLE_INPUT = V4_ROOT / "idle-lettered-final-alpha.png"
DEFAULT_V4_EXPRESSION_INPUT = V4_ROOT / "expressions-lettered-alpha.png"
DEFAULT_V4_SIT_INPUT = V4_ROOT / "sit-lettered-final-alpha.png"
DEFAULT_V4_SLEEP_INPUT = V4_ROOT / "sleep-lettered-final-alpha.png"
DEFAULT_V4_WALK_INPUT = V4_ROOT / "walk-alpha-v2.png"
DEFAULT_V4_DRAG_INPUT = V4_ROOT / "drag-no-hat-lettered-final-alpha.png"
DEFAULT_V4_SELFIE_INPUT = V4_ROOT / "selfie-phone-alpha.png"
CANVAS_SIZE = (560, 500)
PADDING = 16
STANDING_HEIGHT = 450
SEATED_HEIGHT = 316
WALK_PHASES = (
    "contact_right",
    "down_right",
    "passing_left",
    "up_left",
    "contact_left",
    "down_left",
    "passing_right",
    "up_right",
)
WALK_MOTION_FACTORS = (0.55, 0.75, 1.15, 1.55, 0.55, 0.75, 1.15, 1.55)


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """返回可见像素边界，拒绝完全透明的单元格。"""

    bbox = image.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if bbox is None:
        raise ValueError("图集单元格不包含可见像素")
    return bbox


def split_horizontal_sheet(sheet: Image.Image, count: int) -> list[Image.Image]:
    """按透明竖向间隔识别连续帧，并把邻近的小型独立细节并入主体帧。"""

    alpha = sheet.getchannel("A")
    occupied_columns = [
        x
        for x in range(sheet.width)
        if alpha.crop((x, 0, x + 1, sheet.height)).getextrema()[1] > 8
    ]
    spans: list[tuple[int, int]] = []
    if occupied_columns:
        start = previous = occupied_columns[0]
        for x in occupied_columns[1:]:
            if x > previous + 1:
                spans.append((start, previous + 1))
                start = x
            previous = x
        spans.append((start, previous + 1))

    minimum_frame_width = max(2, sheet.width // max(1, count * 20))
    small_spans = [span for span in spans if span[1] - span[0] < minimum_frame_width]
    spans = [span for span in spans if span[1] - span[0] >= minimum_frame_width]
    for small_left, small_right in small_spans:
        if not spans:
            break
        nearest_index = min(
            range(len(spans)),
            key=lambda index: min(
                abs(small_right - spans[index][0]),
                abs(small_left - spans[index][1]),
            ),
        )
        left, right = spans[nearest_index]
        spans[nearest_index] = (min(left, small_left), max(right, small_right))
    spans.sort()
    if len(spans) != count:
        raise ValueError(
            f"横向图集应包含 {count} 个由透明间隔分开的帧，"
            f"实际识别到 {len(spans)} 个"
        )
    return [sheet.crop((left, 0, right, sheet.height)) for left, right in spans]


def sequence_scale(
    images: list[Image.Image],
    target_height: int = STANDING_HEIGHT,
) -> float:
    """为同一动作的全部帧计算统一缩放比例。"""

    boxes = [alpha_bbox(image) for image in images]
    anchor_height = boxes[0][3] - boxes[0][1]
    desired = target_height / anchor_height
    max_width = CANVAS_SIZE[0] - PADDING * 2
    max_height = CANVAS_SIZE[1] - PADDING * 2
    fit_limits = [
        min(max_width / (right - left), max_height / (bottom - top))
        for left, top, right, bottom in boxes
    ]
    return min(desired, *fit_limits)


def normalize_sequence_frame(
    image: Image.Image,
    scale: float,
    baseline_y: int | None = None,
) -> Image.Image:
    """按动作公共比例放入统一透明画布，可保留相对离地高度。"""

    bbox = alpha_bbox(image)
    cropped = image.crop(bbox)
    target_size = (
        max(1, round(cropped.width * scale)),
        max(1, round(cropped.height * scale)),
    )
    resized = cropped.resize(target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    x = (CANVAS_SIZE[0] - resized.width) // 2
    bottom = CANVAS_SIZE[1] - PADDING
    if baseline_y is not None:
        bottom -= round((baseline_y - bbox[3]) * scale)
    y = bottom - resized.height
    canvas.alpha_composite(resized, (x, y))
    return canvas


def save_sequence(
    images: list[Image.Image],
    output_root: Path,
    directory: str,
    prefix: str,
    preserve_vertical_offset: bool = False,
    target_anchor_height: int = STANDING_HEIGHT,
) -> list[str]:
    """按动作公共比例保存连续帧并返回相对路径。"""

    scale = sequence_scale(images, target_height=target_anchor_height)
    baseline_y = (
        max(alpha_bbox(image)[3] for image in images)
        if preserve_vertical_offset
        else None
    )
    paths: list[str] = []
    for index, image in enumerate(images, start=1):
        relative = f"{directory}/{prefix}_{index:02d}.png"
        output_path = output_root / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalize_sequence_frame(image, scale, baseline_y=baseline_y).save(
            output_path,
            "PNG",
            optimize=True,
        )
        paths.append(relative)
    return paths


def split_transparent_row(row: Image.Image, count: int) -> list[Image.Image]:
    """按透明列间隔拆分一行姿态，避免宽坐姿或睡姿被等宽边界裁切。"""

    alpha = row.getchannel("A")
    occupied = [
        x
        for x in range(row.width)
        if alpha.crop((x, 0, x + 1, row.height)).getextrema()[1] > 8
    ]
    spans: list[tuple[int, int]] = []
    if occupied:
        start = previous = occupied[0]
        for x in occupied[1:]:
            if x > previous + 1:
                spans.append((start, previous + 1))
                start = x
            previous = x
        spans.append((start, previous + 1))

    minimum_width = max(2, row.width // (count * 20))
    small = [span for span in spans if span[1] - span[0] < minimum_width]
    spans = [span for span in spans if span[1] - span[0] >= minimum_width]
    for small_left, small_right in small:
        if not spans:
            break
        nearest = min(
            range(len(spans)),
            key=lambda index: min(
                abs(small_right - spans[index][0]),
                abs(small_left - spans[index][1]),
            ),
        )
        left, right = spans[nearest]
        spans[nearest] = (min(left, small_left), max(right, small_right))
    spans.sort()
    if len(spans) != count:
        raise ValueError(f"一行应包含 {count} 个姿态，实际识别到 {len(spans)} 个")
    return [row.crop((left, 0, right, row.height)) for left, right in spans]


def find_transparent_row_split(sheet: Image.Image) -> int:
    """在图集中央寻找两排行为之间的透明横向留白。"""

    alpha = sheet.getchannel("A")
    start = round(sheet.height * 0.35)
    end = round(sheet.height * 0.65)
    counts = {
        y: sum(
            1
            for x in range(sheet.width)
            if alpha.getpixel((x, y)) > 8
        )
        for y in range(start, end)
    }
    minimum_y = min(counts, key=counts.get)
    low_pixel_threshold = max(8, sheet.width // 100)
    split = minimum_y
    while split + 1 < end and counts[split + 1] <= low_pixel_threshold:
        split += 1
    return split + 1


def split_pose_sheet(sheet: Image.Image) -> dict[str, Image.Image]:
    """按固定四列两行拆分八种用户姿态。"""

    names = (
        "idle",
        "wave",
        "happy",
        "selfie",
        "surprised",
        "annoyed",
        "sit",
        "sleep",
    )
    row_split = find_transparent_row_split(sheet)
    rows = (
        sheet.crop((0, 0, sheet.width, row_split)),
        sheet.crop((0, row_split, sheet.width, sheet.height)),
    )
    cells: dict[str, Image.Image] = {}
    for row_index, row in enumerate(rows):
        for column, cell in enumerate(split_transparent_row(row, 4)):
            name = names[row_index * 4 + column]
            alpha_bbox(cell)
            cells[name] = cell
    return cells


def split_walk_sheet(sheet: Image.Image) -> list[Image.Image]:
    """按从上到下、从左到右顺序拆分八相位走路循环。"""

    row_split = find_transparent_row_split(sheet)
    rows = (
        sheet.crop((0, 0, sheet.width, row_split)),
        sheet.crop((0, row_split, sheet.width, sheet.height)),
    )
    frames = [frame for row in rows for frame in split_transparent_row(row, 4)]
    for frame in frames:
        alpha_bbox(frame)
    return frames


def normalize_pose(
    image: Image.Image,
    target_height: int,
    *,
    bottom_offset: int = 0,
    horizontal_offset: int = 0,
) -> Image.Image:
    """将一个姿态按指定高度置于统一透明画布。"""

    cropped = image.crop(alpha_bbox(image))
    scale = target_height / cropped.height
    max_width = CANVAS_SIZE[0] - PADDING * 2
    if cropped.width * scale > max_width:
        scale = max_width / cropped.width
    size = (
        max(1, round(cropped.width * scale)),
        max(1, round(cropped.height * scale)),
    )
    resized = cropped.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    x = (CANVAS_SIZE[0] - resized.width) // 2 + horizontal_offset
    y = CANVAS_SIZE[1] - PADDING - bottom_offset - resized.height
    canvas.alpha_composite(resized, (x, y))
    return canvas


def save_frames(
    output_root: Path,
    directory: str,
    prefix: str,
    frames: list[Image.Image],
) -> list[str]:
    """保存一组 RGBA 帧并返回相对于私有宠物目录的路径。"""

    paths: list[str] = []
    for index, frame in enumerate(frames, start=1):
        relative = f"{directory}/{prefix}_{index:02d}.png"
        path = output_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.save(path, "PNG", optimize=True)
        paths.append(relative)
    return paths


def repeated_pose(
    pose: Image.Image,
    height: int,
    offsets: list[tuple[int, int]],
) -> list[Image.Image]:
    """用轻微水平和垂直偏移形成简单连续动画。"""

    return [
        normalize_pose(
            pose,
            height,
            horizontal_offset=x_offset,
            bottom_offset=bottom_offset,
        )
        for x_offset, bottom_offset in offsets
    ]


def validate_walk_cycle(frames: list[Image.Image]) -> None:
    """检查走路循环的尺寸、离地、相邻差异和首尾过渡。"""

    if len(frames) != 8:
        raise ValueError(f"走路循环必须包含 8 帧，实际为 {len(frames)} 帧")
    boxes = [alpha_bbox(frame) for frame in frames]
    heights = [bottom - top for _left, top, _right, bottom in boxes]
    bottoms = [bottom for _left, _top, _right, bottom in boxes]
    if max(heights) - min(heights) > 8:
        raise ValueError("走路帧人物高度变化超过 8 像素")
    if max(bottoms) - min(bottoms) < 4:
        raise ValueError("走路帧没有可见的脚底接触与离地变化")

    difference_ratios: list[float] = []
    for current, following in zip(frames, frames[1:] + frames[:1], strict=True):
        difference = ImageChops.difference(current, following).convert("L")
        changed = difference.point(lambda value: 255 if value > 12 else 0)
        changed_pixels = changed.histogram()[255]
        visible_pixels = max(1, sum(current.getchannel("A").histogram()[1:]))
        difference_ratios.append(changed_pixels / visible_pixels)
    if any(ratio < 0.08 for ratio in difference_ratios):
        raise ValueError("走路循环存在过于相似的相邻帧")
    if difference_ratios[-1] > max(difference_ratios[:-1]) * 1.75:
        raise ValueError("走路动画第八帧回到第一帧时跳变过大")


def prepare_user_pet(
    input_path: Path,
    walk_input_path: Path,
    drag_input_path: Path,
    shy_input_path: Path,
    drag_transition_input_path: Path,
    output_root: Path,
) -> dict[str, object]:
    """在角色确认门禁通过后生成私有桌宠帧、图标和清单。"""

    require_character_approved(PROJECT_ROOT / "user_assets" / "workflow.json")

    with Image.open(input_path) as source:
        sheet = source.convert("RGBA")
    with Image.open(walk_input_path) as source:
        walk_sheet = source.convert("RGBA")
    with Image.open(drag_input_path) as source:
        drag_sheet = source.convert("RGBA")
    with Image.open(shy_input_path) as source:
        shy_sheet = source.convert("RGBA")
    with Image.open(drag_transition_input_path) as source:
        drag_transition_sheet = source.convert("RGBA")
    poses = split_pose_sheet(sheet)
    walk_frames = split_walk_sheet(walk_sheet)
    drag_split = find_transparent_row_split(drag_sheet)
    drag_frames = [
        *split_transparent_row(drag_sheet.crop((0, 0, drag_sheet.width, drag_split)), 3),
        *split_transparent_row(
            drag_sheet.crop((0, drag_split, drag_sheet.width, drag_sheet.height)),
            3,
        ),
    ]
    shy_frames = split_transparent_row(shy_sheet, 2)
    transition_split = find_transparent_row_split(drag_transition_sheet)
    pickup_frames = split_transparent_row(
        drag_transition_sheet.crop(
            (0, 0, drag_transition_sheet.width, transition_split)
        ),
        3,
    )
    drop_frames = split_transparent_row(
        drag_transition_sheet.crop(
            (
                0,
                transition_split,
                drag_transition_sheet.width,
                drag_transition_sheet.height,
            )
        ),
        3,
    )

    animations: dict[str, list[str]] = {}
    animations["idle"] = save_frames(
        output_root,
        "idle",
        "idle",
        repeated_pose(poses["idle"], STANDING_HEIGHT, [(0, 0), (0, 1), (1, 2), (0, 2), (-1, 1), (0, 0)]),
    )
    # 图像模型容易让后半步继续使用同一条前腿。后四相位严格镜像前四
    # 相位，确保左右落脚、承重、迈过和抬升形成对称循环。
    walk_frames = [
        *walk_frames[:4],
        *(ImageOps.mirror(frame) for frame in walk_frames[:4]),
    ]
    normalized_walk_frames = [
        normalize_pose(frame, STANDING_HEIGHT, bottom_offset=offset)
        for frame, offset in zip(
            walk_frames,
            (0, 1, 2, 4, 0, 1, 2, 4),
            strict=True,
        )
    ]
    validate_walk_cycle(normalized_walk_frames)
    animations["walk"] = save_frames(
        output_root,
        "walk",
        "walk",
        normalized_walk_frames,
    )
    normalized_walk_frames[0].save(
        output_root / "walk-preview.gif",
        save_all=True,
        append_images=normalized_walk_frames[1:],
        duration=90,
        loop=0,
        disposal=2,
    )
    animations["sit"] = save_frames(
        output_root,
        "sit",
        "sit",
        [
            normalize_pose(poses["idle"], 450),
            normalize_pose(poses["idle"], 405),
            normalize_pose(poses["idle"], 360),
            normalize_pose(poses["sit"], 335),
            normalize_pose(poses["sit"], 316),
        ],
    )
    animations["sleep"] = save_frames(
        output_root,
        "sleep",
        "sleep",
        [
            normalize_pose(poses["sit"], 316),
            normalize_pose(poses["sit"], 290),
            normalize_pose(poses["sleep"], 260),
            normalize_pose(poses["sleep"], 245),
            normalize_pose(poses["sleep"], 235),
        ],
    )
    animations["drag"] = save_frames(
        output_root,
        "interact",
        "drag",
        [
            normalize_pose(frame, 430, bottom_offset=18)
            for frame in drag_frames
        ],
    )
    animations["pickup"] = save_frames(
        output_root,
        "interact",
        "pickup",
        [normalize_pose(frame, STANDING_HEIGHT) for frame in pickup_frames],
    )
    animations["drop"] = save_frames(
        output_root,
        "interact",
        "drop",
        [normalize_pose(frame, STANDING_HEIGHT) for frame in drop_frames],
    )
    animations["selfie"] = save_frames(
        output_root,
        "interact",
        "selfie",
        repeated_pose(poses["selfie"], STANDING_HEIGHT, [(0, 0), (-1, 2), (1, 3), (0, 0)]),
    )

    affectionate_frames = [
        normalize_pose(frame, STANDING_HEIGHT)
        for frame in shy_frames
    ]
    animations["happy"] = save_frames(
        output_root,
        "expressions",
        "happy",
        affectionate_frames,
    )
    animations["shy"] = save_frames(
        output_root,
        "expressions",
        "shy",
        affectionate_frames,
    )

    single_poses = {
        "wave": "wave",
        "surprised": "surprised",
        "annoyed": "annoyed",
        "sleepy": "idle",
        "curious": "wave",
    }
    for state, pose_name in single_poses.items():
        directory = "interact" if state == "wave" else "expressions"
        animations[state] = save_frames(
            output_root,
            directory,
            state,
            [normalize_pose(poses[pose_name], STANDING_HEIGHT)],
        )

    icon_path = output_root / "icon.png"
    with Image.open(output_root / animations["idle"][0]) as idle:
        icon = idle.convert("RGBA")
        icon.thumbnail((128, 128), Image.Resampling.LANCZOS)
        icon_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        icon_canvas.alpha_composite(icon, ((128 - icon.width) // 2, (128 - icon.height) // 2))
        icon_canvas.save(icon_path, "PNG", optimize=True)

    manifest: dict[str, object] = {
        "sources": [
            input_path.relative_to(PROJECT_ROOT).as_posix(),
            walk_input_path.relative_to(PROJECT_ROOT).as_posix(),
            drag_input_path.relative_to(PROJECT_ROOT).as_posix(),
            shy_input_path.relative_to(PROJECT_ROOT).as_posix(),
            drag_transition_input_path.relative_to(PROJECT_ROOT).as_posix(),
        ],
        "canvas_size": list(CANVAS_SIZE),
        "target_standing_height": STANDING_HEIGHT,
        "walk_phases": list(WALK_PHASES),
        "walk_motion_factors": list(WALK_MOTION_FACTORS),
        "animations": animations,
        "icon": "icon.png",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def prepare_user_pet_v4(
    base_input_path: Path,
    idle_input_path: Path,
    expression_input_path: Path,
    sit_input_path: Path,
    sleep_input_path: Path,
    walk_input_path: Path,
    drag_input_path: Path,
    selfie_input_path: Path,
    output_root: Path,
) -> dict[str, object]:
    """按已确认帧结构拆分第四版专属角色图集。"""

    require_character_approved(PROJECT_ROOT / "user_assets" / "workflow.json")
    paths = (
        base_input_path,
        idle_input_path,
        expression_input_path,
        sit_input_path,
        sleep_input_path,
        walk_input_path,
        drag_input_path,
        selfie_input_path,
    )
    sheets: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as source:
            sheets.append(source.convert("RGBA"))
    (
        base_sheet,
        idle_sheet,
        expression_sheet,
        sit_sheet,
        sleep_sheet,
        walk_sheet,
        drag_sheet,
        selfie_sheet,
    ) = sheets

    animations: dict[str, list[str]] = {}
    base_frames = split_horizontal_sheet(base_sheet, 2)
    animations["wave"] = save_sequence(
        [base_frames[0]], output_root, "interact", "wave"
    )
    animations["idle"] = save_sequence(
        split_horizontal_sheet(idle_sheet, 6),
        output_root,
        "idle",
        "idle",
    )
    expression_paths = save_sequence(
        split_horizontal_sheet(expression_sheet, 6),
        output_root,
        "expressions",
        "expression",
    )
    for name, relative in zip(
        ("happy", "shy", "surprised", "annoyed", "sleepy", "curious"),
        expression_paths,
        strict=True,
    ):
        animations[name] = [relative]
    animations["sit"] = save_sequence(
        split_horizontal_sheet(sit_sheet, 5),
        output_root,
        "sit",
        "sit",
    )
    animations["sleep"] = save_sequence(
        split_horizontal_sheet(sleep_sheet, 5),
        output_root,
        "sleep",
        "sleep",
        target_anchor_height=SEATED_HEIGHT,
    )
    animations["walk"] = save_sequence(
        split_horizontal_sheet(walk_sheet, 8),
        output_root,
        "walk",
        "walk",
        preserve_vertical_offset=True,
    )
    animations["drag"] = save_sequence(
        split_horizontal_sheet(drag_sheet, 3),
        output_root,
        "interact",
        "drag",
        preserve_vertical_offset=True,
    )
    animations["selfie"] = save_sequence(
        split_horizontal_sheet(selfie_sheet, 6),
        output_root,
        "interact",
        "selfie",
    )

    icon_path = output_root / "icon.png"
    with Image.open(output_root / animations["idle"][0]) as idle:
        icon = idle.convert("RGBA")
        icon.thumbnail((128, 128), Image.Resampling.LANCZOS)
        icon_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        icon_canvas.alpha_composite(
            icon,
            ((128 - icon.width) // 2, (128 - icon.height) // 2),
        )
        icon_canvas.save(icon_path, "PNG", optimize=True)

    manifest: dict[str, object] = {
        "sources": [path.relative_to(PROJECT_ROOT).as_posix() for path in paths],
        "canvas_size": list(CANVAS_SIZE),
        "target_standing_height": STANDING_HEIGHT,
        "animations": animations,
        "icon": "icon.png",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="从八姿态图集生成私有桌宠素材")
    parser.add_argument("--v4-base-input", type=Path, default=DEFAULT_V4_BASE_INPUT)
    parser.add_argument("--v4-idle-input", type=Path, default=DEFAULT_V4_IDLE_INPUT)
    parser.add_argument(
        "--v4-expression-input",
        type=Path,
        default=DEFAULT_V4_EXPRESSION_INPUT,
    )
    parser.add_argument("--v4-sit-input", type=Path, default=DEFAULT_V4_SIT_INPUT)
    parser.add_argument(
        "--v4-sleep-input",
        type=Path,
        default=DEFAULT_V4_SLEEP_INPUT,
    )
    parser.add_argument("--v4-walk-input", type=Path, default=DEFAULT_V4_WALK_INPUT)
    parser.add_argument("--v4-drag-input", type=Path, default=DEFAULT_V4_DRAG_INPUT)
    parser.add_argument(
        "--v4-selfie-input",
        type=Path,
        default=DEFAULT_V4_SELFIE_INPUT,
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--walk-input", type=Path, default=DEFAULT_WALK_INPUT)
    parser.add_argument("--drag-input", type=Path, default=DEFAULT_DRAG_INPUT)
    parser.add_argument("--shy-input", type=Path, default=DEFAULT_SHY_INPUT)
    parser.add_argument(
        "--drag-transition-input",
        type=Path,
        default=DEFAULT_DRAG_TRANSITION_INPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """执行私有素材生成并打印摘要。"""

    args = parse_args()
    v4_paths = (
        args.v4_base_input.resolve(),
        args.v4_idle_input.resolve(),
        args.v4_expression_input.resolve(),
        args.v4_sit_input.resolve(),
        args.v4_sleep_input.resolve(),
        args.v4_walk_input.resolve(),
        args.v4_drag_input.resolve(),
        args.v4_selfie_input.resolve(),
    )
    if all(path.is_file() for path in v4_paths):
        try:
            manifest = prepare_user_pet_v4(
                *v4_paths,
                args.output.resolve(),
            )
        except WorkflowError as exc:
            print(f"流程未通过：{exc}")
            return 2
        frame_count = sum(len(paths) for paths in manifest["animations"].values())
        print(f"已生成 {frame_count} 个第四版私有桌宠帧：{args.output.resolve()}")
        return 0

    input_path = args.input.resolve()
    walk_input_path = args.walk_input.resolve()
    drag_input_path = args.drag_input.resolve()
    shy_input_path = args.shy_input.resolve()
    drag_transition_input_path = args.drag_transition_input.resolve()
    output_root = args.output.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"找不到八姿态透明图集：{input_path}")
    if not walk_input_path.is_file():
        raise FileNotFoundError(f"找不到八相位走路图集：{walk_input_path}")
    if not drag_input_path.is_file():
        raise FileNotFoundError(f"找不到六帧拖拽图集：{drag_input_path}")
    if not shy_input_path.is_file():
        raise FileNotFoundError(f"找不到两帧害羞摸头图集：{shy_input_path}")
    if not drag_transition_input_path.is_file():
        raise FileNotFoundError(
            f"找不到提起与落地过渡图集：{drag_transition_input_path}"
        )
    try:
        manifest = prepare_user_pet(
            input_path,
            walk_input_path,
            drag_input_path,
            shy_input_path,
            drag_transition_input_path,
            output_root,
        )
    except WorkflowError as exc:
        print(f"流程未通过：{exc}")
        return 2
    frame_count = sum(len(paths) for paths in manifest["animations"].values())
    print(f"已生成 {frame_count} 个私有桌宠帧：{output_root}")
    print("下一步必须运行 onepic_workflow.py walk-review，并让用户查看 GIF。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
