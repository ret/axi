from __future__ import division

import time

from math import modf
from serial import Serial
from serial.tools.list_ports import comports

from .planner import Planner
from .progress import Bar

TIMESLICE_MS = 15

MICROSTEPPING_MODE = 2
STEP_DIVIDER = 2 ** (MICROSTEPPING_MODE - 1)

STEPS_PER_INCH = 2032 / STEP_DIVIDER
STEPS_PER_MM = 80 / STEP_DIVIDER

PEN_UP_POSITION = 60
PEN_UP_SPEED = 150
PEN_UP_DELAY = 0

PEN_DOWN_POSITION = 50
PEN_DOWN_SPEED = 150
PEN_DOWN_DELAY = 0

ACCELERATION = 8
MAX_VELOCITY = 2
CORNER_FACTOR = 0.005

VID_PID = '04D8:FD92'

def find_port():
    for port in comports():
        if VID_PID in port[2]:
            return port[0]
    return None

class Device(object):
    def __init__(self, **kwargs):
        self.steps_per_unit = STEPS_PER_INCH
        self.pen_up_position = PEN_UP_POSITION
        self.pen_up_speed = PEN_UP_SPEED
        self.pen_up_delay = PEN_UP_DELAY
        self.pen_down_position = PEN_DOWN_POSITION
        self.pen_down_speed = PEN_DOWN_SPEED
        self.pen_down_delay = PEN_DOWN_DELAY
        self.acceleration = ACCELERATION
        self.max_velocity = MAX_VELOCITY
        self.corner_factor = CORNER_FACTOR

        for k, v in kwargs.items():
            setattr(self, k, v)

        self.error = (0, 0) # accumulated step error

        port = find_port()
        if port is None:
            raise Exception('cannot find axidraw device')
        self.serial = Serial(port, timeout=1)
        self.configure()

    def configure(self):
        servo_min = 7500
        servo_max = 28000
        pen_up_position = self.pen_up_position / 100
        pen_up_position = int(
            servo_min + (servo_max - servo_min) * pen_up_position)
        pen_down_position = self.pen_down_position / 100
        pen_down_position = int(
            servo_min + (servo_max - servo_min) * pen_down_position)
        self.command('SC', 4, pen_up_position)
        self.command('SC', 5, pen_down_position)
        self.command('SC', 11, int(self.pen_up_speed * 5))
        self.command('SC', 12, int(self.pen_down_speed * 5))

    def close(self):
        self.serial.close()

    def make_planner(self):
        return Planner(
            self.acceleration, self.max_velocity, self.corner_factor)

    def readline(self):
        return self.serial.readline().strip()

    def command(self, *args):
        line = ','.join(map(str, args))
        self.serial.write(line + '\r')
        return self.readline()

    # higher level functions
    def move(self, dx, dy):
        self.run_path([(0, 0), (dx, dy)])

    def goto(self, x, y):
        px, py = self.read_position()
        self.run_path([(px, py), (x, y)])

    def home(self):
        self.goto(0, 0)

    # misc commands
    def version(self):
        return self.command('V')

    # motor functions
    def enable_motors(self):
        m = MICROSTEPPING_MODE
        return self.command('EM', m, m)

    def disable_motors(self):
        return self.command('EM', 0, 0)

    def motor_status(self):
        return self.command('QM')

    def zero_position(self):
        return self.command('CS')

    def read_position(self):
        response = self.command('QS')
        self.readline()
        a, b = map(int, response.split(','))
        a /= self.steps_per_unit
        b /= self.steps_per_unit
        y = (a - b) / 2
        x = y + b
        return x, y

    def stepper_move(self, duration, a, b):
        return self.command('XM', duration, a, b)

    def wait(self):
        while '1' in self.motor_status():
            time.sleep(0.01)

    def run_plan(self, plan):
        step_ms = TIMESLICE_MS
        step_s = step_ms / 1000
        t = 0
        while t < plan.t:
            i1 = plan.instant(t)
            i2 = plan.instant(t + step_s)
            d = i2.p.sub(i1.p)
            ex, ey = self.error
            ex, sx = modf(d.x * self.steps_per_unit + ex)
            ey, sy = modf(d.y * self.steps_per_unit + ey)
            self.error = ex, ey
            self.stepper_move(step_ms, int(sx), int(sy))
            t += step_s
        self.wait()

    def run_path(self, path):
        planner = self.make_planner()
        plan = planner.plan(path)
        self.run_plan(plan)

    def run_drawing(self, drawing, progress=True):
        self.pen_up()
        position = (0, 0)
        bar = Bar(enabled=progress)
        for path in bar(drawing.paths):
            self.run_path([position, path[0]])
            self.pen_down()
            self.run_path(path)
            self.pen_up()
            position = path[-1]
        self.run_path([position, (0, 0)])

    def plan_drawing(self, drawing):
        result = []
        planner = self.make_planner()
        for path in drawing.all_paths:
            result.append(planner.plan(path))
        return result

    # pen functions
    def pen_up(self):
        delta = abs(self.pen_up_position - self.pen_down_position)
        duration = int(1000 * delta / self.pen_up_speed)
        delay = max(0, duration + self.pen_up_delay)
        return self.command('SP', 1, delay)

    def pen_down(self):
        delta = abs(self.pen_up_position - self.pen_down_position)
        duration = int(1000 * delta / self.pen_down_speed)
        delay = max(0, duration + self.pen_down_delay)
        return self.command('SP', 0, delay)
