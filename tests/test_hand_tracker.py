import unittest
from types import SimpleNamespace
from unittest.mock import patch

import hand_tracker


def make_hand(thumb_x: float, thumb_y: float, index_x: float, index_y: float):
    landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]
    landmarks[hand_tracker.HandMouseController.WRIST] = SimpleNamespace(x=0.5, y=0.8)
    landmarks[hand_tracker.HandMouseController.MIDDLE_MCP] = SimpleNamespace(x=0.5, y=0.5)
    landmarks[hand_tracker.HandMouseController.THUMB_TIP] = SimpleNamespace(x=thumb_x, y=thumb_y)
    landmarks[hand_tracker.HandMouseController.INDEX_TIP] = SimpleNamespace(x=index_x, y=index_y)
    return landmarks


class HandMouseControllerTests(unittest.TestCase):
    @patch("hand_tracker.pyautogui")
    def test_maps_tracking_area_inside_screen_edges(self, mouse) -> None:
        mouse.size.return_value = (1920, 1080)
        controller = hand_tracker.HandMouseController(hand_tracker.Settings())

        top_left = controller._screen_position(SimpleNamespace(x=0.0, y=0.0))
        bottom_right = controller._screen_position(SimpleNamespace(x=1.0, y=1.0))

        self.assertEqual(top_left, (1.0, 1.0))
        self.assertEqual(bottom_right, (1918.0, 1078.0))

    @patch("hand_tracker.pyautogui")
    def test_pinch_presses_once_and_releases_after_opening_hand(self, mouse) -> None:
        mouse.size.return_value = (1920, 1080)
        controller = hand_tracker.HandMouseController(hand_tracker.Settings(smoothing=1.0))
        controller.enabled = True
        pinched_hand = make_hand(0.51, 0.50, 0.50, 0.50)
        open_hand = make_hand(0.85, 0.50, 0.50, 0.50)

        controller.process_hand(pinched_hand)
        controller.process_hand(pinched_hand)
        controller.process_hand(open_hand)

        mouse.mouseDown.assert_called_once_with(_pause=False)
        mouse.mouseUp.assert_called_once_with(_pause=False)
        self.assertFalse(controller.mouse_is_down)

    @patch("hand_tracker.pyautogui")
    def test_lost_hand_releases_a_drag(self, mouse) -> None:
        mouse.size.return_value = (1920, 1080)
        controller = hand_tracker.HandMouseController(
            hand_tracker.Settings(lost_hand_release_frames=2, smoothing=1.0)
        )
        controller.enabled = True
        controller.process_hand(make_hand(0.51, 0.50, 0.50, 0.50))

        controller.hand_missing()
        controller.hand_missing()

        mouse.mouseUp.assert_called_once_with(_pause=False)
        self.assertFalse(controller.mouse_is_down)


if __name__ == "__main__":
    unittest.main()
