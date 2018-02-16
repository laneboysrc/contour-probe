#!/usr/bin/env python3
'''

Use a 3D printer to scan a vertical surface

Refer to README.md for more information.

'''
from collections import namedtuple
from decimal import Decimal

import argparse
import os
import random
import socket
import sys
import time

try:
    import eel
except ImportError:
    print('eel library not present; please run\n')
    print('    source env/bin/activate')
    sys.exit(1)

# UNIX socket name for the communication between server and client
SERVER_ADDRESS = './.probe_socket'

# G-code definitions for Lulzbot Mini
GCODE_HOME = 'G28'
GCODE_METRIC = 'G21'

GCODE_WAIT_UNTIL_MOVE_FINISHED = 'G4 P0'

GCODE_ACCELERATE_Y_SLOW = 'M201 Y100'
GCODE_ACCELERATE_Y_FAST = 'M201 Y1000'
GCODE_ACCELERATE_X_SLOW = 'M201 X100'

GCODE_MOVE_Y_SLOW = 'G0 F100 Y'
GCODE_MOVE_Y_FAST = 'G0 F500 Y'

# Options for the eel library (UI using the Chrome browser)
WEB_FOLDER = 'web'
WEB_APP_OPTIONS = {
    'mode': "chrome",   # "chrome-app" or "chrome"
    'port': 16953,
    # 'chromeFlags': ["--start-fullscreen", "--browser-startup-dialog"]
}

# Format strings used for generating the OpenSCAD file of the scan
SCAD_HEADER = '''/*

To use this scanned object in another OpenSCAD file, use

    use <{name}.scad>;

{info}
*/

// Preview:
translate(-{name}_offset()) {name}();

// Function to retrieve the objects offset
function {name}_offset() = [{x}, {y}, {z}];

// Function to retrieve the objects size
function {name}_dim() = [{w}, {d}, {h}];

// The object as module
module {name}() {{
    polyhedron(
'''
SCAD_SECTION_POINTS = '        points = [\n'
SCAD_SECTION_SCANNED_POINTS = '            // Scanned points\n'
SCAD_SECTION_BACKPLANE_POINTS = '            // Backplane points\n'
SCAD_SECTION_FACES = '        ],\n        faces = [\n'
SCAD_SECTION_SCANNED_FACES = '            // Scanned faces\n'
SCAD_SECTION_BACKPLANE_FACES = '            // Backplane faces\n'
SCAD_SECTION_BOTTOM_FACES = '            // Bottom connecting faces\n'
SCAD_SECTION_TOP_FACES = '            // Top connecting faces\n'
SCAD_SECTION_LEFT_FACES = '            // Left connecting faces\n'
SCAD_SECTION_RIGHT_FACES = '            // Right connecting faces\n'
SCAD_POINT = '            [{}, {}, {}],\n'
SCAD_FACE_3 = '            [{}, {}, {}],\n'
SCAD_FACE_4 = '            [{}, {}, {}, {}],\n'
SCAD_TRAILER = '        ], convexity=10\n    );\n}\n'

OPENSCAD_FILE_EXTENSION = '.scad'


# When probing the surface, the probe approaches the object first using
# PROBE_STEP_LONG steps. Once triggered, the probe retracts and gets a
# more accurate result using PROBE_STEP_SHORT.
PROBE_STEP_LONG = 0.5
PROBE_STEP_SHORT = 0.01

# Value for rounding to two decimal places
NPLACES = Decimal('.01')

# Define a Point object; each Point has a x, y and z member
Point = namedtuple('Point', ['x', 'y', 'z'])


def dict_to_point(point_dict):
    ''' Convert a dict with x, y and z elements into a Point object '''
    return Point(point_dict['x'], point_dict['y'], point_dict['z'])


def round_str(value):
    ''' Round a Decimal() value to two decimal places and return it as string '''
    return str(Decimal(value).quantize(NPLACES))


def round_int(value):
    ''' Round a Decimal() value to two decimal places and return it as Decimal() '''
    return Decimal(value).quantize(NPLACES)


class DummyCMM():
    '''
    Hardware simulation for debugging and testing.

    To use this simulated hardware start the application with

        ./probe.py --mode=dummy

    Logs all G-code command sent to the 'printer' and triggers the probe
    randomly.
    '''

    def __init__(self):
        self.max = 5
        self.triggered = random.randint(1, self.max)

    def send_gcode(self, gcode):
        ''' Send G-code to the printer '''
        print('>>GCODE', gcode)

    def has_probe_triggered(self):
        ''' Returns True if the probe switch has triggered, otherwise False '''
        if self.triggered:
            self.triggered -= 1
            print('>>Probe', False)
            return False

        self.triggered = random.randint(1, self.max)
        print('>>Probe', True)
        return True


class ServerCMM():
    '''
    Class to communicate with a server instance of probe.py.

    For development purpose the application can operate in server/client
    mode. The server controls the hardware via the serial ports. The
    client can be started and stopped any time without having to reset
    the 3D printer each time.

    This class is used when invoking probe.py as client:

        ./probe.py --mode=client

    '''

    def __init__(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(SERVER_ADDRESS)
        except FileNotFoundError:
            print("Unable to connect to the server")
            sys.exit(1)

    def send_gcode(self, gcode):
        ''' Send G-code to the printer '''
        self.sock.sendall(b'G' + gcode.encode('ASCII'))
        self.sock.recv(16)

    def has_probe_triggered(self):
        ''' Returns True if the probe switch has triggered, otherwise False '''
        self.sock.sendall(b'P')
        data = self.sock.recv(16)
        return data == b'1'


class SerialCMM():
    '''
    Class to communicate with a 3D printer and the touch probe over
    serial ports.

    The application uses the 3D printer connected via USB, implementing
    a serial port (/dev/ttyACM0 for the Lulzbot Mini).

    The probe switch is connected to a USB-to-serial adapter, on the CTS
    signal pin.

    This class is used when invoking probe.py in direct mode (default) or
    as server:

        ./probe.py --mode=direct
        ./probe.py                  (implies --mode=direct)
        ./probe.py --mode=server

    '''

    def __init__(self, printer, baudrate, probe):
        import serial

        try:
            self.printer = serial.Serial(printer, baudrate)
        except serial.serialutil.SerialException:
            print('Unable to open 3D printer serial port at {}'.format(printer))
            sys.exit(1)

        try:
            self.probe = serial.Serial(probe)
        except serial.serialutil.SerialException:
            print('Unable to open Probe serial port at {}'.format(probe))
            sys.exit(1)

        print('SerialCMM: Waiting for printer to start up ...')
        self.printer.read_until(b'start\n')

        self.send_gcode(GCODE_METRIC)
        self.send_gcode(GCODE_ACCELERATE_Y_SLOW)

        print('Homing probe head ...')
        self.send_gcode('G0 F4000 Y180')
        # self.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)
        self.send_gcode(GCODE_HOME)
        self.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)

        if self.has_probe_triggered():
            print('WARNING: Probe is depressed, please release it')
        while self.has_probe_triggered():
            time.sleep(0.1)

    def send_gcode(self, gcode):
        ''' Send G-code to the printer '''
        self.printer.flushInput()
        self.printer.write(gcode.encode('ASCII') + b'\n')
        self.printer.read_until(b'ok\n')

    # def read_gcode_response(device, gcode):
    #     self.printer.flushInput()
    #     self.printer.write(gcode.encode('ASCII') + b'\n')
    #     while not self.printer.inWaiting():
    #         time.sleep(0.1)
    #     return self.printer.read_all()

    def has_probe_triggered(self):
        ''' Returns True if the probe switch has triggered, otherwise False '''
        return not self.probe.getCTS()


class Emitter():
    '''
    Collects the scanned points and outputs the OpenSCAD polyhedron after
    the scan has finished.
    '''

    def __init__(self, filename):
        self.filename = filename
        self.points = []
        self.rows = []
        self.previous_z = -1
        self.start_time = time.time()

    def add_point(self, point):
        ''' Add a probe result to the dataset '''
        print('Adding point', point)

        if self.previous_z != point.z:
            # Output the SCAD file after every scan line
            self.write_scad()
            # Add the new scan row
            self.previous_z = point.z
            self.rows.append(len(self.points))

        self.points.append(point)

    def done(self, duration=0):
        ''' Signals that the scan has finished '''
        self.write_scad()

    def write_scad(self):
        ''' Outputs the scan result as polyhedron in an OpenSCAD file '''

        thickness = 5
        num_points = len(self.points)
        num_rows = len(self.rows)
        num_cols = 0
        if num_rows > 1:
            num_cols = self.rows[1]
        last_row = num_rows - 1
        last_col = num_cols - 1

        if num_rows < 2  or  num_cols < 2:
            print('Scan consists only of a single line, can not create polyhedron')
            return

        # Find the minimum and maximum extent of the scanned surface in
        # all axis
        p_min = [999, 999, 999]
        p_max = [0, 0, 0]
        for point in self.points:
            p_min[0] = min(point.x, p_min[0])
            p_min[1] = min(point.y, p_min[1])
            p_min[2] = min(point.z, p_min[2])
            p_max[0] = max(point.x, p_max[0])
            p_max[1] = max(point.y, p_max[1])
            p_max[2] = max(point.z, p_max[2])

        points_min = Point(x=p_min[0], y=p_min[1], z=p_min[2])
        points_max = Point._make(p_max)

        backplane_y = points_min.y - thickness
        dim = [points_max[index] - points_min[index] for index in range(3)]
        dim[1] += thickness

        now = time.time()
        elapsed_time = int(now - self.start_time)
        print('Scan took {} seconds'.format(elapsed_time))


        info = '''Number of scanned vertices (num_points):', {num_points}
Minimum extent (points_min):', {points_min}
Maximum extent (points_max):', {points_max}
Number of rows (num_rows):', {num_rows}
Number of columns (num_cols):', {num_cols}

Scan took {elapsed_time} seconds
'''.format(num_points=num_points, points_min=points_min, points_max=points_max,
           num_rows=num_rows, num_cols=num_cols, elapsed_time=elapsed_time)

        print(info)

        output_file = open(self.filename + OPENSCAD_FILE_EXTENSION, 'w')
        output_file.write(SCAD_HEADER.format(
            name=self.filename, info=info,
            x=points_min.x, y=backplane_y, z=points_min.z,
            w=dim[0], d=dim[1], h=dim[2]))

        # Write out all scanned points.
        # The first point is "index 0" (we need to reference the point
        # indices further down when creating the faces)

        output_file.write(SCAD_SECTION_POINTS)

        output_file.write(SCAD_SECTION_SCANNED_POINTS)
        for point in self.points:
            output_file.write(SCAD_POINT.format(
                round_str(point.x), round_str(point.y), round_str(point.z)))

        # Write backplane points.
        # The backplane perimeter needs to have a point on each of the colums
        # and rows, but no points are needed inside the plane.

        backplane_points = []
        backplane_rows = []

        for row in range(num_rows):
            # Bottom and top row
            if row == 0  or  row == last_row:
                backplane_rows.append(len(backplane_points))
                for col in range(num_cols):
                    point = self.points[row * num_cols + col]
                    backplane_points.append(Point(point.x, backplane_y, point.z))
            # Rows in-between
            else:
                left = self.points[row * num_cols]
                right = self.points[row * num_cols + last_col]

                backplane_rows.append(len(backplane_points))
                backplane_points.append(Point(left.x, backplane_y, left.z))
                backplane_points.append(Point(right.x, backplane_y, right.z))


        output_file.write(SCAD_SECTION_BACKPLANE_POINTS)
        for point in backplane_points:
            output_file.write(SCAD_POINT.format(
                round_str(point.x), round_str(point.y), round_str(point.z)))

        # Points done, generate the faces

        # =================================================================
        # IMPORTANT:
        # the points of each face have to be in the correct order,
        # otherwise the "normals" are wrong and the resulting object is
        # unusable for further processing in OpenSCAD.
        #
        # From the OpenSCAD documentation:
        #
        #       All faces must have points ordered in the same direction.
        #       OpenSCAD prefers clockwise when looking at each face from
        #       outside inwards. The back is viewed from the back, the bottom
        #       from the bottom, etc..
        #
        # =================================================================

        output_file.write(SCAD_SECTION_FACES)

        output_file.write(SCAD_SECTION_SCANNED_FACES)
        for row in range(num_rows - 1):
            for col in range(num_cols - 1):
                pt1 = row * num_cols + col
                pt2 = pt1 + 1
                pt3 = (row + 1) * num_cols + col
                pt4 = pt3 + 1

                output_file.write(SCAD_FACE_3.format(pt1, pt2, pt3))
                output_file.write(SCAD_FACE_3.format(pt2, pt4, pt3))

        # Write the faces that make the backplane
        # The backplane is constructed from points at each row and colum on
        # the perimeter of the plane. Therefore for the top and bottom row we
        # have to use triangles, but for the inner section we can use quads

        output_file.write(SCAD_SECTION_BACKPLANE_FACES)
        first_backplane_point = num_points
        for row in range(num_rows - 1):
            # Bottom row: use triangles
            if row == 0:
                pt3 = first_backplane_point + backplane_rows[1]
                for col in range(num_cols - 1):
                    pt1 = first_backplane_point + col
                    pt2 = pt1 + 1
                    output_file.write(SCAD_FACE_3.format(pt3, pt2, pt1))
                # Closing the plane
                output_file.write(SCAD_FACE_3.format(pt3 - 1, pt3, pt3 + 1))
            # Top row: use triangles
            elif row == last_row - 1:
                pt3 = first_backplane_point + backplane_rows[row] + 1
                for col in range(num_cols - 1):
                    pt1 = pt3 + 1 + col
                    pt2 = pt1 + 1
                    output_file.write(SCAD_FACE_3.format(pt1, pt2, pt3))
                # Closing the plane
                output_file.write(SCAD_FACE_3.format(pt3 + 1, pt3, pt3 - 1))
            # Rows in-between: use quads
            else:
                # Since in-between rows only store the left and rightmost
                # colum values, we can use simple addition to index the four
                # points
                #
                #   pt3    pt4
                #   pt1    pt2
                #
                pt1 = first_backplane_point + backplane_rows[row]
                pt2 = pt1 + 1
                pt3 = pt1 + 2
                pt4 = pt1 + 3
                output_file.write(SCAD_FACE_4.format(pt3, pt4, pt2, pt1))

        # Write the faces that connect the front and backplane

        output_file.write(SCAD_SECTION_BOTTOM_FACES)
        for col in range(num_cols - 1):
            pt1 = col
            pt2 = pt1 + 1
            pt3 = first_backplane_point + col
            pt4 = pt3 + 1
            output_file.write(SCAD_FACE_4.format(pt1, pt3, pt4, pt2))

        output_file.write(SCAD_SECTION_TOP_FACES)
        for col in range(num_cols - 1):
            pt1 = self.rows[last_row] + col
            pt2 = pt1 + 1
            pt3 = first_backplane_point + backplane_rows[last_row] + col
            pt4 = pt3 + 1
            output_file.write(SCAD_FACE_4.format(pt1, pt2, pt4, pt3))

        output_file.write(SCAD_SECTION_LEFT_FACES)
        for row in range(num_rows - 1):
            pt1 = self.rows[row]
            pt2 = self.rows[row + 1]
            pt3 = first_backplane_point + backplane_rows[row]
            pt4 = first_backplane_point + backplane_rows[row + 1]
            output_file.write(SCAD_FACE_4.format(pt1, pt2, pt4, pt3))

        output_file.write(SCAD_SECTION_RIGHT_FACES)
        for row in range(num_rows - 1):
            pt1 = self.rows[row] + num_cols - 1
            pt2 = self.rows[row + 1] + num_cols - 1
            if row == 0:
                pt3 = first_backplane_point + backplane_rows[row] + num_cols - 1
                pt4 = first_backplane_point + backplane_rows[row + 1] + 1
            elif row == last_row - 1:
                pt3 = first_backplane_point + backplane_rows[row] + 1
                pt4 = first_backplane_point + backplane_rows[row + 1] + num_cols - 1
            else:
                pt3 = first_backplane_point + backplane_rows[row] + 1
                pt4 = first_backplane_point + backplane_rows[row + 1] + 1
            output_file.write(SCAD_FACE_4.format(pt1, pt3, pt4, pt2))

        # All done, finish

        output_file.write(SCAD_TRAILER)
        output_file.close()


class Probe():
    '''
    Class the operates the probe on an abstract level.

    The probe uses one of the hardware configurations (direct serial control,
    server/client, or simulated hardware).

    Users of this class can move the probe, and execute probe cycles.
    '''

    def __init__(self, cmm):
        self.cmm = cmm
        self.cmm.send_gcode(GCODE_METRIC)
        self.cmm.send_gcode(GCODE_ACCELERATE_Y_SLOW)
        self.cmm.send_gcode(GCODE_ACCELERATE_X_SLOW)

    def move_to(self, point):
        '''
        Move the probe to a given coordinate

        The Y axis is moved first, then the X and Z axis together. This is
        done to ensure the object to scan is cleared safely.
        '''
        self.cmm.send_gcode(GCODE_ACCELERATE_Y_SLOW)
        self.cmm.send_gcode('G0 F4000 Y%s' % (round_str(point.y)))
        self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)
        self.cmm.send_gcode('G0 F4000 X%s Z%s' % (round_str(point.x), round_str(point.z)))
        self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)

    def probe(self, start):
        ''' Perform a probe in Y direction '''
        y_pos = Decimal(start)

        self.cmm.send_gcode(GCODE_ACCELERATE_Y_FAST)
        while y_pos > 0:
            y_pos -= Decimal(PROBE_STEP_LONG)
            self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)
            self.cmm.send_gcode(GCODE_MOVE_Y_FAST + round_str(y_pos))
            if self.cmm.has_probe_triggered():
                # Move back until the probe no longer touches
                y_pos += Decimal(PROBE_STEP_LONG)
                self.cmm.send_gcode(GCODE_MOVE_Y_FAST + round_str(y_pos))
                self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)

                while self.cmm.has_probe_triggered():
                    y_pos += Decimal(PROBE_STEP_LONG)
                    self.cmm.send_gcode(GCODE_MOVE_Y_FAST + round_str(y_pos))
                    self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)

                while y_pos > 0:
                    y_pos -= Decimal(PROBE_STEP_SHORT)
                    self.cmm.send_gcode(GCODE_MOVE_Y_SLOW + round_str(y_pos))
                    self.cmm.send_gcode(GCODE_WAIT_UNTIL_MOVE_FINISHED)

                    if self.cmm.has_probe_triggered():
                        return round_int(y_pos)

                print("Probe never triggered during slow probing, object not found")
                return 0

        print("Probe never triggered, object not found")
        return 0

    def scan(self, start, end, x_step=1, z_step=1, y_clearance=None, name='scan'):
        '''
        Scan a vertical surface, starting from *start* until reaching *end*.

        *start* is the lower-left coordinate of the area to scan.

        *end* is the upper-right coordinate of the area to scan.

        *x_step* and *z_step* specify the step width in the respective
            direction, i.e. how far the probe is moved for each scan step.

        *y_clearance* declares how far the probe is moved back in Y position
            before the next scan. If the value is not given then the probe
            is moved back to the start Y position for each scan. Specifying
            y_clearance can reduce scan time, but setting it too low can
            cause that the probe crashes into the object when moving to the
            next scan position.

        *name* specifies the resulting OpenSCAD filename, and the module name
            of the generated polyhedron. Ensure the name does not contain
            whitespace or special characters.

        '''

        emitter = Emitter(name)

        print('Moving probe head to starting position ...')
        self.move_to(start)

        pos = Point(round_int(start.x), round_int(start.y), round_int(start.z))

        while pos.z <= end.z:
            while pos.x <= end.x:
                self.move_to(pos)

                pos = pos._replace(y=self.probe(pos.y))
                # print('Probe touched at {}'.format(pos))
                emitter.add_point(pos)
                eel.progress(round_str(pos.x), round_str(pos.y), round_str(pos.z))

                # Move the probe back in Y only to clear the part
                if y_clearance:
                    pos = pos._replace(y=pos.y+y_clearance)
                else:
                    pos = pos._replace(y=start.y)
                self.move_to(pos)

                next_x = round_int(Decimal(pos.x) + Decimal(x_step))
                pos = pos._replace(x=next_x)

            next_x = round_int(Decimal(pos.x) - Decimal(x_step))
            pos = pos._replace(x=next_x, y=start.y)
            self.move_to(pos)

            next_z = round_int(Decimal(pos.z) + Decimal(z_step))
            pos = pos._replace(x=start.x, z=next_z)

        self.move_to(start)
        emitter.done()


def server(cmm):
    '''
    Run in server mode.

    Listens on a UNIX socket for G-code and probe commands, and performs
    them on the hardware.
    '''

    # Make sure the socket does not already exist
    try:
        os.unlink(SERVER_ADDRESS)
    except OSError:
        if os.path.exists(SERVER_ADDRESS):
            raise

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    # Bind the socket to the port
    print('Starting up server on %s' % SERVER_ADDRESS)
    sock.bind(SERVER_ADDRESS)
    sock.listen(1)

    while True:
        # Wait for a connection
        print('Waiting for a connection')
        connection, _ = sock.accept()
        try:
            print('Client connected')

            while True:
                data = connection.recv(512)
                if data:
                    data = data.decode('ASCII')
                    print('Received "%s"' % data)
                    if data[0] == 'G':
                        if len(data) > 1:
                            cmm.send_gcode(data[1:])
                        else:
                            print('ERROR: empty G code!')
                        connection.sendall(b'ok\n')
                    elif data[0] == 'P':
                        if cmm.has_probe_triggered():
                            connection.sendall(b'1')
                        else:
                            connection.sendall(b'0')
                else:
                    print('Client disconnected')
                    break

        except BaseException:
            # On any error close the connection and wait for the next one
            connection.close()

        finally:
            # Clean up the connection
            connection.close()


def client(cmm):
    '''
    Run in client mode.

    The user interface is written in HTML, using the Eel library.
    https://github.com/ChrisKnott/Eel

    Two function are exposed to JavaScript: 'move_to' and 'scan'.

    '''
    probe = Probe(cmm)

    @eel.expose
    def scan(start, end, x_step=5, z_step=5, y_clearance=None, name='scan'):
        ''' Start a scan '''
        print('EEL: scan(start={}, end={}, x_step={}, z_step={}, y_clearance={}, name={})'.format(
            start, end, x_step, z_step, y_clearance, name))

        start = dict_to_point(start)
        end = dict_to_point(end)
        print(start)
        probe.scan(start, end, x_step, z_step, y_clearance, name)


    @eel.expose
    def move_to(point):
        ''' Jog the probe to a given position '''
        print('EEL: move_to(point={})'.format(point))

        point = dict_to_point(point)
        probe.move_to(point)

    eel.init(WEB_FOLDER)
    eel.log('Python connected!')
    eel.start('index.html', options=WEB_APP_OPTIONS)


def main():
    '''
    Parse commandline arguments and launch the corresponding part
    of the application
     '''

    parser = argparse.ArgumentParser(description='3D printer surface scanner.')
    parser.add_argument('--mode', '-m', default='direct',
                        choices=['direct', 'server', 'client', 'dummy'],
                        help='Run the hardware directly, or in server/client mode')

    parser.add_argument('--server', '-s', dest='mode', action='store_const', const='server',
                        help='Run in server mode (shortcut for --mode=server')

    parser.add_argument('--client', '-c', dest='mode', action='store_const', const='client',
                        help='Run in client mode (shortcut for --mode=client')

    parser.add_argument('--printer', '-p', default='/dev/ttyACM0',
                        help='Serial port of the 3D printer. Default: /dev/ttyACM0')

    parser.add_argument('--baudrate', '-b', default=115200,
                        help='Baudrate of the 3D printer serial port. Default: 115200')

    parser.add_argument('--probe', default='/dev/ttyUSB0',
                        help='Serial port of the touch probe. Default: /dev/ttyUSB0')

    args = parser.parse_args()

    # Determine which CMM type to use:
    #   - if we are a client, we use the ServerCMM
    #   - if dummy CMM is requested, we use a simulated CMM
    #   - in all other cases (direct mode, server mode) we use the Serial port CMM
    if args.mode == 'client':
        client(ServerCMM())
    elif args.mode == 'dummy':
        client(DummyCMM())
    elif args.mode == 'direct':
        client(SerialCMM(args.printer, args.baudrate, args.probe))
    elif args.mode == 'server':
        server(SerialCMM(args.printer, args.baudrate, args.probe))


if __name__ == '__main__':
    main()
