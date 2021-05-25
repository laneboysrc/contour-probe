# Contour Probe

This program can be used in conjunction with a 3D printer to scan the vertical surface of an object. It serves as a poor-man's 3D scanner.

A small micro-switch is mounted to the hot-end, and the object to scan is secured to the build plate. Using the GUI, you define a rectangular area in X and Z direction to scan. Once defined, the 3D printer probes the object in regular intervals and creates an OpenSCAD output file.

This program was designed for the Lulzbot Mini. Other 3D printers with USB port may work, but will most likely require changes to this program.


# Important

This software is incredibly simple and has not been fully tested. It may crash, and may cause damage to your 3D printer or object to scan.


# Requirements

* Lulzbot Mini
* A computer running Linux (Ubuntu 16.04.3 tested; Raspberry Pi may work)
* Python 3
* Google Chrome or Chromium web browser
* USB-to-serial adapter with accessible CTS input
* Micro-switch
* A 1..10 KOhm resistor


# Hardware

The micro-switch is connected to the USB-Serial adapter between GND and CTS. The resistor is connected between VCC and CTS, it serves as pull-up resistor.

                                +----------+
    +---------------------+     |          |
    |                     |     |         +++
    |              VCC (+)+-----+         | |   1..10 KOhm
    |                     |               | |
    |                     |               +++
    | USB-to-serial       |                |
    | (USB UART)      CTS +----------------+
    |                     |                |
    |                     |                +
    |                     |                   X
    |              GND (-)+-----+            X
    |                     |     |           X   Micro-switch
    +---------------------+     |          X
                                |          |
                                +----------+


# Installation

    python3 -m venv env
    source env/bin/activate
    pip install --upgrade pip
    pip install eel pyserial


# Usage

    source env/bin/activate
    ./probe.py

The Chrome browser will start and show the UI of the application. Use the *Probe movement* section to find the desired start and end positions and enter them in the *Scanning* section. The *start* X/Y/Z values define the bottom/left corner, the *end* values the upper/right corner of the area to scan; when viewed from front of the 3D printer.

Enter the name of the scan, which will also be used as filename. Do not use spaces or special characters in the name.

Click the *scan* to start scanning.


# Development

By default the program controls the 3D printer and the USB-serial apapter that connects the probe switch directly. This causes the 3D printer to initialize and home every time the application is started, which is inconvenient for development.

The program can also run as server/client mode. The server controls the 3D printer and probe, and the client performs the actual function. Restarting the client does not require re-initialization of the 3D printer.

To start the server, run

    source env/bin/activate
    ./probe.py -s

To start the client, run

    source env/bin/activate
    ./probe.py -c


Furthermore, you can run the application with a dummy 3D printer and probe hardware. The probe returns a random surface of a certain depth. To use the dummy hardware, run the application as follows:

    source env/bin/activate
    ./probe.py --mode=dummy

