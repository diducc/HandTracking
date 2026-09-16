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
    cursor_gain: float = 2.1
    pinch_down_threshold: float = 0.22
    pinch_up_threshold: float = 0.34
    pinch_move_threshold: float = 14.0
    pinch_click_max_duration: float = 0.55
    lost_hand_release_frames: int = 10


class HandMouseController:
    """Convert a hand's index position and pinch state into mouse input."""

    INDEX_TIP = 8
    THUMB_TIP = 4
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
        self.enabled = False
        self.pinch_active = False
        self.pinch_moved = False
        self.pinch_started_at = 0.0
        self.pinch_start_hand: tuple[float, float] | None = None
        self.pinch_start_cursor: tuple[int, int] | None = None
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

    def _pinch_ratio(self, landmarks) -> float:
        pinch_distance = self._distance(
            landmarks[self.THUMB_TIP], landmarks[self.INDEX_TIP]
        )
        palm_size = self._distance(landmarks[self.WRIST], landmarks[self.MIDDLE_MCP])
        return pinch_distance / max(palm_size, 0.001)

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

        pyautogui.moveTo(round(self.filtered_x), round(self.filtered_y), _pause=False)

    def _start_pinch(self, index_tip) -> None:
        self.pinch_active = True
        self.pinch_moved = False
        self.pinch_started_at = time.monotonic()
        self.pinch_start_hand = self._screen_position(index_tip)
        self.pinch_start_cursor = pyautogui.position()
        self.filtered_x, self.filtered_y = self.pinch_start_cursor

    def _move_from_pinch(self, index_tip) -> None:
        if self.pinch_start_hand is None or self.pinch_start_cursor is None:
            return

        hand_x, hand_y = self._screen_position(index_tip)
        target_x = self.pinch_start_cursor[0] + (
            hand_x - self.pinch_start_hand[0]
        ) * self.settings.cursor_gain
        target_y = self.pinch_start_cursor[1] + (
            hand_y - self.pinch_start_hand[1]
        ) * self.settings.cursor_gain
        movement = math.hypot(
            target_x - self.pinch_start_cursor[0],
            target_y - self.pinch_start_cursor[1],
        )
        if movement >= self.settings.pinch_move_threshold:
            self.pinch_moved = True
            self._move_mouse_to(target_x, target_y)

    def _cancel_pinch(self) -> None:
        self.pinch_active = False
        self.pinch_moved = False
        self.pinch_start_hand = None
        self.pinch_start_cursor = None

    def _finish_pinch(self) -> None:
        is_click = (
            not self.pinch_moved
            and time.monotonic() - self.pinch_started_at <= self.settings.pinch_click_max_duration
        )
        self._cancel_pinch()
        if is_click:
            pyautogui.click(_pause=False)

    def toggle(self) -> None:
        self.enabled = not self.enabled
        if not self.enabled:
            self._cancel_pinch()

    def process_hand(self, landmarks) -> float:
        """Move the pointer and press/release based on the current hand pose."""
        self.frames_without_hand = 0
        if not self.enabled:
            return self._pinch_ratio(landmarks)

        pinch_ratio = self._pinch_ratio(landmarks)

        # Separate thresholds prevent jitter near the pinch boundary.
        if not self.pinch_active and pinch_ratio <= self.settings.pinch_down_threshold:
            self._start_pinch(landmarks[self.INDEX_TIP])
        elif self.pinch_active and pinch_ratio >= self.settings.pinch_up_threshold:
            self._finish_pinch()
        elif self.pinch_active:
            self._move_from_pinch(landmarks[self.INDEX_TIP])

        return pinch_ratio

    def hand_missing(self) -> None:
        self.frames_without_hand += 1
        if self.frames_without_hand >= self.settings.lost_hand_release_frames:
            self._cancel_pinch()

    def close(self) -> None:
        self._cancel_pinch()


def draw_interface(frame, controller: HandMouseController, pinch_ratio: float | None) -> None:
    state = "ON" if controller.enabled else "PAUSED"
    state_color = (70, 220, 70) if controller.enabled else (60, 180, 255)
    pointer_state = "MOVE" if controller.pinch_active else "READY"
    lines = [
        (f"Mouse: {state}  |  {pointer_state}", state_color),
        ("pinch + move: cursor    tap: click", (235, 235, 235)),
        ("m: toggle    q / Esc: quit", (235, 235, 235)),
    ]
    if pinch_ratio is not None:
        lines.append((f"Pinch: {pinch_ratio:.2f}", (235, 235, 235)))

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
        description="Control the mouse cursor using an index finger and a pinch gesture."
    )
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0)")
    parser.add_argument("--width", type=int, default=1280, help="Capture width (default: 1280)")
    parser.add_argument("--height", type=int, default=720, help="Capture height (default: 720)")
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=2.1,
        help="Cursor gain while pinching (default: 2.1)",
    )
    parser.add_argument(
        "--smoothing",
        type=float,
        default=0.18,
        help="Motion smoothing from 0.01 to 1.0; lower is smoother (default: 0.18)",
    )
    parser.add_argument(
        "--pinch-threshold",
        type=float,
        default=0.22,
        help="Pinch sensitivity; lower requires fingers to be closer (default: 0.22)",
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
    if not 0.05 <= args.pinch_threshold < 0.5:
        parser.error("--pinch-threshold must be between 0.05 and 0.49")
    return Settings(
        camera_index=args.camera,
        frame_width=args.width,
        frame_height=args.height,
        cursor_gain=args.sensitivity,
        smoothing=args.smoothing,
        pinch_down_threshold=args.pinch_threshold,
        pinch_up_threshold=args.pinch_threshold + 0.12,
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
                pinch_ratio: float | None = None

                if results.multi_hand_landmarks:
                    hand_landmarks = results.multi_hand_landmarks[0]
                    pinch_ratio = controller.process_hand(hand_landmarks.landmark)
                    drawing.draw_landmarks(
                        frame,
                        hand_landmarks,
                        hands.HAND_CONNECTIONS,
                        drawing_styles.get_default_hand_landmarks_style(),
                        drawing_styles.get_default_hand_connections_style(),
                    )
                else:
                    controller.hand_missing()

                draw_interface(frame, controller, pinch_ratio)
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
