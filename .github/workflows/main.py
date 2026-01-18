import re
import ast
import math
import operator as op
import sqlite3
import os

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, RoundedRectangle
from kivy.utils import get_color_from_hex
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.animation import Animation
from kivy.metrics import dp
from kivy.core.window import Window

# ---------- UPGRADED MATH PARSER (3.13 COMPLIANT) ----------
class MathParser:
    def __init__(self, use_degrees=True):
        self.use_degrees = use_degrees
        # Whitelist of allowed operations
        self.operators = {
            ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
            ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod, 
            ast.USub: op.neg, ast.UAdd: lambda x: x
        }
        self.constants = {'pi': math.pi, 'e': math.e}
        self.functions = {
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
            'log': math.log10, 'ln': math.log, 'sqrt': math.sqrt, 'radians': math.radians
        }
        self._trig_re = re.compile(r'(?<![a-zA-Z_])(?P<fn>sin|cos|tan)\s*\(')

    def evaluate(self, expression: str):
        expression = (expression or '').strip()
        if not expression: raise ValueError("Empty")

        # UPGRADE: Handling implicit multiplication (e.g., 5pi, 2(3))
        expression = expression.replace('π', 'pi').replace('^', '**').replace('√', 'sqrt')
        expression = re.sub(r'(\d)(pi|e|\()', r'\1*\2', expression)
        expression = re.sub(r'(\))(\d|\()', r'\1*\2', expression)

        if self.use_degrees:
            expression = self._trig_re.sub(r"\g<fn>(radians(", expression)

        # UPGRADE: Auto-balancing parentheses
        diff = expression.count('(') - expression.count(')')
        if diff > 0: expression += ')' * diff

        node = ast.parse(expression, mode='eval').body
        return self._eval(node)

    def _eval(self, node):
        # UPGRADE: ast.Constant is the standard for Python 3.8 to 3.13+
        if isinstance(node, ast.Constant): return node.value
        if isinstance(node, ast.Num): return node.n # Legacy fallback
        if isinstance(node, ast.Name):
            if node.id in self.constants: return self.constants[node.id]
            raise NameError(node.id)
        if isinstance(node, ast.BinOp):
            return self.operators[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return self.operators[type(node.op)](self._eval(node.operand))
        if isinstance(node, ast.Call):
            fname = node.func.id
            if fname not in self.functions: raise NameError(fname)
            return self.functions[fname](*[self._eval(a) for a in node.args])
        raise TypeError("Unsupported")

# ---------- UI STYLING ----------
COLORS = {
    'bg': '#050505', 'display': '#1e2229', 'accent': '#2979ff',
    'num': '#263238', 'op': '#1c252b', 'err': '#ff5252', 'text': '#ffffff'
}

class StyledButton(Button):
    def __init__(self, bg_color=COLORS['num'], **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.btn_color = get_color_from_hex(bg_color)
        with self.canvas.before:
            self.color_obj = Color(rgba=self.btn_color)
            self.rect = RoundedRectangle(size=self.size, pos=self.pos, radius=[dp(12)])
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, instance, value):
        self.rect.pos, self.rect.size = instance.pos, instance.size

    # UPGRADE: Haptic-style feedback on touch
    def on_press(self):
        self.color_obj.a = 0.5
    def on_release(self):
        self.color_obj.a = 1.0

# ---------- MAIN APP ----------
class LegendaryCalc(App):
    expression = StringProperty('0')
    is_deg = BooleanProperty(True)
    mem = NumericProperty(0)

    def build(self):
        # UPGRADE: Safer Android DB pathing
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.db_path = os.path.join(self.user_data_dir, 'history.db')
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute('CREATE TABLE IF NOT EXISTS log (entry TEXT)')
        
        root = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(8))

        # Display Area
        display_box = BoxLayout(orientation='vertical', size_hint_y=0.28, padding=dp(18))
        with display_box.canvas.before:
            self.bg_color = Color(rgba=get_color_from_hex(COLORS['display']))
            self.bg_rect = RoundedRectangle(radius=[dp(20)])
        display_box.bind(pos=self._update_ui, size=self._update_ui)

        # Status/Header
        status = BoxLayout(size_hint_y=0.2)
        self.unit_btn = Button(text='DEG', background_color=(0,0,0,0), color=get_color_from_hex(COLORS['accent']), bold=True)
        self.unit_btn.bind(on_release=self.toggle_unit)
        status.add_widget(self.unit_btn)
        status.add_widget(Label(size_hint_x=0.5))
        hist_btn = Button(text='HISTORY', background_color=(0,0,0,0), color=get_color_from_hex(COLORS['accent']))
        hist_btn.bind(on_release=self.show_log)
        status.add_widget(hist_btn)
        display_box.add_widget(status)

        # UPGRADE: Reactive Label binding for instant updates
        self.lbl = Label(text=self.expression, halign='right', valign='center', font_size='48sp')
        self.lbl.bind(size=self._update_lbl)
        self.bind(expression=self._sync_expression)
        display_box.add_widget(self.lbl)
        
        root.add_widget(display_box)

        # Keypad Grid
        grid = GridLayout(cols=5, spacing=dp(8), size_hint_y=0.72)
        keys = [
            'AC', 'DEL', 'MS', 'MR', '/',
            'sin', 'cos', 'tan', '(', ')',
            '7', '8', '9', '*', '^',
            '4', '5', '6', '-', '%',
            '1', '2', '3', '+', '√',
            'π', '0', '.', 'e', '='
        ]
        for k in keys:
            c = COLORS['num']
            if k in ['/','*','-','+','=','^','%']: c = COLORS['accent']
            elif k in ['AC','DEL']: c = COLORS['err']
            elif k in ['MS', 'MR']: c = '#546e7a'
            btn = StyledButton(text=k, bg_color=c, font_size='18sp')
            btn.bind(on_press=self.on_key) # Trigger on press for speed
            grid.add_widget(btn)
        
        root.add_widget(grid)
        return root

    def _sync_expression(self, inst, val):
        self.lbl.text = val

    def _update_ui(self, i, v):
        self.bg_rect.pos, self.bg_rect.size = i.pos, i.size

    def _update_lbl(self, i, v):
        i.text_size = (i.width - dp(24), None)

    def toggle_unit(self, _):
        self.is_deg = not self.is_deg
        self.unit_btn.text = 'DEG' if self.is_deg else 'RAD'

    def on_key(self, instance):
        val = instance.text
        if val == 'AC': 
            self.expression = '0'
        elif val == 'DEL': 
            self.expression = (self.expression[:-1] or '0')
        elif val == 'MS': 
            try: self.mem = float(self.expression)
            except: pass
        elif val == 'MR': 
            self.expression = (str(self.mem) if self.expression == '0' else self.expression + str(self.mem))
        elif val == '=': 
            self.run_math()
        else:
            # Special Handling for functions
            token = 'sqrt(' if val == '√' else (val + '(' if val in ['sin','cos','tan'] else val)
            if self.expression == '0' and val not in ('.','%'):
                self.expression = token
            else:
                self.expression += token

    def run_math(self):
        try:
            p = MathParser(use_degrees=self.is_deg)
            res = p.evaluate(self.expression)
            formatted = '{:.8g}'.format(res)
            # Store to history
            self.conn.execute('INSERT INTO log VALUES (?)', (f"{self.expression} = {formatted}",))
            self.conn.commit()
            self.expression = formatted
        except:
            # Error animation
            anim = Animation(rgba=get_color_from_hex(COLORS['err']), duration=0.1) + \
                   Animation(rgba=get_color_from_hex(COLORS['display']), duration=0.2)
            anim.start(self.bg_color)
            self.expression = 'Error'

    def show_log(self, _):
        v = ModalView(size_hint=(0.85, 0.75))
        scroll = ScrollView()
        box = BoxLayout(orientation='vertical', size_hint_y=None, padding=dp(20), spacing=dp(10))
        box.bind(minimum_height=box.setter('height'))
        cursor = self.conn.execute('SELECT entry FROM log ORDER BY rowid DESC LIMIT 50')
        for row in cursor:
            lbl = Label(text=row[0], size_hint_y=None, height=dp(42), halign='left')
            lbl.bind(size=lambda l, v: setattr(l, 'text_size', (l.width, None)))
            box.add_widget(lbl)
        scroll.add_widget(box)
        v.add_widget(scroll)
        v.open()

if __name__ == '__main__':
    LegendaryCalc().run()
