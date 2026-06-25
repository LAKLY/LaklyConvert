import os
import sys
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Text
import tkinter.font as tkfont

try:
    import numpy as np
    from PIL import Image, ImageFilter
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Ошибка импорта",
                         f"Не установлены необходимые библиотеки:\n{e}\n\n"
                         "Установите их командой:\n"
                         "pip install numpy pillow")
    sys.exit(1)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

try:
    import scipy
    from scipy.ndimage import binary_erosion, binary_dilation
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class BrailleConverter:
    SHIFT_VALUES = [0, 1, 2, 6, 3, 4, 5, 7]

    def __init__(self, width_chars=50, invert=False, dither_method='floyd',
                 greyscale_mode='luminance', monospace=True, vertical_scale=1.0,
                 contrast=0, brightness=0, auto_threshold=True, threshold=128,
                 use_median_filter=False, adaptive_threshold=False,
                 adaptive_block_size=15, adaptive_c=5,
                 block_width=2, block_height=4,
                 use_weighted_average=True,
                 post_processing=False,
                 auto_shift=True,
                 selection_mode='mse'):
        self.width_chars = width_chars
        self.invert = invert
        self.dither_method = dither_method
        self.greyscale_mode = greyscale_mode
        self.monospace = monospace
        self.vertical_scale = vertical_scale
        self.contrast = contrast
        self.brightness = brightness
        self.auto_threshold = auto_threshold
        self.threshold = threshold
        self.use_median_filter = use_median_filter
        self.adaptive_threshold = adaptive_threshold
        self.adaptive_block_size = adaptive_block_size
        self.adaptive_c = adaptive_c
        self.block_width = block_width
        self.block_height = block_height
        self.use_weighted_average = use_weighted_average
        self.post_processing = post_processing
        self.auto_shift = auto_shift
        self.selection_mode = selection_mode

        self._precompute_symbol_vectors()

    def _precompute_symbol_vectors(self):
        self.symbol_vectors = np.zeros((256, 8), dtype=np.uint8)
        for code in range(256):
            bits = []
            for i in range(8):
                bit = 1 if (code >> self.SHIFT_VALUES[i]) & 1 else 0
                bits.append(bit)
            self.symbol_vectors[code] = bits

        if self.block_width == 2 and self.block_height == 4:
            coords = [(0,0), (1,0), (0,1), (1,1), (0,2), (1,2), (0,3), (1,3)]
            cx, cy = 0.5, 1.5
            sigma = 1.0
            self.weights = np.zeros(8)
            for i, (x, y) in enumerate(coords):
                self.weights[i] = np.exp(-((x - cx)**2 + (y - cy)**2) / (2 * sigma**2))
            self.weights /= np.sum(self.weights)
        else:
            self.weights = np.ones(8) / 8.0

    def _to_greyscale(self, rgb_array):
        if self.greyscale_mode == 'luminance':
            return 0.2126 * rgb_array[:, :, 0] + 0.7152 * rgb_array[:, :, 1] + 0.0722 * rgb_array[:, :, 2]
        elif self.greyscale_mode == 'lightness':
            return (np.max(rgb_array, axis=2) + np.min(rgb_array, axis=2)) / 2.0
        elif self.greyscale_mode == 'average':
            return np.mean(rgb_array, axis=2)
        elif self.greyscale_mode == 'value':
            return np.max(rgb_array, axis=2)
        else:
            raise ValueError(f"Неизвестный режим серого: {self.greyscale_mode}")

    def _apply_contrast_brightness(self, grey):
        factor = (100 + self.contrast) / 100.0
        grey = (grey - 128) * factor + 128 + self.brightness
        return np.clip(grey, 0, 255).astype(np.uint8)

    def _median_filter(self, grey, size=3):
        img = Image.fromarray(grey.astype(np.uint8))
        img = img.filter(ImageFilter.MedianFilter(size=size))
        return np.array(img, dtype=np.uint8)

    def _otsu_threshold(self, grey):
        hist, _ = np.histogram(grey, bins=256, range=(0, 256))
        total = grey.size
        if total == 0:
            return 128
        sum_total = np.sum(np.arange(256) * hist)
        sum_b = 0
        w_b = 0
        w_f = 0
        var_max = 0
        threshold = 0
        for t in range(256):
            w_b += hist[t]
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += t * hist[t]
            m_b = sum_b / w_b
            m_f = (sum_total - sum_b) / w_f
            var_between = w_b * w_f * (m_b - m_f) ** 2
            if var_between > var_max:
                var_max = var_between
                threshold = t
        return threshold

    def _adaptive_threshold_bradley(self, grey, block_size=15, c=5):
        pad = block_size // 2
        padded = np.pad(grey, pad, mode='reflect')
        try:
            import scipy.signal
            kernel = np.ones((block_size, block_size), dtype=np.float32) / (block_size * block_size)
            mean = scipy.signal.convolve2d(padded, kernel, mode='valid')
        except ImportError:
            int_img = np.zeros((grey.shape[0] + 1, grey.shape[1] + 1), dtype=np.uint64)
            int_img[1:, 1:] = np.cumsum(np.cumsum(grey.astype(np.uint64), axis=0), axis=1)
            mean = np.zeros_like(grey, dtype=np.float32)
            for y in range(grey.shape[0]):
                y1 = y
                y2 = y + block_size
                if y2 > grey.shape[0]:
                    y2 = grey.shape[0]
                    y1 = grey.shape[0] - block_size
                for x in range(grey.shape[1]):
                    x1 = x
                    x2 = x + block_size
                    if x2 > grey.shape[1]:
                        x2 = grey.shape[1]
                        x1 = grey.shape[1] - block_size
                    area = (y2 - y1) * (x2 - x1)
                    if area == 0:
                        mean[y, x] = 128
                        continue
                    sum_val = int_img[y2, x2] - int_img[y1, x2] - int_img[y2, x1] + int_img[y1, x1]
                    mean[y, x] = sum_val / area
        thresh = mean - c
        binary = (grey > thresh).astype(np.uint8)
        return binary

    def _floyd_steinberg_dither(self, grey):
        h, w = grey.shape
        img = grey.astype(np.float32)
        output = np.zeros((h, w), dtype=np.uint8)

        for y in range(h):
            for x in range(w):
                old = img[y, x]
                new = 1 if old >= 128 else 0
                output[y, x] = new
                err = old - (new * 255)

                if x + 1 < w:
                    img[y, x + 1] += err * (7 / 16)
                if y + 1 < h:
                    if x > 0:
                        img[y + 1, x - 1] += err * (3 / 16)
                    img[y + 1, x] += err * (5 / 16)
                    if x + 1 < w:
                        img[y + 1, x + 1] += err * (1 / 16)
        return output

    def _bayer_dither(self, grey):
        h, w = grey.shape
        bayer = np.array([
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5]
        ]) * (255 / 16)
        bayer_tiled = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w]
        binary = (grey > bayer_tiled).astype(np.uint8)
        return binary

    def _post_process(self, binary):
        if SCIPY_AVAILABLE:
            structure = np.ones((3, 3), dtype=bool)
            eroded = binary_erosion(binary, structure)
            dilated = binary_dilation(eroded, structure)
            return dilated.astype(np.uint8)
        else:
            img = Image.fromarray(binary * 255)
            eroded = img.filter(ImageFilter.MinFilter(3))
            dilated = eroded.filter(ImageFilter.MaxFilter(3))
            return (np.array(dilated) > 128).astype(np.uint8)

    def _evaluate_shift(self, grey, binary, shift_x, shift_y):
        h, w = grey.shape
        bw = self.block_width
        bh = self.block_height
        new_h = h - shift_y
        new_w = w - shift_x
        new_h = new_h - (new_h % bh)
        new_w = new_w - (new_w % bw)
        if new_h < bh or new_w < bw:
            return float('inf')

        reconstructed = np.zeros((new_h, new_w), dtype=np.uint8)
        for y in range(0, new_h, bh):
            for x in range(0, new_w, bw):
                block = binary[shift_y + y:shift_y + y + bh, shift_x + x:shift_x + x + bw]
                vec = np.zeros(8, dtype=np.uint8)
                idx = 0
                for dy in range(bh):
                    for dx in range(bw):
                        if idx < 8:
                            vec[idx] = block[dy, dx]
                            idx += 1
                best_code = self._find_best_symbol(vec)
                sym_vec = self.symbol_vectors[best_code]
                for i, (dx, dy) in enumerate(self._get_coords()):
                    if i < 8:
                        reconstructed[y + dy, x + dx] = sym_vec[i]
        orig = binary[shift_y:shift_y + new_h, shift_x:shift_x + new_w]
        sad = np.sum(np.abs(orig.astype(np.int16) - reconstructed.astype(np.int16)))
        return sad

    def _get_coords(self):
        return [(0,0), (1,0), (0,1), (1,1), (0,2), (1,2), (0,3), (1,3)]

    def _find_best_symbol(self, block_vector):
        if self.selection_mode == 'direct':
            code = 0
            for i, bit in enumerate(block_vector):
                if bit:
                    code |= (1 << self.SHIFT_VALUES[i])
            return code
        elif self.selection_mode == 'mse':
            vec = np.array(block_vector, dtype=np.float32)
            diff = self.symbol_vectors.astype(np.float32) - vec
            mse = np.mean(diff ** 2, axis=1)
            return np.argmin(mse)
        elif self.selection_mode == 'weighted_mse':
            vec = np.array(block_vector, dtype=np.float32)
            diff = self.symbol_vectors.astype(np.float32) - vec
            weighted_mse = np.mean((diff ** 2) * self.weights, axis=1)
            return np.argmin(weighted_mse)
        else:
            code = 0
            for i, bit in enumerate(block_vector):
                if bit:
                    code |= (1 << self.SHIFT_VALUES[i])
            return code

    def convert(self, image_path):
        img = Image.open(image_path).convert('RGB')
        orig_w, orig_h = img.size

        bw = self.block_width
        bh = self.block_height

        target_w = self.width_chars * bw
        if target_w < bw:
            target_w = bw
        scale = target_w / orig_w
        new_h = int(orig_h * scale * self.vertical_scale)
        target_w = target_w - (target_w % bw)
        new_h = new_h - (new_h % bh)
        if new_h < bh:
            new_h = bh

        img_resized = img.resize((target_w, new_h), Image.LANCZOS)
        img_array = np.array(img_resized, dtype=np.float32)

        grey = self._to_greyscale(img_array)
        grey = self._apply_contrast_brightness(grey)

        if self.use_median_filter:
            grey = self._median_filter(grey, size=3)

        if self.dither_method == 'floyd':
            binary = self._floyd_steinberg_dither(grey)
        elif self.dither_method == 'bayer':
            binary = self._bayer_dither(grey)
        else:
            if self.adaptive_threshold:
                binary = self._adaptive_threshold_bradley(grey, self.adaptive_block_size, self.adaptive_c)
            else:
                if self.auto_threshold:
                    thresh = self._otsu_threshold(grey)
                else:
                    thresh = self.threshold
                binary = (grey >= thresh).astype(np.uint8)

        if self.post_processing:
            binary = self._post_process(binary)

        if self.invert:
            binary = 1 - binary

        if self.auto_shift:
            best_shift = (0, 0)
            best_score = float('inf')
            for sx in range(bw):
                for sy in range(bh):
                    score = self._evaluate_shift(grey, binary, sx, sy)
                    if score < best_score:
                        best_score = score
                        best_shift = (sx, sy)
            shift_x, shift_y = best_shift
        else:
            shift_x, shift_y = 0, 0

        h, w = binary.shape
        h_crop = h - shift_y
        w_crop = w - shift_x
        h_crop = h_crop - (h_crop % bh)
        w_crop = w_crop - (w_crop % bw)
        if h_crop < bh or w_crop < bw:
            shift_x, shift_y = 0, 0
            h_crop = h - (h % bh)
            w_crop = w - (w % bw)

        binary_cropped = binary[shift_y:shift_y + h_crop, shift_x:shift_x + w_crop]
        grey_cropped = grey[shift_y:shift_y + h_crop, shift_x:shift_x + w_crop]

        chars = []
        coords = self._get_coords()
        for y in range(0, h_crop, bh):
            line = []
            for x in range(0, w_crop, bw):
                block_bits = np.zeros(8, dtype=np.uint8)
                if self.use_weighted_average:
                    idx = 0
                    for dy in range(bh):
                        for dx in range(bw):
                            if idx < 8:
                                cx = x + dx
                                cy = y + dy
                                y_min = max(0, cy - 1)
                                y_max = min(h_crop - 1, cy + 1)
                                x_min = max(0, cx - 1)
                                x_max = min(w_crop - 1, cx + 1)
                                patch = grey_cropped[y_min:y_max+1, x_min:x_max+1]
                                avg = np.mean(patch)
                                block_bits[idx] = 1 if avg >= 128 else 0
                                idx += 1
                else:
                    idx = 0
                    for dy in range(bh):
                        for dx in range(bw):
                            if idx < 8:
                                if y + dy < h_crop and x + dx < w_crop:
                                    block_bits[idx] = binary_cropped[y + dy, x + dx]
                                else:
                                    block_bits[idx] = 0
                                idx += 1

                code = self._find_best_symbol(block_bits)
                if code == 0:
                    if self.monospace:
                        line.append(chr(0x2804))
                    else:
                        line.append(chr(0x2800))
                else:
                    line.append(chr(0x2800 + code))
            chars.append(''.join(line))
        return '\n'.join(chars)


class BrailleApp:
    CONFIG_FILE = "config.json"

    def __init__(self, root):
        self.root = root
        self.root.title("LaklyConvert")
        self.root.geometry("1500x700")
        self.root.minsize(1100, 500)

        # Переменные настроек (значения по умолчанию)
        self.defaults = {
            'width': 60,
            'invert': False,
            'dither_method': 'floyd',
            'greyscale': 'luminance',
            'vertical_scale': 1.1,
            'contrast': 0,
            'brightness': 0,
            'auto_threshold': True,
            'threshold': 128,
            'monospace': True,
            'dark_theme': False,
            'use_median_filter': False,
            'adaptive_threshold': False,
            'adaptive_block_size': 15,
            'adaptive_c': 5,
            'block_size': '2x4',
            'use_weighted_average': True,
            'post_processing': False,
            'auto_shift': True,
            'selection_mode': 'mse'
        }

        self.width_var = tk.IntVar(value=self.defaults['width'])
        self.invert_var = tk.BooleanVar(value=self.defaults['invert'])
        self.dither_method_var = tk.StringVar(value=self.defaults['dither_method'])
        self.greyscale_var = tk.StringVar(value=self.defaults['greyscale'])
        self.vertical_scale_var = tk.DoubleVar(value=self.defaults['vertical_scale'])
        self.contrast_var = tk.IntVar(value=self.defaults['contrast'])
        self.brightness_var = tk.IntVar(value=self.defaults['brightness'])
        self.auto_threshold_var = tk.BooleanVar(value=self.defaults['auto_threshold'])
        self.threshold_var = tk.IntVar(value=self.defaults['threshold'])
        self.monospace_var = tk.BooleanVar(value=self.defaults['monospace'])
        self.dark_theme_var = tk.BooleanVar(value=self.defaults['dark_theme'])

        self.use_median_filter_var = tk.BooleanVar(value=self.defaults['use_median_filter'])
        self.adaptive_threshold_var = tk.BooleanVar(value=self.defaults['adaptive_threshold'])
        self.adaptive_block_size_var = tk.IntVar(value=self.defaults['adaptive_block_size'])
        self.adaptive_c_var = tk.IntVar(value=self.defaults['adaptive_c'])

        self.block_size_var = tk.StringVar(value=self.defaults['block_size'])
        self.use_weighted_average_var = tk.BooleanVar(value=self.defaults['use_weighted_average'])
        self.post_processing_var = tk.BooleanVar(value=self.defaults['post_processing'])
        self.auto_shift_var = tk.BooleanVar(value=self.defaults['auto_shift'])
        self.selection_mode_var = tk.StringVar(value=self.defaults['selection_mode'])

        self.last_image_path = None
        self.line_count = 0
        self.current_text = ""

        self._create_widgets()
        self._load_config()

        self.root.bind("<Configure>", self._on_configure)
        self.root.bind("<Map>", lambda e: self.root.after_idle(self._adjust_font_size))
        self.root.bind("<Destroy>", self._on_destroy)

        default_img = os.path.join(os.path.dirname(__file__), 'select.png')
        if os.path.exists(default_img):
            self.load_image(default_img)
        else:
            self.status_var.set("Откройте изображение через кнопку или перетащите файл")

        if DND_AVAILABLE:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)

    def _create_widgets(self):
        self.control_frame = ttk.Frame(self.root, padding=3)
        self.control_frame.pack(fill=tk.X, side=tk.TOP)

        # ---- Строка 1: кнопки ----
        buttons_frame = ttk.Frame(self.control_frame)
        buttons_frame.pack(fill=tk.X, pady=1)

        btn_open = ttk.Button(buttons_frame, text="Открыть", command=self.open_image)
        btn_open.pack(side=tk.LEFT, padx=2)

        btn_convert = ttk.Button(buttons_frame, text="Применить", command=self.reconvert)
        btn_convert.pack(side=tk.LEFT, padx=2)

        btn_copy = ttk.Button(buttons_frame, text="Копировать", command=self.copy_to_clipboard)
        btn_copy.pack(side=tk.LEFT, padx=2)

        btn_save = ttk.Button(buttons_frame, text="Сохранить", command=self.save_to_file)
        btn_save.pack(side=tk.LEFT, padx=2)

        btn_clear = ttk.Button(buttons_frame, text="Очистить", command=self.clear_text)
        btn_clear.pack(side=tk.LEFT, padx=2)

        btn_reset = ttk.Button(buttons_frame, text="Сбросить настройки", command=self.reset_settings)
        btn_reset.pack(side=tk.LEFT, padx=2)

        # ---- Строка 2: основные настройки ----
        settings_frame = ttk.Frame(self.control_frame)
        settings_frame.pack(fill=tk.X, pady=1)

        ttk.Label(settings_frame, text="Шир:").pack(side=tk.LEFT, padx=(2, 1))
        spin_width = ttk.Spinbox(settings_frame, from_=2, to=500, increment=2,
                                 textvariable=self.width_var, width=4)
        spin_width.pack(side=tk.LEFT, padx=1)
        spin_width.bind('<Return>', lambda e: self.reconvert())
        spin_width.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(settings_frame, text="Верт:").pack(side=tk.LEFT, padx=(4, 1))
        spin_vscale = ttk.Spinbox(settings_frame, from_=0.3, to=2.0, increment=0.1,
                                  textvariable=self.vertical_scale_var, width=4)
        spin_vscale.pack(side=tk.LEFT, padx=1)
        spin_vscale.bind('<Return>', lambda e: self.reconvert())
        spin_vscale.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(settings_frame, text="Контр:").pack(side=tk.LEFT, padx=(4, 1))
        spin_contrast = ttk.Spinbox(settings_frame, from_=-100, to=100, increment=5,
                                    textvariable=self.contrast_var, width=4)
        spin_contrast.pack(side=tk.LEFT, padx=1)
        spin_contrast.bind('<Return>', lambda e: self.reconvert())
        spin_contrast.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(settings_frame, text="Ярк:").pack(side=tk.LEFT, padx=(4, 1))
        spin_bright = ttk.Spinbox(settings_frame, from_=-100, to=100, increment=5,
                                  textvariable=self.brightness_var, width=4)
        spin_bright.pack(side=tk.LEFT, padx=1)
        spin_bright.bind('<Return>', lambda e: self.reconvert())
        spin_bright.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(settings_frame, text="Метод:").pack(side=tk.LEFT, padx=(4, 1))
        method_combo = ttk.Combobox(settings_frame, textvariable=self.dither_method_var,
                                    values=['none', 'floyd', 'bayer'], state='readonly', width=6)
        method_combo.pack(side=tk.LEFT, padx=1)
        method_combo.bind('<<ComboboxSelected>>', lambda e: self.reconvert())
        method_combo.bind('<<ComboboxSelected>>', lambda e: self._save_config())

        chk_auto = ttk.Checkbutton(settings_frame, text="Автопорог", variable=self.auto_threshold_var,
                                   command=self._toggle_threshold)
        chk_auto.pack(side=tk.LEFT, padx=2)

        ttk.Label(settings_frame, text="Порог:").pack(side=tk.LEFT, padx=(2, 1))
        spin_thresh = ttk.Spinbox(settings_frame, from_=0, to=255, increment=1,
                                  textvariable=self.threshold_var, width=4)
        spin_thresh.pack(side=tk.LEFT, padx=1)
        spin_thresh.bind('<Return>', lambda e: self.reconvert())
        spin_thresh.bind('<<Modified>>', lambda e: self._save_config())

        # ---- Строка 3: дополнительные настройки ----
        extra_frame = ttk.Frame(self.control_frame)
        extra_frame.pack(fill=tk.X, pady=1)

        chk_median = ttk.Checkbutton(extra_frame, text="Медиан", variable=self.use_median_filter_var,
                                     command=self._on_check_change)
        chk_median.pack(side=tk.LEFT, padx=2)

        chk_adaptive = ttk.Checkbutton(extra_frame, text="Адаптив", variable=self.adaptive_threshold_var,
                                       command=self._toggle_adaptive)
        chk_adaptive.pack(side=tk.LEFT, padx=2)

        ttk.Label(extra_frame, text="Блок:").pack(side=tk.LEFT, padx=(2, 1))
        spin_block = ttk.Spinbox(extra_frame, from_=3, to=51, increment=2,
                                 textvariable=self.adaptive_block_size_var, width=3)
        spin_block.pack(side=tk.LEFT, padx=1)
        spin_block.bind('<Return>', lambda e: self.reconvert())
        spin_block.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(extra_frame, text="C:").pack(side=tk.LEFT, padx=(2, 1))
        spin_c = ttk.Spinbox(extra_frame, from_=0, to=20, increment=1,
                             textvariable=self.adaptive_c_var, width=3)
        spin_c.pack(side=tk.LEFT, padx=1)
        spin_c.bind('<Return>', lambda e: self.reconvert())
        spin_c.bind('<<Modified>>', lambda e: self._save_config())

        ttk.Label(extra_frame, text="Размер:").pack(side=tk.LEFT, padx=(4, 1))
        block_combo = ttk.Combobox(extra_frame, textvariable=self.block_size_var,
                                   values=['2x4', '3x6', '4x8'], state='readonly', width=5)
        block_combo.pack(side=tk.LEFT, padx=1)
        block_combo.bind('<<ComboboxSelected>>', lambda e: self.reconvert())
        block_combo.bind('<<ComboboxSelected>>', lambda e: self._save_config())

        ttk.Label(extra_frame, text="Подбор:").pack(side=tk.LEFT, padx=(4, 1))
        sel_combo = ttk.Combobox(extra_frame, textvariable=self.selection_mode_var,
                                 values=['direct', 'mse', 'weighted_mse'], state='readonly', width=9)
        sel_combo.pack(side=tk.LEFT, padx=1)
        sel_combo.bind('<<ComboboxSelected>>', lambda e: self.reconvert())
        sel_combo.bind('<<ComboboxSelected>>', lambda e: self._save_config())

        chk_weighted = ttk.Checkbutton(extra_frame, text="Усредн.", variable=self.use_weighted_average_var,
                                       command=self._on_check_change)
        chk_weighted.pack(side=tk.LEFT, padx=2)

        chk_post = ttk.Checkbutton(extra_frame, text="Пост-обр.", variable=self.post_processing_var,
                                   command=self._on_check_change)
        chk_post.pack(side=tk.LEFT, padx=2)

        chk_shift = ttk.Checkbutton(extra_frame, text="Сдвиг", variable=self.auto_shift_var,
                                    command=self._on_check_change)
        chk_shift.pack(side=tk.LEFT, padx=2)

        chk_invert = ttk.Checkbutton(extra_frame, text="Инверт.", variable=self.invert_var,
                                     command=self._on_check_change)
        chk_invert.pack(side=tk.LEFT, padx=2)

        chk_mono = ttk.Checkbutton(extra_frame, text="Плотный режим", variable=self.monospace_var,
                                   command=self._on_check_change)
        chk_mono.pack(side=tk.LEFT, padx=2)

        ttk.Label(extra_frame, text="Режим:").pack(side=tk.LEFT, padx=(4, 1))
        greyscale_combo = ttk.Combobox(extra_frame, textvariable=self.greyscale_var,
                                       values=['luminance', 'lightness', 'average', 'value'],
                                       state='readonly', width=8)
        greyscale_combo.pack(side=tk.LEFT, padx=1)
        greyscale_combo.bind('<<ComboboxSelected>>', lambda e: self.reconvert())
        greyscale_combo.bind('<<ComboboxSelected>>', lambda e: self._save_config())

        chk_dark = ttk.Checkbutton(extra_frame, text="Тёмная", variable=self.dark_theme_var,
                                   command=self.toggle_theme)
        chk_dark.pack(side=tk.LEFT, padx=2)

        self.text_area = Text(self.root, wrap=tk.NONE, font=('Courier New', 12),
                              bg='white', fg='black', relief=tk.FLAT)
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        self.status_var = tk.StringVar(value="Готово")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, ipady=1)

        self._apply_theme(self.dark_theme_var.get())

    def _on_check_change(self):
        self.reconvert()
        self._save_config()

    def _toggle_threshold(self):
        state = 'disabled' if self.auto_threshold_var.get() else 'normal'
        for child in self.control_frame.winfo_children():
            for sub in child.winfo_children():
                if isinstance(sub, ttk.Spinbox):
                    var = sub.cget('textvariable')
                    if var and str(var) == str(self.threshold_var):
                        sub.config(state=state)
                        break
        self.reconvert()
        self._save_config()

    def _toggle_adaptive(self):
        if self.adaptive_threshold_var.get():
            self.auto_threshold_var.set(False)
            self._toggle_threshold()
        self.reconvert()
        self._save_config()

    def _apply_theme(self, dark):
        style = ttk.Style()
        style.theme_use('clam')
        if dark:
            bg_main = '#2b2b2b'
            bg_panel = '#3c3c3c'
            bg_text = '#1e1e1e'
            fg_text = '#ffffff'
            fg_general = '#ffffff'
            bg_button = '#5a5a5a'
            bg_entry = '#3c3c3c'
        else:
            bg_main = '#f0f0f0'
            bg_panel = '#f0f0f0'
            bg_text = '#ffffff'
            fg_text = '#000000'
            fg_general = '#000000'
            bg_button = '#e0e0e0'
            bg_entry = '#ffffff'

        self.root.configure(bg=bg_main)
        self.text_area.config(bg=bg_text, fg=fg_text, insertbackground=fg_text)
        style.configure('TFrame', background=bg_panel)
        style.configure('TLabel', background=bg_panel, foreground=fg_general)
        style.configure('TButton', background=bg_button, foreground=fg_general)
        style.configure('TCheckbutton', background=bg_panel, foreground=fg_general)
        style.configure('TCombobox', fieldbackground=bg_entry, background=bg_entry, foreground=fg_general)
        style.configure('TSpinbox', fieldbackground=bg_entry, background=bg_entry, foreground=fg_general)
        style.configure('TStatusBar.TLabel', background=bg_panel, foreground=fg_general)
        self.status_bar.config(style='TStatusBar.TLabel')
        for child in self.control_frame.winfo_children():
            if isinstance(child, ttk.Frame):
                child.configure(style='TFrame')

    def toggle_theme(self):
        self._apply_theme(self.dark_theme_var.get())
        self._save_config()

    def _get_config_dict(self):
        return {
            'width': self.width_var.get(),
            'invert': self.invert_var.get(),
            'dither_method': self.dither_method_var.get(),
            'greyscale': self.greyscale_var.get(),
            'vertical_scale': self.vertical_scale_var.get(),
            'contrast': self.contrast_var.get(),
            'brightness': self.brightness_var.get(),
            'auto_threshold': self.auto_threshold_var.get(),
            'threshold': self.threshold_var.get(),
            'monospace': self.monospace_var.get(),
            'dark_theme': self.dark_theme_var.get(),
            'use_median_filter': self.use_median_filter_var.get(),
            'adaptive_threshold': self.adaptive_threshold_var.get(),
            'adaptive_block_size': self.adaptive_block_size_var.get(),
            'adaptive_c': self.adaptive_c_var.get(),
            'block_size': self.block_size_var.get(),
            'use_weighted_average': self.use_weighted_average_var.get(),
            'post_processing': self.post_processing_var.get(),
            'auto_shift': self.auto_shift_var.get(),
            'selection_mode': self.selection_mode_var.get()
        }

    def _save_config(self):
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._get_config_dict(), f, indent=4, ensure_ascii=False)
        except Exception as e:
            # Не показываем ошибку, чтобы не раздражать пользователя
            print(f"Ошибка сохранения конфига: {e}")

    def _load_config(self):
        if not os.path.exists(self.CONFIG_FILE):
            return
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Устанавливаем значения, если они есть в конфиге
            for key, value in config.items():
                if key == 'width':
                    self.width_var.set(value)
                elif key == 'invert':
                    self.invert_var.set(value)
                elif key == 'dither_method':
                    self.dither_method_var.set(value)
                elif key == 'greyscale':
                    self.greyscale_var.set(value)
                elif key == 'vertical_scale':
                    self.vertical_scale_var.set(value)
                elif key == 'contrast':
                    self.contrast_var.set(value)
                elif key == 'brightness':
                    self.brightness_var.set(value)
                elif key == 'auto_threshold':
                    self.auto_threshold_var.set(value)
                elif key == 'threshold':
                    self.threshold_var.set(value)
                elif key == 'monospace':
                    self.monospace_var.set(value)
                elif key == 'dark_theme':
                    self.dark_theme_var.set(value)
                elif key == 'use_median_filter':
                    self.use_median_filter_var.set(value)
                elif key == 'adaptive_threshold':
                    self.adaptive_threshold_var.set(value)
                elif key == 'adaptive_block_size':
                    self.adaptive_block_size_var.set(value)
                elif key == 'adaptive_c':
                    self.adaptive_c_var.set(value)
                elif key == 'block_size':
                    self.block_size_var.set(value)
                elif key == 'use_weighted_average':
                    self.use_weighted_average_var.set(value)
                elif key == 'post_processing':
                    self.post_processing_var.set(value)
                elif key == 'auto_shift':
                    self.auto_shift_var.set(value)
                elif key == 'selection_mode':
                    self.selection_mode_var.set(value)
            # Применяем тему
            self._apply_theme(self.dark_theme_var.get())
            # Обновляем состояние порога
            self._toggle_threshold()
        except Exception as e:
            print(f"Ошибка загрузки конфига: {e}")

    def reset_settings(self):
        """Сброс всех настроек к значениям по умолчанию."""
        for key, value in self.defaults.items():
            if key == 'width':
                self.width_var.set(value)
            elif key == 'invert':
                self.invert_var.set(value)
            elif key == 'dither_method':
                self.dither_method_var.set(value)
            elif key == 'greyscale':
                self.greyscale_var.set(value)
            elif key == 'vertical_scale':
                self.vertical_scale_var.set(value)
            elif key == 'contrast':
                self.contrast_var.set(value)
            elif key == 'brightness':
                self.brightness_var.set(value)
            elif key == 'auto_threshold':
                self.auto_threshold_var.set(value)
            elif key == 'threshold':
                self.threshold_var.set(value)
            elif key == 'monospace':
                self.monospace_var.set(value)
            elif key == 'dark_theme':
                self.dark_theme_var.set(value)
            elif key == 'use_median_filter':
                self.use_median_filter_var.set(value)
            elif key == 'adaptive_threshold':
                self.adaptive_threshold_var.set(value)
            elif key == 'adaptive_block_size':
                self.adaptive_block_size_var.set(value)
            elif key == 'adaptive_c':
                self.adaptive_c_var.set(value)
            elif key == 'block_size':
                self.block_size_var.set(value)
            elif key == 'use_weighted_average':
                self.use_weighted_average_var.set(value)
            elif key == 'post_processing':
                self.post_processing_var.set(value)
            elif key == 'auto_shift':
                self.auto_shift_var.set(value)
            elif key == 'selection_mode':
                self.selection_mode_var.set(value)
        self._apply_theme(self.dark_theme_var.get())
        self._toggle_threshold()
        self._save_config()
        self.reconvert()
        self.status_var.set("Настройки сброшены")

    def _on_destroy(self, event):
        if event.widget == self.root:
            self._save_config()

    def _on_drop(self, event):
        if not DND_AVAILABLE:
            return
        files = event.data.split()
        if files:
            path = files[0].strip('{}')
            if os.path.isfile(path):
                self.load_image(path)

    def _on_configure(self, event):
        if event.widget == self.root:
            self.root.after_idle(self._adjust_font_size)

    def open_image(self):
        file_path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp"), ("All files", "*.*")]
        )
        if file_path:
            self.load_image(file_path)

    def load_image(self, file_path):
        self.last_image_path = file_path
        self.reconvert()

    def reconvert(self):
        if not self.last_image_path:
            self.status_var.set("Не выбрано изображение")
            return

        def do_convert():
            try:
                self.status_var.set("Конвертация...")
                self.root.update_idletasks()

                block_str = self.block_size_var.get()
                bw, bh = map(int, block_str.split('x'))

                converter = BrailleConverter(
                    width_chars=self.width_var.get(),
                    invert=self.invert_var.get(),
                    dither_method=self.dither_method_var.get(),
                    greyscale_mode=self.greyscale_var.get(),
                    monospace=self.monospace_var.get(),
                    vertical_scale=self.vertical_scale_var.get(),
                    contrast=self.contrast_var.get(),
                    brightness=self.brightness_var.get(),
                    auto_threshold=self.auto_threshold_var.get(),
                    threshold=self.threshold_var.get(),
                    use_median_filter=self.use_median_filter_var.get(),
                    adaptive_threshold=self.adaptive_threshold_var.get(),
                    adaptive_block_size=self.adaptive_block_size_var.get(),
                    adaptive_c=self.adaptive_c_var.get(),
                    block_width=bw,
                    block_height=bh,
                    use_weighted_average=self.use_weighted_average_var.get(),
                    post_processing=self.post_processing_var.get(),
                    auto_shift=self.auto_shift_var.get(),
                    selection_mode=self.selection_mode_var.get()
                )
                result = converter.convert(self.last_image_path)

                self.root.after(0, lambda: self._update_text(result))
                self.root.after(0, lambda: self.status_var.set(
                    f"Готово. Символов: {len(result)}, строк: {len(result.splitlines())}"
                ))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self._show_error(err_msg))

        threading.Thread(target=do_convert, daemon=True).start()

    def _update_text(self, text):
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(1.0, text)
        self.current_text = text
        self.line_count = len(text.splitlines())
        self.root.after_idle(self._adjust_font_size)

    def _show_error(self, msg):
        messagebox.showerror("Ошибка", f"Не удалось конвертировать изображение:\n{msg}")
        self.status_var.set("Ошибка")

    def copy_to_clipboard(self):
        text = self.text_area.get(1.0, tk.END).rstrip('\n')
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("Скопировано в буфер обмена")
        else:
            self.status_var.set("Нет текста для копирования")

    def save_to_file(self):
        text = self.text_area.get(1.0, tk.END).rstrip('\n')
        if not text:
            self.status_var.set("Нет текста для сохранения")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                self.status_var.set(f"Сохранено в {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось сохранить файл:\n{e}")

    def clear_text(self):
        self.text_area.delete(1.0, tk.END)
        self.current_text = ""
        self.line_count = 0
        self.status_var.set("Текст очищен")

    def _adjust_font_size(self):
        if not self.text_area.winfo_exists():
            return
        try:
            self.root.update_idletasks()
            width_pixels = self.text_area.winfo_width() - 10
            height_pixels = self.text_area.winfo_height() - 10
        except:
            return
        if width_pixels <= 10 or height_pixels <= 10:
            return

        chars = max(1, self.width_var.get())
        lines = max(1, self.line_count)

        low, high = 4, 80
        best = low
        while low <= high:
            mid = (low + high) // 2
            font = tkfont.Font(family="Courier New", size=mid)
            str_width = font.measure("W" * chars)
            str_height = font.metrics('linespace') * lines
            if str_width <= width_pixels and str_height <= height_pixels:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        self.text_area.configure(font=("Courier New", best))


if __name__ == '__main__':
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = BrailleApp(root)
    root.mainloop()