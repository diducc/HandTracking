import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hand_tracker
from pyautogui import FailSafeException


def make_hand(
    extended=(),
    click=False,
    move=False,
    index_x=0.5,
    index_y=0.20,
    middle_x=0.5,
    middle_y=0.20,
    palm_x=0.5,
):
    """Build landmarks for the controller's rotation-independent pose checks."""
    landmarks = [SimpleNamespace(x=0.5, y=0.72) for _ in range(21)]
    landmarks[hand_tracker.HandMouseController.WRIST] = SimpleNamespace(x=0.5, y=0.8)
    landmarks[hand_tracker.HandMouseController.MIDDLE_MCP] = SimpleNamespace(x=palm_x, y=0.6)
    landmarks[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=0.1, y=0.5)

    fingers = (
        ("index", hand_tracker.HandMouseController.INDEX_TIP, hand_tracker.HandMouseController.INDEX_PIP),
        ("middle", hand_tracker.HandMouseController.MIDDLE_TIP, hand_tracker.HandMouseController.MIDDLE_PIP),
        ("ring", hand_tracker.HandMouseController.RING_TIP, hand_tracker.HandMouseController.RING_PIP),
        ("pinky", hand_tracker.HandMouseController.PINKY_TIP, hand_tracker.HandMouseController.PINKY_PIP),
    )
    for name, tip, pip in fingers:
        if name in extended:
            landmarks[pip] = SimpleNamespace(x=0.5, y=0.45)
            landmarks[tip] = SimpleNamespace(
                x=index_x if name == "index" else middle_x,
                y=index_y if name == "index" else middle_y,
            )
        else:
            landmarks[pip] = SimpleNamespace(x=0.5, y=0.65)
            landmarks[tip] = SimpleNamespace(x=0.5, y=0.72)

    if click:
        landmarks[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=0.51, y=0.50)
        landmarks[hand_tracker.HandMouseController.MIDDLE_TIP] = SimpleNamespace(x=0.50, y=0.50)
    elif move:
        landmarks[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(
            x=index_x + 0.01, y=index_y
        )
    return landmarks


class HandMouseControllerTests(unittest.TestCase):
    def make_controller(self, mouse, **settings):
        mouse.size.return_value = (1920, 1080)
        mouse.position.return_value = (960, 540)
        with patch("hand_tracker.virtual_screen_bounds", return_value=(0, 0, 1920, 1080)):
            return hand_tracker.HandMouseController(hand_tracker.Settings(smoothing=1.0, **settings))

    @patch("hand_tracker.pyautogui")
    def test_maps_tracking_area_inside_screen_edges(self, mouse) -> None:
        controller = self.make_controller(mouse)

        top_left = controller._screen_position(SimpleNamespace(x=0.0, y=0.0))
        bottom_right = controller._screen_position(SimpleNamespace(x=1.0, y=1.0))

        self.assertEqual(top_left, (1.0, 1.0))
        self.assertEqual(bottom_right, (1918.0, 1078.0))

    @patch("hand_tracker.pyautogui")
    def test_failsafe_uses_only_outer_virtual_desktop_corners(self, mouse) -> None:
        self.make_controller(mouse)
        hand_tracker.configure_failsafe_points(-1280, 0, 3200, 1080)

        self.assertEqual(
            mouse.FAILSAFE_POINTS,
            [(-1280, 0), (-1280, 1079), (1919, 0), (1919, 1079)],
        )

    @patch("hand_tracker.pyautogui")
    def test_failsafe_pauses_control_without_closing_app(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        mouse.FailSafeException = FailSafeException
        mouse.moveTo.side_effect = FailSafeException

        controller._move_mouse_to(200, 200)

        self.assertFalse(controller.enabled)
        self.assertTrue(controller.failsafe_triggered)

    @patch("hand_tracker.pyautogui")
    def test_thumb_index_pinch_moves_cursor(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True

        controller.process_hand(make_hand(extended=("index",), move=True, index_x=0.50))
        controller.process_hand(make_hand(extended=("index",), move=True, index_x=0.65))

        mouse.moveTo.assert_called()
        self.assertEqual(controller.gesture, "MOVE")
        self.assertTrue(controller.move_active)

    @patch("hand_tracker.pyautogui")
    def test_thumb_index_pinch_tolerates_depth_noise(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand(extended=("index",), move=True)
        hand[hand_tracker.HandMouseController.INDEX_TIP].z = 0.10

        controller.process_hand(hand)

        self.assertEqual(controller.gesture, "MOVE")
        self.assertTrue(controller.move_active)

    @patch("hand_tracker.pyautogui")
    def test_index_pinch_wins_when_middle_is_barely_closer(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand(extended=("index", "middle", "ring"), move=True)
        # The middle tip almost touches the thumb too, a bit closer than the
        # index: this used to fire a click instead of the move pinch.
        hand[hand_tracker.HandMouseController.MIDDLE_TIP] = SimpleNamespace(x=0.521, y=0.20)

        controller.process_hand(hand)

        self.assertEqual(controller.gesture, "MOVE")
        mouse.click.assert_not_called()

    @patch("hand_tracker.pyautogui")
    def test_middle_pinch_clicks_when_clearly_closer_than_index(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand(extended=("index", "middle", "ring"))
        hand[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=0.51, y=0.20)
        hand[hand_tracker.HandMouseController.INDEX_TIP] = SimpleNamespace(x=0.53, y=0.20)
        hand[hand_tracker.HandMouseController.MIDDLE_TIP] = SimpleNamespace(x=0.51, y=0.21)

        controller.process_hand(hand)

        self.assertEqual(controller.gesture, "CLICK")
        mouse.click.assert_called_once_with(_pause=False)

    @patch("hand_tracker.pyautogui")
    def test_thumb_middle_pinch_clicks_once_until_released(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True

        clicked_hand = make_hand(extended=("index",), click=True)
        controller.process_hand(clicked_hand)
        controller.process_hand(clicked_hand)
        controller.process_hand(make_hand(extended=("index",)))
        controller.process_hand(clicked_hand)

        self.assertEqual(mouse.click.call_count, 2)
        self.assertEqual(controller.gesture, "CLICK")

    @patch("hand_tracker.pyautogui")
    def test_click_fires_once_per_pinch_and_not_while_releasing(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        clicked_hand = make_hand(extended=("index",), click=True)
        release_hand = make_hand(extended=("index",))
        release_hand[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(
            x=0.50, y=0.50
        )
        release_hand[hand_tracker.HandMouseController.MIDDLE_TIP] = SimpleNamespace(
            x=0.59, y=0.50
        )

        controller.process_hand(clicked_hand)
        controller.process_hand(clicked_hand)
        controller.process_hand(release_hand)
        controller.process_hand(release_hand)
        controller.process_hand(clicked_hand)

        self.assertEqual(mouse.click.call_count, 2)

    @patch("hand_tracker.pyautogui")
    def test_thumb_middle_pinch_tolerates_depth_noise(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        clicked_hand = make_hand(extended=("index",), click=True)
        clicked_hand[hand_tracker.HandMouseController.MIDDLE_TIP].z = 0.10

        controller.process_hand(clicked_hand)

        self.assertEqual(controller.gesture, "CLICK")
        mouse.click.assert_called_once_with(_pause=False)

    @patch("hand_tracker.pyautogui")
    def test_thumb_middle_pinch_can_click_with_index_folded(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand()
        hand[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=0.70, y=0.58)
        hand[hand_tracker.HandMouseController.MIDDLE_TIP] = SimpleNamespace(x=0.70, y=0.58)

        controller.process_hand(hand)

        self.assertEqual(controller.gesture, "CLICK")
        mouse.click.assert_called_once_with(_pause=False)

    @patch("hand_tracker.pyautogui")
    def test_fist_holds_button_and_moves_relatively(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True

        controller.process_hand(make_hand())
        controller.process_hand(make_hand(palm_x=0.65))
        controller.process_hand(make_hand(extended=("index",)))

        mouse.mouseDown.assert_called_once_with(_pause=False)
        mouse.moveTo.assert_called()
        mouse.mouseUp.assert_called_once_with(_pause=False)
        self.assertFalse(controller.drag_active)

    @patch("hand_tracker.pyautogui")
    def test_drag_survives_one_misclassified_outer_finger(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True

        controller.process_hand(make_hand())
        controller.process_hand(make_hand(extended=("ring",)))

        mouse.mouseDown.assert_called_once_with(_pause=False)
        mouse.mouseUp.assert_not_called()
        self.assertTrue(controller.drag_active)

    @patch("hand_tracker.pyautogui")
    def test_folded_fist_with_thumb_near_middle_starts_drag(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        fist = make_hand()
        fist[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=0.51, y=0.72)

        controller.process_hand(fist)

        self.assertEqual(controller.gesture, "DRAG")
        mouse.mouseDown.assert_called_once_with(_pause=False)

    @patch("hand_tracker.pyautogui")
    def test_close_index_and_middle_scroll_from_finger_motion(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True

        controller.process_hand(
            make_hand(extended=("index", "middle"), index_y=0.30, middle_y=0.30)
        )
        controller.process_hand(
            make_hand(extended=("index", "middle"), index_y=0.20, middle_y=0.20)
        )

        mouse.scroll.assert_called_once_with(3, _pause=False)
        self.assertEqual(controller.gesture, "SCROLL")

    @patch("hand_tracker.pyautogui")
    def test_scroll_gesture_ignores_depth_gap_between_fingertips(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand(
            extended=("index", "middle"), index_y=0.30, middle_y=0.30
        )
        hand[hand_tracker.HandMouseController.INDEX_TIP].z = 0.20
        hand[hand_tracker.HandMouseController.MIDDLE_TIP].z = -0.20

        controller.process_hand(hand)

        self.assertEqual(controller.gesture, "SCROLL")
        self.assertTrue(controller.scroll_active)

    @patch("hand_tracker.pyautogui")
    def test_scroll_ignores_movement_of_the_entire_hand(self, mouse) -> None:
        controller = self.make_controller(mouse)
        controller.enabled = True
        hand = make_hand(
            extended=("index", "middle"), index_y=0.30, middle_y=0.30
        )
        shifted_hand = [SimpleNamespace(x=point.x, y=point.y + 0.10) for point in hand]

        controller.process_hand(hand)
        controller.process_hand(shifted_hand)

        mouse.scroll.assert_not_called()

    @patch("hand_tracker.pyautogui")
    def test_lost_hand_releases_active_drag(self, mouse) -> None:
        controller = self.make_controller(mouse, lost_hand_release_frames=2)
        controller.enabled = True
        controller.process_hand(make_hand())

        controller.hand_missing()
        controller.hand_missing()

        mouse.mouseUp.assert_called_once_with(_pause=False)
        self.assertFalse(controller.drag_active)


if __name__ == "__main__":
    unittest.main()
