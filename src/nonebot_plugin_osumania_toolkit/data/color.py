# 星数颜色数据与函数
class sr_color:
    STAR_BG_STOPS = [
        (0.0, "#aaaaaa"),
        (0.9, "#4bb3fd"),
        (2.0, "#4fffd5"),
        (3.0, "#d3f557"),
        (4.0, "#fda265"),
        (5.0, "#f94d79"),
        (6.0, "#b64cc1"),
        (7.0, "#5654ca"),
        (8.0, "#14117d"),
        (9.0, "#000000"),
        (9999.9, "#000000"),
    ]
    STAR_TEXT_STOPS = [
        (0.0, "#000000"),
        (6.49, "#000000"),
        (6.5, "#ffd966"),
        (8.9, "#ffd966"),
        (9.0, "#f6f05c"),
        (10.0, "#ff7a69"),
        (11.0, "#e74a95"),
        (12.0, "#9a57ce"),
        (12.39, "#6563de"),
        (9999.9, "#6563de"),
    ]
    
    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        color = hex_color.lstrip("#")
        if len(color) == 3:
            color = "".join(ch + ch for ch in color)
        value = int(color, 16)
        return ((value >> 16) & 255, (value >> 8) & 255, value & 255)
    
    def _rgb_to_hex(self, r: int, g: int, b: int) -> str:
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _interpolate_color(self, hex_a: str, hex_b: str, t: float) -> str:
        ar, ag, ab = self._hex_to_rgb(hex_a)
        br, bg, bb = self._hex_to_rgb(hex_b)
        r = round(ar + (br - ar) * t)
        g = round(ag + (bg - ag) * t)
        b = round(ab + (bb - ab) * t)
        return self._rgb_to_hex(r, g, b)
    
    def _color_for(self, value: float, stops: list[tuple[float, str]], fallback: str) -> str:
        if not isinstance(value, (int, float)):
            return fallback
        if value <= stops[0][0]:
            return stops[0][1]
        for i in range(len(stops) - 1):
            lv, lc = stops[i]
            rv, rc = stops[i + 1]
            if lv <= value <= rv:
                t = (value - lv) / (rv - lv or 1.0)
                return self._interpolate_color(lc, rc, t)
        return stops[-1][1]
    
    def convert(self, v: int) -> float:
            c = v / 255.0
            if c <= 0.03928:
                return c / 12.92
            return ((c + 0.055) / 1.055) ** 2.4
        
    def _relative_luminance(self, hex_color: str) -> float:
        r, g, b = self._hex_to_rgb(hex_color)
        return 0.2126 * self.convert(r) + 0.7152 * self.convert(g) + 0.0722 * self.convert(b)

    def _contrast_ratio(self, hex_a: str, hex_b: str) -> float:
        l1 = self._relative_luminance(hex_a)
        l2 = self._relative_luminance(hex_b)
        bright = max(l1, l2)
        dark = min(l1, l2)
        return (bright + 0.05) / (dark + 0.05)

    def _pick_readable_text_color(self, star_value: float, bg_color: str, preferred_color: str) -> str:
        if isinstance(star_value, (int, float)) and star_value > 12:
            return "#6563de"
        if isinstance(star_value, (int, float)) and 6.0 <= star_value <= 6.49:
            return "#000000"
        if isinstance(star_value, (int, float)) and 6.5 <= star_value <= 8.9:
            return "#ffd966"
        preferred = preferred_color or "#f6fbff"
        if self._contrast_ratio(bg_color, preferred) >= 4.5:
            return preferred
        candidate_dark = "#111111"
        candidate_light = "#f6fbff"
        candidate_gold = "#FFD966"
        dark_ratio = self._contrast_ratio(bg_color, candidate_dark)
        light_ratio = self._contrast_ratio(bg_color, candidate_light)
        gold_ratio = self._contrast_ratio(bg_color, candidate_gold)
        if 7.0 <= star_value <= 10.0:
            if gold_ratio >= 4.5:
                return candidate_gold
            return candidate_light if light_ratio >= dark_ratio else candidate_dark
        if dark_ratio >= 4.5 or dark_ratio > light_ratio:
            return candidate_dark
        return candidate_light

    def _mode_tag_class(self, tag: str) -> str:
        normalized = tag if tag in {"RC", "LN", "HB", "Mix"} else "Mix"
        return f"mode-{normalized.lower()}"