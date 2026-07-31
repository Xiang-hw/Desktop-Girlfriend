"""
本模块验证桌面宠物窗口的连续帧控制、表情符号、轮廓遮罩、DPI 渲染缓存、分区互动和自拍成片。

测试在 Qt 的离屏平台中创建真实 PetWindow，但不显示到用户桌面、不写配置文件，
也不启动系统托盘。重点检查透明区域不会形成完整矩形点击区、重复绘制能够复用缓存，
以及坐下过渡可正向停在末帧并反向回到站立帧。
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.behavior import PetState, StateDecision
from onepic_desktop_pet.config import PetSettings
from onepic_desktop_pet.emotion_effects import emotion_effect_name
from onepic_desktop_pet.window import PetWindow


def _create_window() -> tuple[QApplication, PetWindow]:
    """创建或复用离屏 Qt 应用，并返回采用默认设置的宠物窗口。"""

    app = QApplication.instance() or QApplication([])
    window = PetWindow(PetSettings())
    window.show()
    app.processEvents()
    return app, window


def test_window_uses_character_mask_and_reuses_render_cache() -> None:
    app, window = _create_window()
    initial_render_count = len(window._render_cache)
    initial_mask_count = len(window._mask_cache)

    window._refresh_pixmap()

    assert not window.mask().isEmpty()
    assert window.mask().boundingRect().width() < window.width()
    assert len(window._render_cache) == initial_render_count
    assert len(window._mask_cache) == initial_mask_count
    window.close()
    window.deleteLater()
    app.processEvents()


def test_sit_animation_holds_then_reverses_to_standing_frame() -> None:
    app, window = _create_window()
    window.set_state(PetState.SIT)

    for _ in range(len(window._pixmaps[PetState.SIT])):
        window._animation_tick()

    assert window._frame_index == len(window._pixmaps[PetState.SIT]) - 1
    assert not window.animation_timer.isActive()

    window._reverse_transition_to_idle()
    for _ in range(len(window._pixmaps[PetState.SIT]) - 1):
        window._animation_tick()

    assert window._frame_index == 0
    assert not window.animation_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_pauses_briefly_when_turning_at_screen_edge() -> None:
    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.direction = -1
    window._frame_index = 3
    window.move(0, 0)
    window._screen_geometry = lambda: QRect(0, 0, 1000, 1000)

    window._movement_tick()

    assert window.direction == 1
    assert window._turn_paused
    assert window.turn_timer.isActive()
    assert not window.animation_timer.isActive()

    window._finish_turn()

    assert not window._turn_paused
    assert window.animation_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_vertical_offset_follows_footfall_frames() -> None:
    """行走起伏必须跟随连续帧，而不是由独立的慢速浮动计时器驱动。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    offsets = [window.label.y()]

    for _ in range(3):
        window._animation_tick()
        offsets.append(window.label.y())

    assert offsets == [1, 2, 1, 0]
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_uses_subpixel_phase_synced_speed(monkeypatch) -> None:
    """水平移动应亚像素累计，落脚阶段减速而不冻结，随后平滑加速。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.direction = 1
    window.move(100, 0)
    window._movement_x = 100.0
    window._last_movement_at = 10.0
    window._screen_geometry = lambda: QRect(0, 0, 1000, 1000)
    current_time = [10.016]
    monkeypatch.setattr(
        "onepic_desktop_pet.window.time.monotonic",
        lambda: current_time[0],
    )

    window._frame_index = 0
    window._movement_tick()
    assert round(window._movement_x, 2) == 100.45
    assert window.x() == 100

    current_time[0] = 10.032
    window._frame_index = 3
    window._movement_tick()
    assert window._movement_speed_pixels_per_second() == 62.5
    assert round(window._movement_x, 2) == 102.1
    assert window.x() == 102
    window.close()
    window.deleteLater()
    app.processEvents()


def test_walk_motion_curve_avoids_freeze_and_balances_both_steps() -> None:
    """移动曲线不应停顿后猛跳，且左右两个半步必须使用相同节奏。"""

    app, window = _create_window()

    assert min(window._walk_motion_factors) > 0.0
    assert max(window._walk_motion_factors) / min(window._walk_motion_factors) < 4
    assert window._walk_motion_factors[:4] == window._walk_motion_factors[4:]
    assert sum(window._walk_motion_factors) / 8 == 1.0

    window.close()
    window.deleteLater()
    app.processEvents()


def test_drag_state_uses_dedicated_suspended_animation() -> None:
    """私有拖拽状态应加载专用悬空素材，而不是回退到待机站立。"""

    app, window = _create_window()
    window.set_state(PetState.DRAG)

    display_state, _pixmap = window._current_source()
    assert display_state is PetState.DRAG
    assert len(window._pixmaps[PetState.DRAG]) == 3
    assert window.animation_timer.isActive()

    window.close()
    window.deleteLater()
    app.processEvents()


def test_interaction_states_have_reusable_emotion_symbols() -> None:
    """互动表情应使用独立符号层，换角色素材后仍然能够显示。"""

    expected = {
        PetState.HAPPY: "sparkle",
        PetState.SHY: "heart",
        PetState.SURPRISED: "exclamation",
        PetState.ANNOYED: "anger",
        PetState.SLEEPY: "sleep",
        PetState.CURIOUS: "question",
        PetState.SELFIE: "flash",
        PetState.DRAG: "sweat",
    }
    assert {state: emotion_effect_name(state) for state in expected} == expected
    assert emotion_effect_name(PetState.IDLE) is None


def test_emotion_symbol_timer_follows_current_state() -> None:
    """进入表情状态时符号应动画，恢复待机后必须停止计时器。"""

    app, window = _create_window()
    window.set_state(PetState.SURPRISED)
    assert window.effect_timer.isActive()
    assert not window.label.pixmap().isNull()

    window.set_state(PetState.IDLE)
    assert not window.effect_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_inactivity_progresses_from_sit_to_sleep() -> None:
    """超过睡眠阈值后仍应先完整坐下，再播放坐姿入睡序列。"""

    settings = PetSettings(inactive_sit_ms=10000, inactive_sleep_ms=20000)
    app = QApplication.instance() or QApplication([])
    window = PetWindow(settings)
    window._last_user_interaction = time.monotonic() - 21
    window.set_state(PetState.IDLE)

    window._state_timeout()
    assert window.state is PetState.SIT
    assert window._sleep_after_sit

    window._state_timeout()
    assert window.state is PetState.SLEEP
    assert not window._sleep_after_sit
    window.close()
    window.deleteLater()
    app.processEvents()


def test_manual_controls_trigger_sit_and_sleep_via_transition() -> None:
    """控制菜单应能手动坐下，并通过坐姿过渡进入睡眠。"""

    app, window = _create_window()

    window.trigger_sit()
    assert window.state is PetState.SIT
    assert window.state_timer.isActive()

    window.trigger_sleep()
    assert window.state is PetState.SIT
    assert window._sleep_after_sit
    window._state_timeout()
    assert window.state is PetState.SLEEP

    window.close()
    window.deleteLater()
    app.processEvents()


def test_context_menu_exposes_manual_sit_and_sleep_actions() -> None:
    """右键控制菜单应直接提供坐下和睡觉按钮。"""

    app, window = _create_window()
    menu = window._build_context_menu()
    labels = {action.text() for action in menu.actions()}

    assert "坐下" in labels
    assert "睡觉" in labels

    menu.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_pause_disables_running_but_keeps_ambient_state_timer() -> None:
    """暂停跑动时应进入生活状态并继续计时，而不是冻结在站立帧。"""

    app, window = _create_window()
    window.set_state(PetState.WALK)
    window.behavior.next_autonomous_state = (
        lambda _current, allow_walk: StateDecision(PetState.SIT, 2000)
    )

    window.set_paused(True)

    assert window.paused
    assert window.state is PetState.SIT
    assert window.state_timer.isActive()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_display_size_preset_updates_geometry_and_settings() -> None:
    """右键尺寸预设应立即改变窗口和标签尺寸，并写回设置对象。"""

    app, window = _create_window()
    window.set_display_height(280)

    assert window.settings.display_height == 280
    assert window.height() == 294
    assert window.label.height() == 288
    assert not window.mask().isEmpty()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_interaction_zones_map_head_face_body_and_camera() -> None:
    """窗口相对位置应稳定映射为四种点击区域。"""

    app, window = _create_window()
    center_x = window.label.x() + window.label.width() // 2
    assert window._interaction_zone(QPoint(center_x, 20)) == "head"
    assert (
        window._interaction_zone(
            QPoint(center_x, round(window.label.height() * 0.34))
        )
        == "face"
    )
    assert (
        window._interaction_zone(
            QPoint(
                window.label.x() + round(window.label.width() * 0.2),
                round(window.label.height() * 0.62),
            )
        )
        == "camera"
    )
    assert (
        window._interaction_zone(
            QPoint(center_x, round(window.label.height() * 0.7))
        )
        == "body"
    )
    window.close()
    window.deleteLater()
    app.processEvents()


def test_head_click_increases_affinity_and_repeated_body_poke_annoys() -> None:
    """摸头应提升亲密度，短时间连续戳身体应切换到轻微生气表情。"""

    app, window = _create_window()
    initial_affinity = window.mood.affinity
    head = QPoint(window.width() // 2, 20)
    body = QPoint(window.width() // 2, round(window.label.height() * 0.7))

    window._handle_click(head)
    assert window.mood.affinity == initial_affinity + 5
    assert window.state is PetState.HAPPY

    for _ in range(3):
        window._handle_click(body)
    assert window.state is PetState.ANNOYED
    assert window.mood.affinity < initial_affinity + 5
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_completion_does_not_show_photo_bubble() -> None:
    """手机自拍完成后只播放角色反应，不弹出原始照片。"""

    app, window = _create_window()
    window._selfie_photo = window._pixmaps[PetState.SELFIE][-1]
    window.set_state(PetState.SELFIE)
    window._finish_interaction()
    app.processEvents()

    assert not window.photo_bubble.isVisible()
    window.photo_bubble.hide()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_photo_uses_high_dpi_backing_pixels() -> None:
    """200% 缩放时横竖照片都应使用高分辨率像素并限制逻辑尺寸。"""

    app, window = _create_window()
    window._selfie_photo = window._pixmaps[PetState.SELFIE][-1]
    photo = window._scaled_selfie_photo(2.0)

    assert photo.devicePixelRatio() == 2.0
    assert max(photo.width(), photo.height()) >= 300
    assert round(photo.width() / photo.devicePixelRatio()) <= 150
    assert round(photo.height() / photo.devicePixelRatio()) <= 210
    window.close()
    window.deleteLater()
    app.processEvents()


def test_selfie_photo_is_positioned_near_visible_character() -> None:
    """照片应贴近人物不透明轮廓，而不是贴着含大块留白的窗口边缘。"""

    app, window = _create_window()
    window._selfie_photo = window._pixmaps[PetState.SELFIE][-1]
    window.move(500, 300)
    window._screen_geometry = lambda: QRect(0, 0, 1200, 900)
    window.set_state(PetState.SELFIE)
    window._show_photo_bubble()
    app.processEvents()

    character_left = window.x() + window.mask().boundingRect().left()
    visual_gap = character_left - (
        window.photo_bubble.x() + window.photo_bubble.width()
    )
    assert visual_gap == 8
    window.photo_bubble.hide()
    window.close()
    window.deleteLater()
    app.processEvents()
