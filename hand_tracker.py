"""Control the mouse with one hand, using a webcam and MediaPipe."""

from __future__ import annotations

import argparse
import ctypes
import math
import platform
import time
from dataclasses import dataclass

import cv2
import mediapipe as mp
import pyautogui


@dataclass
class Settings:
    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    detection_confidence: float = 0.65
    tracking_confidence: float = 0.65
    screen_margin: float = 0.08
    smoothing: float = 0.18
    cursor_gain: float = 1.0
    move_down_threshold: float = 0.22
    move_up_threshold: float = 0.34
    click_down_threshold: float = 0.22
    click_up_threshold: float = 0.34
    scroll_down_threshold: float = 0.45
    scroll_up_threshold: float = 0.60
    scroll_notch_distance: float = 0.15
    lost_hand_release_frames: int = 10


class HandMouseController:
    """Convert one hand's poses into mouse movement and commands."""

    INDEX_TIP = 8
    INDEX_PIP = 6
    THUMB_TIP = 4
    MIDDLE_TIP = 12
    MIDDLE_PIP = 10
    RING_TIP = 16
    RING_PIP = 14
    PINKY_TIP = 20
    PINKY_PIP = 18
    WRIST = 0
    MIDDLE_MCP = 9

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        (
            self.screen_left,
            self.screen_top,
            self.screen_width,
            self.screen_height,
        ) = virtual_screen_bounds()
        configure_failsafe_points(
            self.screen_left,
            self.screen_top,
            self.screen_width,
            self.screen_height,
        )
        self.enabled = False
        self.failsafe_triggered = False
        self.move_active = False
        self.move_start_hand: tuple[float, float] | None = None
        self.move_start_cursor: tuple[int, int] | None = None
        self.click_active = False
        self.drag_active = False
        self.drag_start_hand: tuple[float, float] | None = None
        self.drag_start_cursor: tuple[int, int] | None = None
        self.open_palm_latched = False
        self.last_scroll_relative_y: float | None = None
        self.scroll_active = False
        self.scroll_remainder = 0.0
        self.gesture = "READY"
        self.filtered_x: float | None = None
        self.filtered_y: float | None = None
        self.frames_without_hand = 0

        # Avoid PyAutoGUI's default 100 ms pause after every move/click.
        pyautogui.PAUSE = 0

    @staticmethod
    def _distance(point_a, point_b) -> float:
        return math.sqrt(
            (point_a.x - point_b.x) ** 2
            + (point_a.y - point_b.y) ** 2
            + (getattr(point_a, "z", 0.0) - getattr(point_b, "z", 0.0)) ** 2
        )

    def _pinch_ratio(self, landmarks, finger_tip: int) -> float:
        pinch_distance = self._distance(
            landmarks[self.THUMB_TIP], landmarks[finger_tip]
        )
        palm_size = self._distance(landmarks[self.WRIST], landmarks[self.MIDDLE_MCP])
        return pinch_distance / max(palm_size, 0.001)

    def _finger_spacing_ratio(self, landmarks, first_tip: int, second_tip: int) -> float:
        """Return the tip distance scaled to the current palm size."""
        fingertip_distance = self._distance(landmarks[first_tip], landmarks[second_tip])
        palm_size = self._distance(landmarks[self.WRIST], landmarks[self.MIDDLE_MCP])
        return fingertip_distance / max(palm_size, 0.001)

    def _finger_is_extended(self, landmarks, tip: int, pip: int) -> bool:
        """Classify a finger from its distance to the wrist, independent of rotation."""
        tip_distance = self._distance(landmarks[tip], landmarks[self.WRIST])
        pip_distance = self._distance(landmarks[pip], landmarks[self.WRIST])
        return tip_distance > pip_distance * 1.2

    def _recognize_gesture(
        self, landmarks, move_ratio: float, click_ratio: float, scroll_ratio: float
    ) -> str:
        index_extended = self._finger_is_extended(
            landmarks, self.INDEX_TIP, self.INDEX_PIP
        )
        middle_extended = self._finger_is_extended(
            landmarks, self.MIDDLE_TIP, self.MIDDLE_PIP
        )
        ring_extended = self._finger_is_extended(
            landmarks, self.RING_TIP, self.RING_PIP
        )
        pinky_extended = self._finger_is_extended(
            landmarks, self.PINKY_TIP, self.PINKY_PIP
        )

        if click_ratio <= self.settings.click_down_threshold or self.click_active:
            return "CLICK"
        if move_ratio <= self.settings.move_down_threshold or (
            self.move_active and move_ratio < self.settings.move_up_threshold
        ):
            return "MOVE"
        if index_extended and middle_extended and ring_extended and pinky_extended:
            return "PAUSE"
        if not any((index_extended, middle_extended, ring_extended, pinky_extended)):
            return "DRAG"
        if (
            index_extended
            and middle_extended
            and not ring_extended
            and not pinky_extended
            and (
                scroll_ratio <= self.settings.scroll_down_threshold
                or (
                    self.scroll_active
                    and scroll_ratio < self.settings.scroll_up_threshold
                )
            )
        ):
            return "SCROLL"
        return "READY"

    def _screen_position(self, landmark) -> tuple[float, float]:
        margin = self.settings.screen_margin
        normalized_x = (landmark.x - margin) / (1 - 2 * margin)
        normalized_y = (landmark.y - margin) / (1 - 2 * margin)
        normalized_x = min(max(normalized_x, 0.0), 1.0)
        normalized_y = min(max(normalized_y, 0.0), 1.0)

        # Keep one pixel away from corners so PyAutoGUI's emergency failsafe stays usable.
        usable_width = max(self.screen_width - 3, 0)
        usable_height = max(self.screen_height - 3, 0)
        return (
            self.screen_left + 1 + normalized_x * usable_width,
            self.screen_top + 1 + normalized_y * usable_height,
        )

    def _move_mouse_to(self, target_x: float, target_y: float) -> None:
        min_x = self.screen_left + 1
        min_y = self.screen_top + 1
        max_x = self.screen_left + max(self.screen_width - 2, 1)
        max_y = self.screen_top + max(self.screen_height - 2, 1)
        target_x = min(max(target_x, min_x), max_x)
        target_y = min(max(target_y, min_y), max_y)
        if self.filtered_x is None or self.filtered_y is None:
            self.filtered_x, self.filtered_y = target_x, target_y
        else:
            amount = self.settings.smoothing
            self.filtered_x += (target_x - self.filtered_x) * amount
            self.filtered_y += (target_y - self.filtered_y) * amount

        try:
            pyautogui.moveTo(round(self.filtered_x), round(self.filtered_y), _pause=False)
        except pyautogui.FailSafeException:
            # Keep the emergency stop but leave the camera window running.
            self.enabled = False
            self.failsafe_triggered = True
            self._stop_move()
            self._reset_scroll()
            print("PyAutoGUI fail-safe triggered. Move the mouse away from the desktop corner, then press m.")

    def _start_move(self, index_tip) -> None:
        self.move_active = True
        self.move_start_hand = self._screen_position(index_tip)
        self.move_start_cursor = pyautogui.position()
        self.filtered_x, self.filtered_y = self.move_start_cursor

    def _move_from_pinch(self, index_tip) -> None:
        if self.move_start_hand is None or self.move_start_cursor is None:
            return

        hand_x, hand_y = self._screen_position(index_tip)
        target_x = self.move_start_cursor[0] + (
            hand_x - self.move_start_hand[0]
        ) * self.settings.cursor_gain
        target_y = self.move_start_cursor[1] + (
            hand_y - self.move_start_hand[1]
        ) * self.settings.cursor_gain
        self._move_mouse_to(target_x, target_y)

    def _stop_move(self) -> None:
        self.move_active = False
        self.move_start_hand = None
        self.move_start_cursor = None

    def _start_drag(self, palm_center) -> None:
        self.drag_active = True
        self.drag_start_hand = self._screen_position(palm_center)
        self.drag_start_cursor = pyautogui.position()
        self.filtered_x, self.filtered_y = self.drag_start_cursor
        pyautogui.mouseDown(_pause=False)

    def _move_drag(self, palm_center) -> None:
        if self.drag_start_hand is None or self.drag_start_cursor is None:
            return

        hand_x, hand_y = self._screen_position(palm_center)
        target_x = self.drag_start_cursor[0] + (
            hand_x - self.drag_start_hand[0]
        ) * self.settings.cursor_gain
        target_y = self.drag_start_cursor[1] + (
            hand_y - self.drag_start_hand[1]
        ) * self.settings.cursor_gain
        self._move_mouse_to(target_x, target_y)

    def _stop_drag(self) -> None:
        if self.drag_active:
            pyautogui.mouseUp(_pause=False)
        self.drag_active = False
        self.drag_start_hand = None
        self.drag_start_cursor = None

    def _scroll(self, landmarks) -> None:
        """Scroll from two fingertips moving relative to a stationary palm."""
        fingertip_y = (
            landmarks[self.INDEX_TIP].y + landmarks[self.MIDDLE_TIP].y
        ) / 2
        palm_y = landmarks[self.MIDDLE_MCP].y
        palm_size = self._distance(landmarks[self.WRIST], landmarks[self.MIDDLE_MCP])
        relative_y = (fingertip_y - palm_y) / max(palm_size, 0.001)

        self.scroll_active = True
        if self.last_scroll_relative_y is None:
            self.last_scroll_relative_y = relative_y
            return

        self.scroll_remainder += (
            self.last_scroll_relative_y - relative_y
        ) / self.settings.scroll_notch_distance
        self.last_scroll_relative_y = relative_y
        epsilon = math.copysign(1e-9, self.scroll_remainder)
        notches = math.trunc(self.scroll_remainder + epsilon)
        if notches:
            pyautogui.scroll(notches, _pause=False)
            self.scroll_remainder -= notches

    def _reset_scroll(self) -> None:
        self.last_scroll_relative_y = None
        self.scroll_remainder = 0.0
        self.scroll_active = False

    def toggle(self) -> None:
        self.enabled = not self.enabled
        if self.enabled:
            self.failsafe_triggered = False
        if not self.enabled:
            self._stop_move()
            self._stop_drag()
            self._reset_scroll()

    def process_hand(self, landmarks) -> tuple[float, float]:
        """Move the pointer and execute commands for the currently visible hand."""
        self.frames_without_hand = 0
        move_ratio = self._pinch_ratio(landmarks, self.INDEX_TIP)
        click_ratio = self._pinch_ratio(landmarks, self.MIDDLE_TIP)
        scroll_ratio = self._finger_spacing_ratio(
            landmarks, self.INDEX_TIP, self.MIDDLE_TIP
        )
        self.gesture = self._recognize_gesture(
            landmarks, move_ratio, click_ratio, scroll_ratio
        )

        # An open palm toggles only once until the hand leaves that pose.
        if self.gesture == "PAUSE":
            if not self.open_palm_latched:
                self.open_palm_latched = True
                self.toggle()
            return move_ratio, click_ratio
        self.open_palm_latched = False

        if not self.enabled:
            self.gesture = "FAILSAFE" if self.failsafe_triggered else "PAUSED"
            return move_ratio, click_ratio

        if self.move_active and self.gesture != "MOVE":
            self._stop_move()
        if self.drag_active and self.gesture != "DRAG":
            self._stop_drag()
        if self.gesture == "MOVE":
            if not self.move_active:
                self._start_move(landmarks[self.INDEX_TIP])
            self._move_from_pinch(landmarks[self.INDEX_TIP])
        elif self.gesture == "DRAG":
            if not self.drag_active:
                self._start_drag(landmarks[self.MIDDLE_MCP])
            self._move_drag(landmarks[self.MIDDLE_MCP])
        elif self.gesture == "SCROLL":
            self._scroll(landmarks)
        else:
            self._reset_scroll()
            if self.gesture == "CLICK" and not self.click_active:
                self.click_active = True
                pyautogui.click(_pause=False)
            elif self.click_active and click_ratio >= self.settings.click_up_threshold:
                self.click_active = False
        return move_ratio, click_ratio

    def hand_missing(self) -> None:
        self.frames_without_hand += 1
        if self.frames_without_hand >= self.settings.lost_hand_release_frames:
            self._stop_move()
            self._stop_drag()
            self._reset_scroll()
            self.click_active = False
            self.open_palm_latched = False
            self.gesture = "READY"

    def close(self) -> None:
        self._stop_move()
        self._stop_drag()


def draw_interface(
    frame,
    controller: HandMouseController,
    pinch_ratios: tuple[float, float] | None,
) -> None:
    state = "ON" if controller.enabled else "FAILSAFE" if controller.failsafe_triggered else "PAUSED"
    state_color = (70, 220, 70) if controller.enabled else (60, 180, 255)
    pointer_state = controller.gesture
    lines = [
        (f"Mouse: {state}  |  {pointer_state}", state_color),
        ("thumb+index: move  thumb+middle: click  fist: drag", (235, 235, 235)),
        ("index+middle together: scroll  open palm: pause/resume", (235, 235, 235)),
        ("m: toggle    q / Esc: quit", (235, 235, 235)),
    ]
    if pinch_ratios is not None:
        move_ratio, click_ratio = pinch_ratios
        lines.append(
            (f"Move pinch: {move_ratio:.2f}  Click pinch: {click_ratio:.2f}", (235, 235, 235))
        )

    for index, (text, color) in enumerate(lines):
        y = 34 + index * 29
        cv2.putText(frame, text, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (25, 25, 25), 3)
        cv2.putText(frame, text, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, color, 1)


def virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Return the whole desktop rectangle, including secondary monitors on Windows."""
    if platform.system() == "Windows":
        user32 = ctypes.windll.user32
        try:
            # Keep cursor coordinates aligned with physical pixels on mixed-DPI monitors.
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            user32.SetProcessDPIAware()
        return (
            user32.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
            user32.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
            user32.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
            user32.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
        )

    width, height = pyautogui.size()
    return 0, 0, width, height


def configure_failsafe_points(left: int, top: int, width: int, height: int) -> None:
    """Keep the fail-safe on outer virtual-desktop corners, not monitor joins."""
    right = left + max(width - 1, 0)
    bottom = top + max(height - 1, 0)
    pyautogui.FAILSAFE_POINTS = [(left, top), (left, bottom), (right, top), (right, bottom)]


def camera_backends() -> list[tuple[str, int]]:
    """Return the capture backends that are useful for the current system."""
    system = platform.system()
    if system == "Windows":
        candidates = [
            ("DirectShow", cv2.CAP_DSHOW),
            ("Media Foundation", cv2.CAP_MSMF),
            ("automatic", cv2.CAP_ANY),
        ]
    elif system == "Darwin":
        candidates = [("AVFoundation", cv2.CAP_AVFOUNDATION), ("automatic", cv2.CAP_ANY)]
    else:
        candidates = [("automatic", cv2.CAP_ANY)]

    # CAP_ANY may coincide with another backend on a platform; do not retry it.
    seen: set[int] = set()
    return [(name, backend) for name, backend in candidates if not (backend in seen or seen.add(backend))]


def open_camera(settings: Settings) -> tuple[cv2.VideoCapture, object, str]:
    """Open a webcam and read an initial frame, trying system-specific backends."""
    attempted_backends: list[str] = []
    for backend_name, backend in camera_backends():
        attempted_backends.append(backend_name)
        camera = cv2.VideoCapture(settings.camera_index, backend)
        if not camera.isOpened():
            camera.release()
            continue

        camera.set(cv2.CAP_PROP_FRAME_WIDTH, settings.frame_width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.frame_height)

        # Some integrated cameras need a moment before returning their first frame.
        for _ in range(20):
            ok, frame = camera.read()
            if ok and frame is not None and frame.size:
                return camera, frame, backend_name
            time.sleep(0.05)
        camera.release()

    tried = ", ".join(attempted_backends)
    raise RuntimeError(
        f"Webcam {settings.camera_index} opened but did not return a frame. "
        f"Backends tried: {tried}. Close Teams/Zoom/browser tabs that may be using the camera, "
        "check Settings > Privacy & security > Camera, then try --camera 1."
    )


def list_cameras() -> None:
    """Print video streams exposed by OpenCV without moving the mouse."""
    print("Scanning camera indices 0 to 4...")
    for camera_index in range(5):
        found_stream = False
        for backend_name, backend in camera_backends():
            camera = cv2.VideoCapture(camera_index, backend)
            if not camera.isOpened():
                camera.release()
                continue

            frame = None
            for _ in range(20):
                ok, candidate = camera.read()
                if ok and candidate is not None and candidate.size:
                    frame = candidate
                    break
                time.sleep(0.05)
            camera.release()

            if frame is None:
                continue

            height, width = frame.shape[:2]
            brightness = cv2.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))[0]
            print(
                f"camera {camera_index}: {backend_name}, {width}x{height}, "
                f"brightness {brightness:.0f}/255"
            )
            found_stream = True

        if not found_stream:
            print(f"camera {camera_index}: no frames")


def parse_arguments() -> Settings:
    parser = argparse.ArgumentParser(
        description="Control the mouse cursor using index, pinch, fist, and V hand gestures."
    )
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0)")
    parser.add_argument("--width", type=int, default=1280, help="Capture width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Capture height (default: 720)")
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=1.0,
        help="Cursor gain while moving or dragging (default: 1.0)",
    )
    parser.add_argument(
        "--smoothing",
        type=float,
        default=0.18,
        help="Motion smoothing from 0.01 to 1.0; lower is smoother (default: 0.18)",
    )
    parser.add_argument(
        "--move-threshold",
        type=float,
        default=0.22,
        help="Thumb-index movement sensitivity; lower requires fingers to be closer (default: 0.22)",
    )
    parser.add_argument(
        "--click-threshold",
        type=float,
        default=0.22,
        help="Thumb-middle click sensitivity; lower requires fingers to be closer (default: 0.22)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="List camera streams and exit without opening the hand tracker",
    )
    args = parser.parse_args()
    if args.list_cameras:
        list_cameras()
        raise SystemExit(0)
    if args.sensitivity <= 0:
        parser.error("--sensitivity must be greater than zero")
    if not 0.01 <= args.smoothing <= 1.0:
        parser.error("--smoothing must be between 0.01 and 1.0")
    if not 0.05 <= args.click_threshold < 0.5:
        parser.error("--click-threshold must be between 0.05 and 0.49")
    if not 0.05 <= args.move_threshold < 0.5:
        parser.error("--move-threshold must be between 0.05 and 0.49")
    return Settings(
        camera_index=args.camera,
        frame_width=args.width,
        frame_height=args.height,
        cursor_gain=args.sensitivity,
        smoothing=args.smoothing,
        move_down_threshold=args.move_threshold,
        move_up_threshold=args.move_threshold + 0.12,
        click_down_threshold=args.click_threshold,
        click_up_threshold=args.click_threshold + 0.12,
    )


def main() -> None:
    settings = parse_arguments()
    camera, initial_frame, backend_name = open_camera(settings)

    controller = HandMouseController(settings)
    hands = mp.solutions.hands
    drawing = mp.solutions.drawing_utils
    drawing_styles = mp.solutions.drawing_styles

    print(
        f"Hand tracking started with {backend_name}. Focus the video window; "
        "press m to enable mouse input, q or Esc to quit."
    )

    try:
        with hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            model_complexity=1,
            min_detection_confidence=settings.detection_confidence,
            min_tracking_confidence=settings.tracking_confidence,
        ) as detector:
            while True:
                if initial_frame is not None:
                    frame = initial_frame
                    initial_frame = None
                else:
                    ok, frame = camera.read()
                    if not ok or frame is None:
                        raise RuntimeError("The webcam stopped returning frames. Close and restart the app.")

                # Mirroring makes moving the hand feel like looking into a mirror.
                frame = cv2.flip(frame, 1)
                results = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                pinch_ratios: tuple[float, float] | None = None

                if results.multi_hand_landmarks:
                    hand_landmarks = results.multi_hand_landmarks[0]
                    pinch_ratios = controller.process_hand(hand_landmarks.landmark)
                    drawing.draw_landmarks(
                        frame,
                        hand_landmarks,
                        hands.HAND_CONNECTIONS,
                        drawing_styles.get_default_hand_landmarks_style(),
                        drawing_styles.get_default_hand_connections_style(),
                    )
                else:
                    controller.hand_missing()

                draw_interface(frame, controller, pinch_ratios)
                cv2.imshow("Hand Tracking Mouse", frame)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("m"):
                    controller.toggle()
    finally:
        controller.close()
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
