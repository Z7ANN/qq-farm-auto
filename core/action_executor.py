"""操作执行器 - 后台消息点击/拖拽"""
import ctypes
import random
import time
from ctypes import wintypes
from loguru import logger

import pyautogui
from models.farm_state import Action, OperationResult
from models.config import RunMode
from utils.run_mode_decorator import Config as DecoratorConfig, UNSET


# Windows 消息常量
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

user32 = ctypes.windll.user32

# 前台模式配置
# 禁用pyautogui的安全暂停（我们自己控制延迟）
pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True


class ActionExecutor:
    def __init__(self, window_rect: tuple[int, int, int, int],
                 hwnd: int | None = None,
                 run_mode: RunMode = RunMode.BACKGROUND,
                 delay_min: float = 0.5, delay_max: float = 2.0,
                 click_offset: int = 5):
        self._window_left = window_rect[0]
        self._window_top = window_rect[1]
        self._window_width = window_rect[2]
        self._window_height = window_rect[3]
        self._hwnd = hwnd
        self._run_mode = run_mode
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._click_offset = click_offset

    def update_window_rect(self, rect: tuple[int, int, int, int]):
        self._window_left, self._window_top = rect[0], rect[1]
        self._window_width, self._window_height = rect[2], rect[3]

    def update_window_handle(self, hwnd: int | None):
        self._hwnd = hwnd

    def update_run_mode(self, run_mode: RunMode):
        self._run_mode = run_mode

    def get_run_mode(self) -> RunMode:
        return self._run_mode

    def resolve_dispatch_option(self, key: str):
        if key == "RUN_MODE":
            return self._run_mode
        return UNSET

    def relative_to_absolute(self, rel_x: int, rel_y: int) -> tuple[int, int]:
        """将相对于窗口的坐标转为屏幕绝对坐标"""
        abs_x = self._window_left + rel_x
        abs_y = self._window_top + rel_y
        return abs_x, abs_y

    def _random_offset(self) -> tuple[int, int]:
        """生成随机偏移"""
        ox = random.randint(-self._click_offset, self._click_offset)
        oy = random.randint(-self._click_offset, self._click_offset)
        return ox, oy

    def _random_delay(self):
        """操作间延迟"""
        dmin = min(self._delay_min, self._delay_max)
        dmax = max(self._delay_min, self._delay_max)
        time.sleep(random.uniform(dmin, dmax))

    @staticmethod
    def _make_lparam(x: int, y: int) -> int:
        return ((y & 0xFFFF) << 16) | (x & 0xFFFF)

    def _screen_to_client(self, abs_x: int, abs_y: int) -> tuple[int, int] | None:
        if not self._hwnd:
            logger.error("后台点击失败: 窗口句柄为空")
            return None
        point = wintypes.POINT(int(abs_x), int(abs_y))
        ok = user32.ScreenToClient(wintypes.HWND(self._hwnd), ctypes.byref(point))
        if not ok:
            logger.error("后台点击失败: ScreenToClient 调用失败")
            return None
        return point.x, point.y

    def _in_window(self, abs_x: int, abs_y: int) -> bool:
        return (self._window_left <= abs_x <= self._window_left + self._window_width and
                self._window_top <= abs_y <= self._window_top + self._window_height)

    def _send_click_client(self, client_x: int, client_y: int) -> bool:
        if not self._hwnd:
            return False
        hwnd = wintypes.HWND(self._hwnd)
        lparam = self._make_lparam(client_x, client_y)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.03)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
        return True

    def click(self, x: int, y: int, use_offset: bool = True) -> bool:
        """点击屏幕绝对坐标。"""
        try:
            target_x, target_y = int(x), int(y)
            if use_offset:
                ox, oy = self._random_offset()
                target_x += ox
                target_y += oy

            if not self._in_window(target_x, target_y):
                logger.warning(f"后台点击越界: ({target_x}, {target_y})")
                return False

            return self._click_by_mode(target_x, target_y)
        except Exception as e:
            logger.error(f"点击失败: {e}")
            return False

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _click_by_mode(self, target_x: int, target_y: int) -> bool:
        return self._click_background(target_x, target_y)

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _click_by_mode(self, target_x: int, target_y: int) -> bool:
        return self._click_foreground(target_x, target_y)

    def _click_foreground(self, target_x: int, target_y: int) -> bool:
        pyautogui.moveTo(target_x, target_y, duration=0.02)
        time.sleep(0.03)
        pyautogui.click(target_x, target_y)
        logger.debug(f"前台点击 screen=({target_x},{target_y})")
        return True

    def _click_background(self, target_x: int, target_y: int) -> bool:
        client = self._screen_to_client(target_x, target_y)
        if not client:
            return False
        success = self._send_click_client(client[0], client[1])
        if success:
            logger.debug(f"后台点击 screen=({target_x},{target_y}) client=({client[0]},{client[1]})")
        else:
            logger.error("后台点击失败: 发送消息失败")
        return success

    def click_relative(self, rel_x: int, rel_y: int, use_offset: bool = True) -> bool:
        """后台点击窗口相对坐标"""
        abs_x, abs_y = self.relative_to_absolute(rel_x, rel_y)
        return self.click(abs_x, abs_y, use_offset=use_offset)

    def drag_relative_path(self, points: list[tuple[int, int]],
                           move_delay: float = 0.12) -> bool:
        """拖拽：按下后沿给定相对坐标路径移动，最后抬起"""
        if len(points) < 2:
            return False

        abs_points: list[tuple[int, int]] = []
        for rel_x, rel_y in points:
            abs_x, abs_y = self.relative_to_absolute(int(rel_x), int(rel_y))
            if not self._in_window(abs_x, abs_y):
                logger.warning(f"后台拖拽越界: ({abs_x}, {abs_y})")
                return False
            abs_points.append((abs_x, abs_y))

        return self._drag_by_mode(abs_points, move_delay)

    @DecoratorConfig.when(RUN_MODE=RunMode.BACKGROUND)
    def _drag_by_mode(self, abs_points: list[tuple[int, int]], move_delay: float) -> bool:
        return self._drag_background(abs_points, move_delay)

    @DecoratorConfig.when(RUN_MODE=RunMode.FOREGROUND)
    def _drag_by_mode(self, abs_points: list[tuple[int, int]], move_delay: float) -> bool:
        return self._drag_foreground(abs_points, move_delay)

    def _drag_foreground(self, abs_points: list[tuple[int, int]], move_delay: float) -> bool:
        try:
            first_x, first_y = abs_points[0]
            pyautogui.moveTo(first_x, first_y, duration=0.02)
            time.sleep(0.03)
            pyautogui.mouseDown()
            time.sleep(0.03)
            for x, y in abs_points[1:]:
                pyautogui.moveTo(x, y, duration=0.02)
                time.sleep(move_delay)
            pyautogui.mouseUp()
            logger.debug(f"前台拖拽完成: {len(abs_points) - 1} 个目标点")
            return True
        except Exception as e:
            logger.error(f"前台拖拽失败: {e}")
            return False

    def _drag_background(self, abs_points: list[tuple[int, int]], move_delay: float) -> bool:
        if not self._hwnd:
            logger.error("后台拖拽失败: 窗口句柄为空")
            return False

        client_points: list[tuple[int, int]] = []
        for abs_x, abs_y in abs_points:
            client = self._screen_to_client(abs_x, abs_y)
            if not client:
                return False
            client_points.append(client)

        try:
            hwnd = wintypes.HWND(self._hwnd)
            first_x, first_y = client_points[0]
            first_lparam = self._make_lparam(first_x, first_y)
            user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, first_lparam)
            user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, first_lparam)
            time.sleep(0.05)

            for cx, cy in client_points[1:]:
                lparam = self._make_lparam(cx, cy)
                user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam)
                time.sleep(move_delay)

            last_x, last_y = client_points[-1]
            last_lparam = self._make_lparam(last_x, last_y)
            user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, last_lparam)
            logger.debug(f"后台拖拽完成: {len(abs_points) - 1} 个目标点")
            return True
        except Exception as e:
            logger.error(f"后台拖拽失败: {e}")
            return False

    def execute_action(self, action: Action) -> OperationResult:
        """执行单个操作"""
        pos = action.click_position
        if not pos or "x" not in pos or "y" not in pos:
            return OperationResult(
                action=action, success=False,
                message="缺少点击坐标", timestamp=time.time()
            )

        # 转换坐标
        abs_x, abs_y = self.relative_to_absolute(int(pos["x"]), int(pos["y"]))

        # 检查坐标是否在窗口范围内
        if not self._in_window(abs_x, abs_y):
            return OperationResult(
                action=action, success=False,
                message=f"坐标 ({abs_x},{abs_y}) 超出窗口范围",
                timestamp=time.time()
            )

        success = self.click(abs_x, abs_y, use_offset=True)
        self._random_delay()

        return OperationResult(
            action=action, success=success,
            message=action.description if success else "点击失败",
            timestamp=time.time()
        )

    def execute_actions(self, actions: list[Action],
                        max_count: int = 20) -> list[OperationResult]:
        """按优先级执行操作序列"""
        results = []
        executed = 0

        for action in actions:
            if executed >= max_count:
                logger.info(f"已达到单轮最大操作数 {max_count}，停止执行")
                break

            logger.info(f"执行: {action.description} (优先级:{action.priority})")
            result = self.execute_action(action)
            results.append(result)

            if result.success:
                executed += 1
                logger.info(f"✓ {action.description}")
            else:
                logger.warning(f"✗ {action.description}: {result.message}")

        return results
