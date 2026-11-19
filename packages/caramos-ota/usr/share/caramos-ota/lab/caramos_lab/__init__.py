"""Phòng máy (CaramOS computer lab): one-click classroom management with Veyon or Epoptes.

The teacher's computer runs Veyon Master (view the class, show the teacher's screen, lock screens, remote control,
send files, power off) or Epoptes, the lighter one. Students' computers are paired over the school LAN: the
teacher's window shows a 6-digit code, a student's window finds the teacher's computer and asks for that code,
which proves the key or certificate it downloaded is the teacher's. See pairing.py for the protocol, helper.py for
what runs as root, app.py for the window.
"""

STATE_DIR = "/var/lib/caramos-ota/lab"
VEYON = "veyon"
EPOPTES = "epoptes"
BACKENDS = (VEYON, EPOPTES)
TEACHER = "teacher"
STUDENT = "student"
