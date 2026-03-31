"""屏幕捕获模块"""
import ctypes
import os
import time
from ctypes import wintypes
from loguru import logger
from PIL import Image
import mss

from utils.image_utils import save_screenshot


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class ScreenCapture:
    PW_RENDERFULLCONTENT = 0x00000002
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    def __init__(self, save_dir: str = "screenshots"):
        self._save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def _make_screenshot_path(self, prefix: str = "farm") -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{ts}.png"
        return os.path.join(self._save_dir, filename)

    def capture_region(self, rect: tuple[int, int, int, int]) -> Image.Image | None:
        """截取指定区域 (left, top, width, height)"""
        left, top, width, height = rect
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
        try:
            # 每次截图创建新的mss实例，避免跨线程问题
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            return image
        except Exception as e:
            logger.error(f"截屏失败: {e}")
            return None

    def capture_window_print(self, hwnd: int) -> Image.Image | None:
        """使用 PrintWindow 后台截取窗口（按窗口矩形尺寸）"""
        if not hwnd:
            return None

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            logger.error("PrintWindow截屏失败: GetWindowRect 调用失败")
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            logger.error(f"PrintWindow截屏失败: 非法窗口尺寸 {width}x{height}")
            return None

        hwnd_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
        if not hwnd_dc:
            logger.error("PrintWindow截屏失败: GetWindowDC 失败")
            return None

        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mem_dc:
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)
            logger.error("PrintWindow截屏失败: CreateCompatibleDC 失败")
            return None

        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        if not bitmap:
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)
            logger.error("PrintWindow截屏失败: CreateCompatibleBitmap 失败")
            return None

        old_obj = gdi32.SelectObject(mem_dc, bitmap)
        image = None
        try:
            ok = user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, self.PW_RENDERFULLCONTENT)
            if not ok:
                ok = user32.PrintWindow(wintypes.HWND(hwnd), mem_dc, 0)
            if not ok:
                logger.error("PrintWindow截屏失败: PrintWindow 返回 0")
                return None

            bmi = _BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = self.BI_RGB

            buf_len = width * height * 4
            buffer = ctypes.create_string_buffer(buf_len)
            rows = gdi32.GetDIBits(
                mem_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(bmi),
                self.DIB_RGB_COLORS,
            )
            if rows != height:
                logger.error(f"PrintWindow截屏失败: GetDIBits 行数异常 ({rows}/{height})")
                return None

            image = Image.frombytes("RGB", (width, height), buffer.raw, "raw", "BGRX")
            return image
        except Exception as e:
            logger.error(f"PrintWindow截屏失败: {e}")
            return None
        finally:
            if old_obj:
                gdi32.SelectObject(mem_dc, old_obj)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(wintypes.HWND(hwnd), hwnd_dc)

    def capture_and_save(self, rect: tuple[int, int, int, int],
                         prefix: str = "farm") -> tuple[Image.Image | None, str]:
        """截屏并保存到文件，返回(图片, 文件路径)"""
        image = self.capture_region(rect)
        if image is None:
            return None, ""
        filepath = self._make_screenshot_path(prefix)
        save_screenshot(image, filepath)
        return image, filepath

    def capture_window_print_and_save(self, hwnd: int,
                                      prefix: str = "farm") -> tuple[Image.Image | None, str]:
        """PrintWindow后台截屏并保存"""
        image = self.capture_window_print(hwnd)
        if image is None:
            return None, ""
        filepath = self._make_screenshot_path(prefix)
        save_screenshot(image, filepath)
        return image, filepath

    def cleanup_old_screenshots(self, max_count: int = 50):
        """清理旧截图，保留最新的max_count张"""
        try:
            files = sorted(
                [os.path.join(self._save_dir, f) for f in os.listdir(self._save_dir)
                 if f.endswith(".png")],
                key=os.path.getmtime
            )
            if len(files) > max_count:
                for f in files[:len(files) - max_count]:
                    os.remove(f)
        except Exception as e:
            logger.warning(f"清理截图失败: {e}")
